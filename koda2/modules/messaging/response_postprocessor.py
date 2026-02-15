"""Post-processor for LLM responses before sending to users.

Strips raw JSON blocks, tool/function call artifacts, and internal
structured data that should not appear in user-facing messages.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Pattern: fenced JSON code blocks (```json ... ``` or ``` ... ```)
_FENCED_JSON_BLOCK = re.compile(
    r"```(?:json)?\s*\n?\{[^`]*?\}\s*\n?```",
    re.DOTALL | re.IGNORECASE,
)

# Pattern: fenced code blocks that contain tool_call / function_call markers
_FENCED_TOOL_BLOCK = re.compile(
    r"```(?:json)?\s*\n?.*?(?:tool_call|function_call|tool_result|action_request).*?```",
    re.DOTALL | re.IGNORECASE,
)

# Pattern: standalone raw JSON objects (top-level { ... } spanning multiple lines)
_RAW_JSON_OBJECT = re.compile(
    r"(?:^|\n)(\{\s*\"(?:tool_call|function_call|action|tool_result|name|function"
    r"|type|arguments|results?)\"\s*:.*?\})(?:\n|$)",
    re.DOTALL,
)

# Pattern: lines that look like internal tool/function metadata
_TOOL_METADATA_LINE = re.compile(
    r"^\s*(?:Tool call|Function call|tool_call_id|function_call|Action result|Tool result)"
    r"\s*[:=].*$",
    re.MULTILINE | re.IGNORECASE,
)

# Pattern: square-bracket wrapped tool results like [tool_result: ...]
_BRACKET_TOOL_RESULT = re.compile(
    r"\[(?:tool_result|function_result|action_result)[^\]]*\]",
    re.IGNORECASE,
)


def _is_pure_json(text: str) -> bool:
    """Check if the entire text is just a JSON object/array with no prose."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")):
        try:
            json.loads(stripped)
            return True
        except (json.JSONDecodeError, ValueError):
            pass
    return False


def _extract_meaningful_content(json_text: str) -> Optional[str]:
    """Try to extract human-readable content from a JSON response."""
    try:
        data = json.loads(json_text.strip())
    except (json.JSONDecodeError, ValueError):
        return None

    if isinstance(data, dict):
        # Look for common human-readable keys
        for key in ("message", "response", "text", "content", "reply",
                    "answer", "summary", "result", "output", "description"):
            if key in data and isinstance(data[key], str) and data[key].strip():
                return data[key].strip()

        # If there's a "data" key with a message inside
        if "data" in data and isinstance(data["data"], dict):
            inner = data["data"]
            for key in ("message", "response", "text", "content", "reply"):
                if key in inner and isinstance(inner[key], str) and inner[key].strip():
                    return inner[key].strip()

    return None


def sanitize_response_for_user(text: str) -> str:
    """Remove internal/structured data from an LLM response before sending to user.

    This function:
    1. Strips fenced JSON code blocks (```json ... ```)
    2. Strips raw JSON objects containing tool/function call data
    3. Removes tool metadata lines
    4. If the entire response is pure JSON, extracts meaningful content
    5. Cleans up excess whitespace left behind

    Args:
        text: The raw LLM response text.

    Returns:
        Cleaned text suitable for user consumption.
    """
    if not text or not text.strip():
        return text

    original = text

    # Step 1: Check if the entire response is pure JSON
    if _is_pure_json(text.strip()):
        extracted = _extract_meaningful_content(text.strip())
        if extracted:
            logger.debug("Response was pure JSON; extracted meaningful content")
            return extracted
        # If we can't extract anything meaningful, log and return as-is
        # (the LLM may need to reformulate, but we shouldn't return empty)
        logger.warning("Response is pure JSON with no extractable human text")
        # Fall through to other cleaning steps

    # Step 2: Remove fenced JSON blocks containing tool/function data
    text = _FENCED_TOOL_BLOCK.sub("", text)

    # Step 3: Remove generic fenced JSON blocks
    text = _FENCED_JSON_BLOCK.sub("", text)

    # Step 4: Remove standalone raw JSON objects with tool/action keys
    text = _RAW_JSON_OBJECT.sub("", text)

    # Step 5: Remove tool metadata lines
    text = _TOOL_METADATA_LINE.sub("", text)

    # Step 6: Remove bracket-wrapped tool results
    text = _BRACKET_TOOL_RESULT.sub("", text)

    # Step 7: Clean up excess whitespace
    # Collapse 3+ newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip leading/trailing whitespace
    text = text.strip()

    # Step 8: If cleaning removed everything, fall back to original
    if not text:
        logger.warning(
            "Post-processing removed all content from response; "
            "returning original (length=%d)",
            len(original),
        )
        return original.strip()

    if text != original.strip():
        logger.debug(
            "Post-processed response: removed %d chars of internal data",
            len(original) - len(text),
        )

    return text
