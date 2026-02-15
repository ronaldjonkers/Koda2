"""Response cleaner - strips raw JSON from AI responses before sending to users."""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Fields to look for when extracting a message from a JSON object
MESSAGE_FIELDS = ['message', 'content', 'text', 'response', 'reply', 'answer', 'summary', 'result']

# Pattern for ```json ... ``` code blocks (with optional language tag)
JSON_CODE_BLOCK_PATTERN = re.compile(
    r'```(?:json)?\s*\n?(\{[\s\S]*?\}|\[[\s\S]*?\])\s*\n?```',
    re.IGNORECASE
)

# Pattern for standalone JSON objects/arrays (must start at line beginning or after whitespace)
STANDALONE_JSON_PATTERN = re.compile(
    r'(?:^|\n)\s*(\{["\s][\s\S]*?\}|\[["\s][\s\S]*?\])\s*(?:\n|$)',
)


def _try_parse_json(text: str) -> Optional[dict | list]:
    """Attempt to parse text as JSON. Returns parsed object or None."""
    text = text.strip()
    if not text:
        return None
    if not (text.startswith('{') or text.startswith('[')):
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_message_from_json(data: dict | list) -> Optional[str]:
    """Extract a human-readable message from a JSON object by checking known fields."""
    if isinstance(data, list):
        # For arrays, try to summarize or return None
        return None

    if isinstance(data, dict):
        # Check top-level message fields
        for field in MESSAGE_FIELDS:
            if field in data and isinstance(data[field], str) and data[field].strip():
                return data[field].strip()

        # Check nested structures (e.g., {"data": {"message": "..."}})
        for key, value in data.items():
            if isinstance(value, dict):
                for field in MESSAGE_FIELDS:
                    if field in value and isinstance(value[field], str) and value[field].strip():
                        return value[field].strip()

    return None


def _is_entirely_json(text: str) -> bool:
    """Check if the entire text (after stripping whitespace) is a single JSON object/array."""
    stripped = text.strip()
    return _try_parse_json(stripped) is not None


def _remove_json_code_blocks(text: str) -> str:
    """Remove ```json ... ``` code blocks from text."""
    return JSON_CODE_BLOCK_PATTERN.sub('', text)


def _remove_standalone_json(text: str) -> str:
    """Remove standalone JSON objects/arrays from text.
    
    Only removes JSON that appears to be a complete object/array on its own lines,
    not JSON-like text embedded in natural language sentences.
    """
    result = text
    for match in STANDALONE_JSON_PATTERN.finditer(text):
        candidate = match.group(1)
        if _try_parse_json(candidate) is not None:
            result = result.replace(match.group(0), '\n')
    return result


def clean_response(response: str) -> str:
    """Clean an AI response by stripping JSON and keeping natural language.
    
    Processing steps:
    1. If the entire response is JSON, extract message/content/text field
    2. Remove ```json``` code blocks
    3. Remove standalone JSON objects/arrays
    4. Clean up extra whitespace
    
    Args:
        response: Raw AI response text
        
    Returns:
        Cleaned response suitable for sending to users
    """
    if not response or not response.strip():
        return response

    original = response
    stripped = response.strip()

    # Step 1: Check if the entire response is JSON
    parsed = _try_parse_json(stripped)
    if parsed is not None:
        extracted = _extract_message_from_json(parsed)
        if extracted:
            logger.info("Extracted natural language from JSON response")
            return extracted
        else:
            # Entire response is JSON but no message field found.
            # This is unusual - log it and return original to avoid losing data.
            logger.warning(
                "Entire response is JSON but no message field found. "
                "Returning original. Keys: %s",
                list(parsed.keys()) if isinstance(parsed, dict) else f"array[{len(parsed)}]"
            )
            return response

    # Step 2: Check if it's a JSON code block wrapping the whole response
    # e.g., ```json\n{"message": "Hello"}\n```
    code_block_match = re.match(
        r'^\s*```(?:json)?\s*\n?([\s\S]+?)\s*\n?```\s*$',
        stripped,
        re.IGNORECASE
    )
    if code_block_match:
        inner = code_block_match.group(1).strip()
        inner_parsed = _try_parse_json(inner)
        if inner_parsed is not None:
            extracted = _extract_message_from_json(inner_parsed)
            if extracted:
                logger.info("Extracted natural language from JSON code block response")
                return extracted

    # Step 3: Remove JSON code blocks from mixed content
    cleaned = _remove_json_code_blocks(stripped)

    # Step 4: Remove standalone JSON objects from mixed content
    cleaned = _remove_standalone_json(cleaned)

    # Step 5: Clean up whitespace
    # Collapse multiple blank lines into one
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()

    # If cleaning removed everything, return original
    if not cleaned:
        logger.warning("JSON cleaning removed all content, returning original response")
        return response

    if cleaned != stripped:
        logger.info(
            "Cleaned JSON from response (original: %d chars, cleaned: %d chars)",
            len(stripped), len(cleaned)
        )

    return cleaned
