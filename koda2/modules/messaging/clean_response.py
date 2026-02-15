"""Clean LLM responses before sending to users.

This is the single authoritative post-processor for all outbound messages.
It runs immediately before sending via any channel (WhatsApp, dashboard, etc.).
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns that indicate LLM/tool metadata leaked into the response
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?\{.*?\}\s*\n?```", re.DOTALL)
_BARE_JSON_OBJ_RE = re.compile(r"^\s*\{.*\}\s*$", re.DOTALL)
_TOOL_CALL_RE = re.compile(
    r"(tool_call_id|function_call|tool_calls|\"name\"\s*:\s*\"|\"arguments\"\s*:\s*[\{\"'])",
    re.IGNORECASE,
)
_ROLE_METADATA_RE = re.compile(
    r'"role"\s*:\s*"(assistant|tool|function|system)"', re.IGNORECASE
)
_STATUS_SUCCESS_RE = re.compile(
    r'^\s*\{\s*"(status|success|result|ok)"\s*:', re.IGNORECASE
)


def clean_response(text: Optional[str]) -> str:
    """Clean an LLM response for user-facing delivery.

    Steps:
      1. Strip fenced JSON/code blocks that contain tool metadata.
      2. Remove inline JSON objects that look like tool results.
      3. If the entire message is JSON with no natural language, convert to friendly text.
      4. Strip residual whitespace / empty lines.

    Returns the cleaned string, or a friendly fallback if nothing remains.
    """
    if not text or not text.strip():
        return "Done \u2705"

    original = text
    cleaned = text

    # --- Step 1: Remove fenced JSON code blocks containing tool metadata ---
    def _strip_fenced_json(m: re.Match) -> str:
        block = m.group(0)
        if _TOOL_CALL_RE.search(block) or _ROLE_METADATA_RE.search(block):
            logger.debug("Stripped fenced JSON block with tool metadata")
            return ""
        return block  # keep non-tool JSON blocks (user might have asked for JSON)

    cleaned = _JSON_BLOCK_RE.sub(_strip_fenced_json, cleaned)

    # --- Step 2: Check if entire message is a bare JSON object ---
    stripped = cleaned.strip()
    if _BARE_JSON_OBJ_RE.match(stripped):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                # If it has tool/function metadata, convert to friendly text
                if _is_tool_metadata(data):
                    cleaned = _json_to_friendly(data)
                    logger.info("Converted pure tool-metadata JSON to friendly text")
                # If it looks like an action result, convert
                elif _is_action_result(data):
                    cleaned = _action_result_to_friendly(data)
                    logger.info("Converted action-result JSON to friendly text")
                # Otherwise it might be intentional JSON the user asked for
        except (json.JSONDecodeError, ValueError):
            pass

    # --- Step 3: Remove inline JSON fragments that look like tool calls ---
    # Match { ... } on a single line that contains tool_call markers
    def _strip_inline_tool_json(m: re.Match) -> str:
        fragment = m.group(0)
        if _TOOL_CALL_RE.search(fragment) or _ROLE_METADATA_RE.search(fragment):
            logger.debug("Stripped inline tool JSON fragment")
            return ""
        return fragment

    cleaned = re.sub(
        r"\{[^{}]{10,}\}",
        _strip_inline_tool_json,
        cleaned,
    )

    # --- Step 4: Clean up residual whitespace ---
    # Collapse 3+ newlines into 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        logger.warning(
            "Response was entirely metadata/JSON; using fallback. Original length: %d",
            len(original),
        )
        return "Done \u2705"

    return cleaned


def _is_tool_metadata(data: dict) -> bool:
    """Check if a dict looks like leaked tool/function call metadata."""
    tool_keys = {"tool_call_id", "tool_calls", "function_call", "function", "name", "arguments"}
    role_values = {"assistant", "tool", "function", "system"}
    keys = set(data.keys())
    if keys & tool_keys:
        return True
    if data.get("role") in role_values and ("content" in data or "tool_calls" in data):
        return True
    return False


def _is_action_result(data: dict) -> bool:
    """Check if a dict looks like an action/API result."""
    result_keys = {"status", "success", "result", "ok", "error", "message", "data"}
    keys = set(data.keys())
    return bool(keys & result_keys) and len(keys) <= 6


def _json_to_friendly(data: dict) -> str:
    """Convert tool metadata JSON to a friendly message."""
    # If there's a 'content' field with actual text, use that
    content = data.get("content")
    if content and isinstance(content, str) and content.strip():
        return content.strip()
    # If there's a message field
    message = data.get("message")
    if message and isinstance(message, str) and message.strip():
        return message.strip()
    return "Done \u2705"


def _action_result_to_friendly(data: dict) -> str:
    """Convert an action result JSON to a friendly message."""
    # Prefer 'message' field
    message = data.get("message")
    if message and isinstance(message, str) and message.strip():
        return message.strip()

    # Check status/success
    status = data.get("status", data.get("success"))
    result = data.get("result", data.get("data"))

    parts = []
    if status is not None:
        if status in (True, "success", "ok", "completed"):
            parts.append("Done \u2705")
        elif status in (False, "error", "failed"):
            error = data.get("error", data.get("message", "Something went wrong."))
            return f"Sorry, there was an error: {error}"
        else:
            parts.append(str(status))

    if result and isinstance(result, str) and result.strip():
        parts.append(result.strip())
    elif result and isinstance(result, dict):
        # Try to extract a message from nested result
        nested_msg = result.get("message", result.get("summary"))
        if nested_msg and isinstance(nested_msg, str):
            parts.append(nested_msg.strip())

    return " — ".join(parts) if parts else "Done \u2705"
