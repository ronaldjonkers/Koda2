"""Filter LLM responses to extract only user-facing natural language text.

Strips JSON blocks, tool call metadata, function call results, and other
structured data that should not be shown to end users.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns for content that should be stripped from user-facing messages
_PATTERNS = [
    # Fenced JSON code blocks: ```json ... ```
    re.compile(r'```json\s*\n?.*?\n?```', re.DOTALL | re.IGNORECASE),
    # Fenced code blocks with other lang hints that contain JSON-like content
    re.compile(r'```(?:tool_call|function_call|tool_result|action|result)\s*\n?.*?\n?```', re.DOTALL | re.IGNORECASE),
    # XML-style tool blocks: <tool_call>...</tool_call>, <function_call>...</function_call>
    re.compile(r'<(?:tool_call|function_call|tool_result|action_result)[^>]*>.*?</(?:tool_call|function_call|tool_result|action_result)>', re.DOTALL | re.IGNORECASE),
    # Standalone JSON objects on their own "paragraph" (preceded/followed by blank lines or start/end)
    # Match { ... } blocks that look like JSON (contain quoted keys)
    re.compile(r'(?:^|\n\n)\{\s*"[^"]+"\s*:.*?\}(?:\n\n|$)', re.DOTALL),
    # Standalone JSON arrays that look like tool results
    re.compile(r'(?:^|\n\n)\[\s*\{\s*"[^"]+"\s*:.*?\}\s*\](?:\n\n|$)', re.DOTALL),
    # Tool use markers from various LLM providers
    re.compile(r'<\|tool_call\|>.*?<\|/tool_call\|>', re.DOTALL),
    re.compile(r'<\|function\|>.*?<\|/function\|>', re.DOTALL),
    # Lines that are purely "Action:", "Action Input:", "Observation:" style chain-of-thought
    re.compile(r'^(?:Action|Action Input|Observation|Tool Call|Function Call|TOOL_CALL|FUNCTION_CALL)\s*:.*$', re.MULTILINE),
]

# Pattern to detect if a string is essentially just a JSON object/array
_PURE_JSON_PATTERN = re.compile(r'^\s*[{\[].*[}\]]\s*$', re.DOTALL)

# Phrases that indicate tool/function metadata lines
_METADATA_LINE_PREFIXES = (
    'tool_call_id:', 'function_name:', 'tool_name:', 'call_id:',
    '"tool_call_id"', '"function_name"', '"tool_name"',
    'tool_calls:', 'function_calls:',
)


def filter_for_user(text: Optional[str]) -> str:
    """Remove all non-user-facing content from an LLM response.

    Args:
        text: Raw LLM response text that may contain JSON blocks,
              tool call metadata, or other structured data.

    Returns:
        Cleaned text containing only natural language meant for the user.
        Returns empty string if input is None or entirely structured data.
    """
    if not text:
        return ""

    original = text
    cleaned = text

    # Step 1: Remove all regex-matched patterns
    for pattern in _PATTERNS:
        cleaned = pattern.sub('', cleaned)

    # Step 2: Remove lines that are purely metadata
    lines = cleaned.split('\n')
    filtered_lines = []
    for line in lines:
        stripped = line.strip().lower()
        if any(stripped.startswith(prefix.lower()) for prefix in _METADATA_LINE_PREFIXES):
            continue
        filtered_lines.append(line)
    cleaned = '\n'.join(filtered_lines)

    # Step 3: Check if what remains is still just a JSON blob
    # (handles cases where JSON wasn't in a fenced block)
    cleaned_stripped = cleaned.strip()
    if cleaned_stripped and _PURE_JSON_PATTERN.match(cleaned_stripped):
        try:
            parsed = json.loads(cleaned_stripped)
            # If it parses as JSON and looks like tool/function data, strip it
            if isinstance(parsed, dict):
                suspicious_keys = {'tool_call', 'function_call', 'tool_calls',
                                   'function_calls', 'action', 'action_input',
                                   'tool_call_id', 'name', 'arguments',
                                   'tool_name', 'function_name', 'type'}
                if suspicious_keys & set(parsed.keys()):
                    logger.debug("Stripped pure JSON tool/function block from response")
                    cleaned = ""
                elif 'result' in parsed and len(parsed) <= 3:
                    # Likely a tool result like {"result": ..., "status": "success"}
                    cleaned = ""
            elif isinstance(parsed, list) and all(isinstance(i, dict) for i in parsed):
                # Array of objects - likely structured data, not user text
                cleaned = ""
        except (json.JSONDecodeError, ValueError):
            pass  # Not valid JSON, keep it

    # Step 4: Clean up excessive whitespace left by removals
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()

    # Step 5: If we stripped everything, that's suspicious - log it
    if original.strip() and not cleaned:
        logger.warning(
            "User-facing filter stripped entire response (len=%d). "
            "Original started with: %s",
            len(original),
            original[:100]
        )

    return cleaned


def is_user_safe(text: str) -> bool:
    """Check if text is safe to send to user as-is (no structured data).

    Quick check without modifying the text. Useful for assertions/logging.
    """
    if not text:
        return True
    filtered = filter_for_user(text)
    return filtered == text.strip()
