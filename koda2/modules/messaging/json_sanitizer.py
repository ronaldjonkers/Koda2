"""Sanitize LLM responses by removing raw JSON and structured data.

This module provides a robust post-processing step that ensures only
natural language text is sent to users. It handles:
- Fenced JSON code blocks (```json ... ```)
- Bare JSON objects/arrays in the response
- Tool call result artifacts
- Function call metadata
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Pattern: fenced code blocks with json/JSON label
_FENCED_JSON_BLOCK = re.compile(
    r"```(?:json|JSON)\s*\n?.*?```",
    re.DOTALL,
)

# Pattern: any fenced code block (``` ... ```)
_FENCED_CODE_BLOCK = re.compile(
    r"```\w*\s*\n?\{.*?\}\s*```",
    re.DOTALL,
)

# Pattern: standalone JSON objects on their own line(s)
# Matches { ... } blocks that look like JSON (contain quoted keys)
_STANDALONE_JSON_OBJECT = re.compile(
    r"^\s*\{\s*\"[^\}]{10,}\}\s*$",
    re.MULTILINE | re.DOTALL,
)

# Pattern: tool_call / function_call result blocks
_TOOL_RESULT_BLOCK = re.compile(
    r"(?:Tool (?:call |result|output)[:\s]*|Function (?:call |result|output)[:\s]*)"
    r"[`]*\{.*?\}[`]*",
    re.DOTALL | re.IGNORECASE,
)

# Pattern: lines that are purely key-value JSON-like ("key": "value")
_JSON_KV_LINE = re.compile(
    r'^\s*"[^"]+"\s*:\s*(?:"[^"]*"|\d+|true|false|null|\[.*?\]|\{.*?\})\s*,?\s*$',
    re.MULTILINE,
)


def strip_json_from_response(text: str) -> str:
    """Remove raw JSON blocks and structured data from a response string.

    Args:
        text: The raw LLM response text.

    Returns:
        Cleaned text with only natural language content.
    """
    if not text or not text.strip():
        return text

    original = text

    # Step 1: Remove fenced JSON code blocks (```json ... ```)
    text = _FENCED_JSON_BLOCK.sub("", text)

    # Step 2: Remove fenced code blocks containing JSON objects
    text = _FENCED_CODE_BLOCK.sub("", text)

    # Step 3: Remove tool/function result blocks
    text = _TOOL_RESULT_BLOCK.sub("", text)

    # Step 4: Remove standalone JSON objects (multi-line { ... } blocks)
    text = _remove_standalone_json_objects(text)

    # Step 5: Remove orphaned JSON array blocks
    text = _remove_standalone_json_arrays(text)

    # Step 6: Clean up residual artifacts
    text = _clean_residual_artifacts(text)

    # Step 7: Collapse excessive whitespace left behind
    text = _collapse_whitespace(text)

    if text.strip() != original.strip():
        logger.info(
            "JSON sanitizer removed structured data from response "
            "(original length=%d, cleaned length=%d)",
            len(original),
            len(text),
        )

    # Safety: if stripping removed ALL content, return a fallback
    if not text.strip():
        logger.warning(
            "JSON sanitizer stripped entire response; "
            "returning generic acknowledgment"
        )
        return "Done."

    return text.strip()


def _remove_standalone_json_objects(text: str) -> str:
    """Remove multi-line JSON objects that appear standalone in text."""
    lines = text.split("\n")
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Detect start of a JSON object
        if stripped.startswith("{") and _looks_like_json_start(stripped):
            # Collect lines until we find the closing brace
            json_block = [line]
            brace_count = stripped.count("{") - stripped.count("}")
            j = i + 1
            while j < len(lines) and brace_count > 0:
                json_block.append(lines[j])
                brace_count += lines[j].count("{") - lines[j].count("}")
                j += 1

            block_text = "\n".join(json_block).strip()
            if _is_valid_json(block_text):
                # Skip this block entirely
                i = j
                continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines)


def _remove_standalone_json_arrays(text: str) -> str:
    """Remove multi-line JSON arrays that appear standalone in text."""
    lines = text.split("\n")
    result_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("[") and len(stripped) > 2:
            json_block = [line]
            bracket_count = stripped.count("[") - stripped.count("]")
            j = i + 1
            while j < len(lines) and bracket_count > 0:
                json_block.append(lines[j])
                bracket_count += lines[j].count("[") - lines[j].count("]")
                j += 1

            block_text = "\n".join(json_block).strip()
            if _is_valid_json(block_text):
                i = j
                continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines)


def _looks_like_json_start(line: str) -> bool:
    """Heuristic: does this line look like the start of a JSON object?"""
    # Must start with { and contain a quoted key
    return bool(re.match(r'\s*\{\s*"', line))


def _is_valid_json(text: str) -> bool:
    """Check if text is valid JSON."""
    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _clean_residual_artifacts(text: str) -> str:
    """Remove residual artifacts like 'Here is the JSON:' prefixes."""
    # Remove lines like "Here is the JSON response:", "JSON output:", etc.
    text = re.sub(
        r"^.*(?:here is|here's|below is|the)\s+(?:the\s+)?(?:JSON|json|structured|raw)\s*"
        r"(?:response|output|result|data|object|block)?\s*:?\s*$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    return text


def _collapse_whitespace(text: str) -> str:
    """Collapse multiple blank lines into at most two."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def contains_json(text: str) -> bool:
    """Check if text contains JSON blocks (for diagnostics/logging)."""
    if not text:
        return False
    if _FENCED_JSON_BLOCK.search(text):
        return True
    if _FENCED_CODE_BLOCK.search(text):
        return True
    if _TOOL_RESULT_BLOCK.search(text):
        return True
    # Check for standalone JSON objects
    for line in text.split("\n"):
        if _looks_like_json_start(line.strip()):
            return True
    return False
