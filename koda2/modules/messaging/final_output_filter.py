"""Final output filter - last line of defense before messages reach the user.

Applied at the send boundary (WhatsApp send, WebSocket emit, etc.)
to ensure no tool-call JSON, raw function results, or structured
data leaks into user-facing messages.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns that indicate tool-call / function-call content
_TOOL_CALL_INDICATORS = [
    '"tool_calls"',
    '"function_call"',
    '"name":', '"arguments":',
    '"tool_call_id"',
    '"role": "tool"',
    '"role": "function"',
    '"type": "function"',
]

# Regex: fenced JSON/code blocks
_FENCED_JSON_RE = re.compile(
    r'```(?:json|tool_call|function_call|tool|python)?\s*\n?'
    r'(\{[\s\S]*?\})\s*\n?'
    r'```',
    re.IGNORECASE,
)

# Regex: fenced blocks with arrays
_FENCED_ARRAY_RE = re.compile(
    r'```(?:json|tool_call|function_call|tool|python)?\s*\n?'
    r'(\[[\s\S]*?\])\s*\n?'
    r'```',
    re.IGNORECASE,
)

# Regex: standalone JSON object that looks like a tool call
_STANDALONE_TOOL_JSON_RE = re.compile(
    r'(?:^|\n)\s*(\{\s*"(?:tool_calls?|function_call|name|id|type)"[\s\S]*?\})\s*(?:\n|$)',
    re.MULTILINE,
)

# Regex: entire message is a JSON object
_FULL_JSON_RE = re.compile(r'^\s*\{[\s\S]*\}\s*$')

# Regex: entire message is a JSON array
_FULL_ARRAY_RE = re.compile(r'^\s*\[[\s\S]*\]\s*$')


def _is_tool_call_json(text: str) -> bool:
    """Check if a JSON string looks like a tool/function call."""
    indicator_count = sum(1 for ind in _TOOL_CALL_INDICATORS if ind in text)
    return indicator_count >= 2


def _try_extract_text_from_json(text: str) -> Optional[str]:
    """If the text is a JSON object with a 'content' or 'text' field, extract it."""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            # OpenAI-style message object
            if 'content' in data and isinstance(data.get('content'), str):
                return data['content'].strip() or None
            if 'text' in data and isinstance(data.get('text'), str):
                return data['text'].strip() or None
            # choices[0].message.content pattern
            if 'choices' in data and isinstance(data['choices'], list):
                for choice in data['choices']:
                    msg = choice.get('message', {}) or choice.get('delta', {})
                    if isinstance(msg, dict) and msg.get('content'):
                        return msg['content'].strip()
    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        pass
    return None


def filter_for_user(text: Optional[str], fallback: str = "") -> str:
    """Filter an LLM response so only human-readable text reaches the user.

    Args:
        text: The raw response text from the LLM / agent pipeline.
        fallback: Message to return if the response is entirely non-user-facing
                  (e.g. a pure tool call). Empty string means "don't send".

    Returns:
        Cleaned text safe for the user, or *fallback* if nothing remains.
    """
    if not text or not text.strip():
        return fallback

    original = text
    cleaned = text

    # 1) Remove fenced JSON blocks that look like tool calls
    for pattern in (_FENCED_JSON_RE, _FENCED_ARRAY_RE):
        for match in pattern.finditer(cleaned):
            inner = match.group(1)
            if _is_tool_call_json(inner):
                cleaned = cleaned.replace(match.group(0), '')
                logger.debug("Stripped fenced tool-call JSON block from user message")

    # 2) Remove standalone tool-call JSON objects
    for match in _STANDALONE_TOOL_JSON_RE.finditer(cleaned):
        inner = match.group(1)
        if _is_tool_call_json(inner):
            cleaned = cleaned.replace(match.group(0), '')
            logger.debug("Stripped standalone tool-call JSON from user message")

    # 3) If the entire remaining message is a JSON object, check if it's a tool call
    stripped = cleaned.strip()
    if stripped and (_FULL_JSON_RE.match(stripped) or _FULL_ARRAY_RE.match(stripped)):
        if _is_tool_call_json(stripped):
            # Try to extract readable content from it
            extracted = _try_extract_text_from_json(stripped)
            if extracted:
                logger.debug("Extracted text content from JSON response object")
                return extracted
            logger.info("Entire response was tool-call JSON; suppressing")
            return fallback

    # 4) Clean up leftover whitespace from removals
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()

    if not cleaned:
        # Everything was stripped - it was a pure tool call
        logger.info("Response contained only tool-call data; returning fallback")
        return fallback

    if cleaned != original:
        logger.info(
            "Filtered tool-call data from user message (removed %d chars)",
            len(original) - len(cleaned),
        )

    return cleaned
