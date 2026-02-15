"""Sanitize LLM responses to ensure only natural language reaches the user.

Strips tool_call metadata, JSON code blocks, function call artifacts,
and raw serialized response objects from AI output before sending
to WhatsApp or dashboard channels.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns that indicate tool/function call metadata leaked into response
_TOOL_CALL_PATTERNS = [
    # OpenAI tool_calls serialized JSON
    re.compile(r'\{\s*"id"\s*:\s*"call_[^"]+"\s*,\s*"type"\s*:\s*"function"', re.DOTALL),
    # Function call blocks: {"name": "...", "arguments": ...}
    re.compile(r'\{\s*"name"\s*:\s*"[\w.]+"\s*,\s*"arguments"\s*:', re.DOTALL),
    # tool_calls array wrapper
    re.compile(r'"tool_calls"\s*:\s*\[', re.DOTALL),
    # function_call object
    re.compile(r'"function_call"\s*:\s*\{', re.DOTALL),
    # ChatCompletionMessage(...) repr strings
    re.compile(r'ChatCompletionMessage\(', re.DOTALL),
    # role/content/tool_calls object pattern
    re.compile(r'\{\s*"role"\s*:\s*"assistant"\s*,\s*"content"', re.DOTALL),
]

# Regex to match ```json ... ``` or ``` ... ``` code blocks
_JSON_CODE_BLOCK_RE = re.compile(
    r'```(?:json)?\s*\n?(.+?)\n?\s*```',
    re.DOTALL,
)

# Regex to match standalone JSON objects/arrays that span multiple lines
_STANDALONE_JSON_RE = re.compile(
    r'^\s*(\{[\s\S]{20,}\})\s*$|^\s*(\[[\s\S]{20,}\])\s*$',
    re.MULTILINE,
)

# Regex for lines that look like key-value metadata (e.g., "finish_reason": "tool_calls")
_METADATA_LINE_RE = re.compile(
    r'^\s*"?(finish_reason|tool_calls|function_call|refusal|logprobs|id|type|function)"?\s*[:=]',
    re.MULTILINE,
)


def sanitize_response(text: Optional[str]) -> str:
    """Clean an LLM response so only natural language is returned.

    Args:
        text: Raw response text that may contain tool metadata.

    Returns:
        Cleaned string safe for user-facing display.
        Returns empty string if input is None or entirely metadata.
    """
    if not text:
        return ""

    original = text

    # 1. If the entire text is a serialized JSON object (e.g., the full
    #    ChatCompletion response was accidentally stringified), try to
    #    extract just the content field.
    text = _extract_content_from_serialized(text)

    # 2. Remove JSON code blocks (```json ... ```)
    text = _strip_json_code_blocks(text)

    # 3. Remove any remaining tool_call / function_call JSON blobs
    text = _strip_tool_call_json(text)

    # 4. Remove metadata lines that look like key: value pairs from API objects
    text = _strip_metadata_lines(text)

    # 5. Clean up whitespace
    text = _clean_whitespace(text)

    if text != original:
        logger.debug(
            "Sanitized LLM response: removed %d chars of metadata",
            len(original) - len(text),
        )

    return text


def _extract_content_from_serialized(text: str) -> str:
    """If text is a serialized ChatCompletion or message object, extract content."""
    stripped = text.strip()

    # Quick check: does it look like JSON?
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return text

    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return text

    # Handle full ChatCompletion response object
    if isinstance(obj, dict):
        # Direct message object: {"role": "assistant", "content": "..."}
        if "content" in obj and "role" in obj:
            content = obj.get("content")
            if content and isinstance(content, str):
                logger.warning("Response was a serialized message object; extracted content field")
                return content
            return ""

        # Full ChatCompletion: {"choices": [{"message": {"content": "..."}}]}
        choices = obj.get("choices", [])
        if choices and isinstance(choices, list):
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = message.get("content")
            if content and isinstance(content, str):
                logger.warning("Response was a serialized ChatCompletion; extracted content field")
                return content
            return ""

    return text


def _strip_json_code_blocks(text: str) -> str:
    """Remove ```json ... ``` code blocks.

    If the code block contains what looks like tool/function JSON, remove it
    entirely. If it looks like user-relevant data, leave the inner text.
    """
    def _replace_block(match: re.Match) -> str:
        inner = match.group(1).strip()
        # Check if inner content is tool/function metadata
        for pattern in _TOOL_CALL_PATTERNS:
            if pattern.search(inner):
                return ""  # Remove entirely
        # Check if it's a pure JSON object (not user-facing)
        try:
            parsed = json.loads(inner)
            if isinstance(parsed, (dict, list)):
                # Heuristic: if it has keys like 'name', 'arguments', 'tool_calls',
                # 'function', 'id' — it's metadata
                if isinstance(parsed, dict):
                    metadata_keys = {"name", "arguments", "tool_calls", "function", "function_call", "id", "type", "role"}
                    if metadata_keys & set(parsed.keys()):
                        return ""
                return ""  # Remove raw JSON objects from user output
        except (json.JSONDecodeError, ValueError):
            pass
        # Not JSON — might be a code example the AI is sharing; leave it
        return match.group(0)

    return _JSON_CODE_BLOCK_RE.sub(_replace_block, text)


def _strip_tool_call_json(text: str) -> str:
    """Remove inline tool_call / function_call JSON objects from text."""
    for pattern in _TOOL_CALL_PATTERNS:
        match = pattern.search(text)
        if match:
            # Try to find the full JSON object starting at match
            start = match.start()
            json_str = _extract_json_object(text, start)
            if json_str:
                text = text[:start] + text[start + len(json_str):]
    return text


def _extract_json_object(text: str, start: int) -> Optional[str]:
    """Extract a complete JSON object/array starting at position `start`."""
    if start >= len(text):
        return None

    char = text[start]
    if char not in ("{", "["):
        # Scan backwards to find the opening brace
        idx = text.rfind("{", max(0, start - 5), start + 1)
        if idx == -1:
            return None
        start = idx
        char = "{"

    open_char = char
    close_char = "}" if char == "{" else "]"
    depth = 0
    in_string = False
    escape = False

    for i in range(start, min(start + 5000, len(text))):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _strip_metadata_lines(text: str) -> str:
    """Remove lines that look like raw API metadata key-value pairs."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        if _METADATA_LINE_RE.match(line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


def _clean_whitespace(text: str) -> str:
    """Collapse excessive whitespace left after stripping."""
    # Collapse 3+ newlines into 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Strip leading/trailing whitespace
    text = text.strip()
    return text
