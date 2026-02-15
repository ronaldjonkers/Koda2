"""Strip JSON artifacts from user-facing messages.

LLM responses sometimes contain raw JSON objects, tool_call results,
or action payloads that should not be shown to the user. This module
provides a single function to clean those out.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Fields that typically hold the human-readable part of a JSON response
_HUMAN_READABLE_KEYS = (
    "message",
    "content",
    "text",
    "reply",
    "response",
    "user_message",
    "assistant_message",
    "summary",
)

# Regex: fenced JSON blocks  ```json ... ```  or  ``` ... ```
_FENCED_JSON_RE = re.compile(
    r"```(?:json)?\s*\n?\{[^`]*?\}\s*\n?```",
    re.DOTALL,
)

# Regex: bare JSON objects (greedy-safe, brace-balanced handled in code)
_BARE_JSON_RE = re.compile(
    r"(?<!\w)(\{\s*\"[^\}]{2,}\})",
    re.DOTALL,
)

# Regex: bare JSON arrays
_BARE_ARRAY_RE = re.compile(
    r"(?<!\w)(\[\s*\{[^\]]{2,}\])",
    re.DOTALL,
)


def _extract_human_field(obj: dict) -> Optional[str]:
    """Return the first human-readable string field from a dict, if any."""
    for key in _HUMAN_READABLE_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _is_json_object(text: str) -> Optional[dict]:
    """Try to parse *text* as a JSON object. Return dict or None."""
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _is_json_array(text: str) -> Optional[list]:
    """Try to parse *text* as a JSON array. Return list or None."""
    stripped = text.strip()
    if not stripped.startswith("["):
        return None
    try:
        obj = json.loads(stripped)
        if isinstance(obj, list):
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _try_parse_json(candidate: str) -> Optional[dict | list]:
    """Attempt to parse a candidate string as JSON object or array."""
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, (dict, list)):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def strip_json_from_response(text: str) -> str:
    """Remove JSON artifacts from a user-facing message.

    Handles three cases:
    1. Entire response is a JSON object → extract human-readable field.
    2. Entire response is a JSON array → return empty (no readable content).
    3. JSON blocks embedded in prose → remove them, keep the prose.

    Returns the cleaned string. If cleaning would produce an empty string,
    returns the original text unchanged (safety fallback).
    """
    if not text or not isinstance(text, str):
        return text or ""

    original = text
    stripped = text.strip()

    # --- Case 1: entire response is a single JSON object ---
    obj = _is_json_object(stripped)
    if obj is not None:
        human = _extract_human_field(obj)
        if human:
            logger.debug("strip_json: entire response was JSON; extracted human field")
            return human
        # JSON object with no recognisable human field – fall through to
        # embedded-removal so we don't just swallow the whole message.
        logger.debug("strip_json: entire response was JSON but no human field found")

    # --- Case 2: entire response is a JSON array ---
    arr = _is_json_array(stripped)
    if arr is not None:
        # Arrays are almost always tool/data payloads, not user text.
        # Nothing useful to extract; return empty → fallback below.
        logger.debug("strip_json: entire response was a JSON array")
        # Fall through – result will be empty, fallback returns original.

    # --- Case 3: embedded JSON blocks ---
    cleaned = text

    # Remove fenced code blocks containing JSON
    cleaned = _FENCED_JSON_RE.sub("", cleaned)

    # Remove bare JSON objects
    for match in reversed(list(_BARE_JSON_RE.finditer(cleaned))):
        candidate = match.group(1)
        if _try_parse_json(candidate) is not None:
            cleaned = cleaned[: match.start(1)] + cleaned[match.end(1) :]

    # Remove bare JSON arrays
    for match in reversed(list(_BARE_ARRAY_RE.finditer(cleaned))):
        candidate = match.group(1)
        if _try_parse_json(candidate) is not None:
            cleaned = cleaned[: match.start(1)] + cleaned[match.end(1) :]

    # Collapse excessive whitespace left behind
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    # Safety: never return empty if we had content
    if not cleaned:
        logger.debug("strip_json: cleaning produced empty string; returning original")
        return original

    if cleaned != original.strip():
        logger.debug("strip_json: removed embedded JSON from response")

    return cleaned
