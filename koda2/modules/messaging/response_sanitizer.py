"""Centralized response sanitizer for user-facing messages.

Strips JSON code blocks, raw JSON objects/arrays, and tool call metadata
from LLM responses so only natural language reaches the user.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Pattern: ```json ... ``` or ``` ... ``` blocks containing JSON
_JSON_CODE_BLOCK_RE = re.compile(
    r'```(?:json)?\s*\n?\{[\s\S]*?\}\s*\n?```',
    re.IGNORECASE,
)
_ARRAY_CODE_BLOCK_RE = re.compile(
    r'```(?:json)?\s*\n?\[[\s\S]*?\]\s*\n?```',
    re.IGNORECASE,
)
# Generic code blocks (``` ... ```) that may wrap any content
_GENERIC_CODE_BLOCK_RE = re.compile(
    r'```[\s\S]*?```',
)

# Standalone JSON objects: lines starting with { and ending with }
# spanning potentially multiple lines. We use a conservative approach:
# match a { at line start, capture until a matching } at line start/end.
_STANDALONE_JSON_OBJ_RE = re.compile(
    r'^\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}\s*$',
    re.MULTILINE,
)
# Standalone JSON arrays
_STANDALONE_JSON_ARR_RE = re.compile(
    r'^\s*\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]\s*$',
    re.MULTILINE,
)

# Tool call metadata patterns
_TOOL_CALL_PATTERNS = [
    # Function call notation: function_name({...})
    re.compile(r'\b\w+\(\s*\{[\s\S]*?\}\s*\)', re.MULTILINE),
    # "tool_calls": [...] or "function_call": {...}
    re.compile(r'["\']?tool_calls?["\']?\s*:\s*\[', re.IGNORECASE),
    re.compile(r'["\']?function_call["\']?\s*:\s*\{', re.IGNORECASE),
    # <tool_call>...</tool_call> XML-style tags
    re.compile(r'</?tool_call[^>]*>', re.IGNORECASE),
    # <function=name>{...}</function>
    re.compile(r'<function=[^>]+>\s*\{[\s\S]*?\}\s*</function>', re.IGNORECASE),
]

# Lines that look like key-value debug output: "key": "value"
_KEY_VALUE_LINE_RE = re.compile(
    r'^\s*["\']\w+["\']\s*:\s*["\'].*["\']\s*,?\s*$',
    re.MULTILINE,
)


def sanitize_response(text: str) -> str:
    """Remove JSON artifacts and tool metadata from a user-facing response.

    Args:
        text: The raw LLM response text.

    Returns:
        Cleaned text containing only natural language content.
    """
    if not text or not isinstance(text, str):
        return text or ""

    original = text

    # 1. Remove JSON code blocks (```json ... ``` and ``` ... ```)
    text = _JSON_CODE_BLOCK_RE.sub('', text)
    text = _ARRAY_CODE_BLOCK_RE.sub('', text)

    # 2. Remove remaining generic code blocks that contain JSON-like content
    def _remove_json_code_blocks(match: re.Match) -> str:
        content = match.group(0)
        # Only remove if the block contains JSON-like content
        if re.search(r'[{\[]', content):
            return ''
        return content  # Keep non-JSON code blocks (e.g., code examples)

    text = _GENERIC_CODE_BLOCK_RE.sub(_remove_json_code_blocks, text)

    # 3. Remove tool call XML tags and function call patterns
    for pattern in _TOOL_CALL_PATTERNS:
        text = pattern.sub('', text)

    # 4. Remove standalone JSON objects/arrays (multi-line)
    #    We do this carefully to avoid removing normal text
    text = _remove_standalone_json(text)

    # 5. Clean up resulting whitespace
    text = _clean_whitespace(text)

    if text != original:
        removed_len = len(original) - len(text)
        logger.debug(
            "Response sanitizer removed %d chars of JSON/tool metadata",
            removed_len,
        )

    return text


def _remove_standalone_json(text: str) -> str:
    """Remove standalone JSON objects/arrays that span multiple lines."""
    lines = text.split('\n')
    result_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detect start of a JSON object
        if stripped.startswith('{') and not stripped.startswith('{%'):
            json_block, end_idx = _extract_json_block(lines, i, '{', '}')
            if json_block is not None:
                # Skip these lines
                i = end_idx + 1
                continue

        # Detect start of a JSON array
        if stripped.startswith('['):
            json_block, end_idx = _extract_json_block(lines, i, '[', ']')
            if json_block is not None:
                i = end_idx + 1
                continue

        result_lines.append(line)
        i += 1

    return '\n'.join(result_lines)


def _extract_json_block(
    lines: list, start: int, open_char: str, close_char: str
) -> tuple:
    """Try to extract a balanced JSON block starting at the given line.

    Returns (block_text, end_index) if found, (None, start) otherwise.
    """
    depth = 0
    block_lines = []

    for i in range(start, min(start + 50, len(lines))):  # Cap at 50 lines
        line = lines[i]
        block_lines.append(line)

        for ch in line:
            if ch == open_char:
                depth += 1
            elif ch == close_char:
                depth -= 1

        if depth == 0 and block_lines:
            # Verify it looks like JSON (has quotes/colons or brackets)
            block_text = '\n'.join(block_lines)
            if _looks_like_json(block_text):
                return block_text, i
            else:
                return None, start

    return None, start


def _looks_like_json(text: str) -> bool:
    """Heuristic check: does this text look like a JSON structure?"""
    stripped = text.strip()
    # Must start and end with matching brackets
    if not ((stripped.startswith('{') and stripped.endswith('}')) or
            (stripped.startswith('[') and stripped.endswith(']'))):
        return False

    # Should contain typical JSON markers
    json_indicators = ['":', '": ', '",', '",', 'null', 'true', 'false']
    indicator_count = sum(1 for ind in json_indicators if ind in stripped)

    # At least 2 JSON indicators, or it's a short single-key object
    return indicator_count >= 2 or (len(stripped) < 100 and ':' in stripped)


def _clean_whitespace(text: str) -> str:
    """Clean up excessive whitespace left after removals."""
    # Replace 3+ consecutive newlines with 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove leading/trailing whitespace
    text = text.strip()
    return text
