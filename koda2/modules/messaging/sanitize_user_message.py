"""Sanitize AI responses before sending to users.

This is the single authoritative post-processing step for all user-facing
messages. It removes raw JSON, tool call artifacts, function results,
and other internal metadata that should never reach the end user.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns that indicate internal/tool content leaked into the response
_JSON_CODE_BLOCK_RE = re.compile(r"```(?:json)?\s*\n?\{[\s\S]*?\}\s*\n?```", re.IGNORECASE)
_BARE_JSON_OBJECT_RE = re.compile(r'(?:^|\n)(\{\s*"(?:tool_call|function|name|arguments|role|content|tool_call_id|type|id|result|action|status|error)["\s:])[\s\S]*?\}', re.MULTILINE)
_TOOL_CALL_BLOCK_RE = re.compile(r'</?(?:tool_call|function_call|tool_result|function_result)[^>]*>[\s\S]*?(?:</(?:tool_call|function_call|tool_result|function_result)>|$)', re.IGNORECASE)
_FUNCTION_HEADER_RE = re.compile(r'^\s*(?:Function|Tool)\s*(?:call|result|output|response)\s*[:=]\s*', re.IGNORECASE | re.MULTILINE)
_ROLE_LINE_RE = re.compile(r'^\s*(?:assistant|system|user|tool|function)\s*:\s*$', re.IGNORECASE | re.MULTILINE)
_TRIPLE_BACKTICK_JSON_RE = re.compile(r'```[\s\S]*?```')


def sanitize_user_message(response: Optional[str]) -> str:
    """Remove JSON artifacts and internal metadata from a user-facing message.

    Args:
        response: Raw AI response string.

    Returns:
        Cleaned string safe for sending to the user. Returns a fallback
        message if the response is empty or entirely stripped.
    """
    if not response:
        return ""

    original = response
    text = response

    try:
        # 1. Remove XML-style tool call / function result tags
        text = _TOOL_CALL_BLOCK_RE.sub('', text)

        # 2. Remove ```json ... ``` code blocks
        text = _JSON_CODE_BLOCK_RE.sub('', text)

        # 3. Remove remaining triple-backtick blocks that look like JSON
        def _strip_json_backtick_blocks(m: re.Match) -> str:
            inner = m.group(0)
            # Keep non-JSON code blocks (e.g. code examples the user asked for)
            stripped = inner.strip('` \n')
            if stripped.lstrip().startswith('{') or stripped.lstrip().startswith('['):
                return ''
            return inner

        text = _TRIPLE_BACKTICK_JSON_RE.sub(_strip_json_backtick_blocks, text)

        # 4. Remove bare JSON objects that look like tool calls / function results
        text = _BARE_JSON_OBJECT_RE.sub('', text)

        # 5. Remove "Function call:" / "Tool result:" header lines
        text = _FUNCTION_HEADER_RE.sub('', text)

        # 6. Remove bare role lines ("assistant:", "tool:", etc.)
        text = _ROLE_LINE_RE.sub('', text)

        # 7. Try to detect if the entire response is a JSON blob and extract
        #    a natural language portion from it
        stripped = text.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            text = _extract_natural_language_from_json(stripped)

        # 8. Clean up excessive whitespace left by removals
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        if not text:
            logger.warning(
                "sanitize_user_message: entire response was stripped. "
                "Original length=%d", len(original)
            )
            # Return empty string — callers should handle this
            return ""

        if text != original:
            logger.info(
                "sanitize_user_message: cleaned response (removed %d chars)",
                len(original) - len(text)
            )

        return text

    except Exception as e:
        logger.error("sanitize_user_message failed: %s", e, exc_info=True)
        # On error, return the original rather than losing the message
        return original


def _extract_natural_language_from_json(text: str) -> str:
    """If text is a JSON object, try to pull out a human-readable field."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text

    if not isinstance(data, dict):
        return text

    # Common keys that hold the user-facing message
    for key in ('message', 'response', 'text', 'content', 'reply', 'answer', 'summary'):
        if key in data and isinstance(data[key], str) and data[key].strip():
            return data[key].strip()

    # If there's a nested 'result' dict with a message
    if 'result' in data and isinstance(data['result'], dict):
        for key in ('message', 'response', 'text', 'content', 'summary'):
            if key in data['result'] and isinstance(data['result'][key], str):
                return data['result'][key].strip()

    return text
