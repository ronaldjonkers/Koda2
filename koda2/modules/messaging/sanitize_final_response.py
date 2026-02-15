"""Final response sanitizer - strips raw JSON from user-facing messages.

This module provides the definitive sanitization applied right before
a message is sent to the user (WhatsApp or dashboard). It catches any
JSON objects/arrays that leaked through the LLM response.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Pattern to match JSON-like blocks: {...} or [...] spanning multiple chars
# We use a non-greedy approach and validate with json.loads
_JSON_BLOCK_PATTERN = re.compile(
    r'```(?:json)?\s*([\s\S]*?)```',  # fenced code blocks first
    re.IGNORECASE,
)

_BARE_JSON_PATTERN = re.compile(
    r'(\{[\s\S]{10,}?\}|\[[\s\S]{10,}?\])',  # bare JSON objects/arrays (min 10 chars)
)


def _is_valid_json(text: str) -> bool:
    """Check if a string is valid JSON (object or array)."""
    text = text.strip()
    if not text:
        return False
    try:
        result = json.loads(text)
        return isinstance(result, (dict, list))
    except (json.JSONDecodeError, ValueError):
        return False


def _describe_json_briefly(data) -> str:
    """Create a brief natural-language hint about removed JSON."""
    if isinstance(data, dict):
        keys = list(data.keys())[:5]
        if keys:
            return f"(details: {', '.join(str(k) for k in keys)})"
    elif isinstance(data, list):
        return f"({len(data)} items)"
    return ""


def sanitize_final_response(text: Optional[str]) -> str:
    """Remove raw JSON from a user-facing message.

    This is the last line of defense before a message reaches the user.
    It strips fenced code blocks containing JSON and bare JSON objects/arrays.

    Args:
        text: The response text to sanitize.

    Returns:
        Cleaned text with JSON removed. If the entire message was JSON,
        returns a fallback message.
    """
    if not text or not isinstance(text, str):
        return text or ""

    original = text
    cleaned = text

    # 1. Remove fenced code blocks containing JSON
    def _replace_fenced(match):
        content = match.group(1).strip()
        if _is_valid_json(content):
            logger.warning(
                "Stripped fenced JSON block from user-facing message: %s...",
                content[:100],
            )
            return ""
        return match.group(0)

    cleaned = _JSON_BLOCK_PATTERN.sub(_replace_fenced, cleaned)

    # 2. Remove bare JSON objects/arrays
    def _replace_bare(match):
        candidate = match.group(1).strip()
        if _is_valid_json(candidate):
            logger.warning(
                "Stripped bare JSON from user-facing message: %s...",
                candidate[:100],
            )
            return ""
        return match.group(0)

    cleaned = _BARE_JSON_PATTERN.sub(_replace_bare, cleaned)

    # 3. Clean up extra whitespace left behind
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()

    # 4. If we stripped everything, provide a fallback
    if not cleaned and original.strip():
        logger.error(
            "Entire user-facing message was JSON — replaced with fallback. Original: %s...",
            original[:200],
        )
        cleaned = "Done! Let me know if you need any details."

    if cleaned != original:
        logger.info("Final response sanitizer modified the outgoing message.")

    return cleaned
