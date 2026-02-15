"""Response pipeline post-processor.

Strips JSON blocks, markdown code fences containing JSON, tool-call results,
and other structured data from assistant replies so only natural language
reaches the end user.

This is the *single* chokepoint that both WhatsApp and dashboard channels
call before delivering a message.
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns (order matters – most specific first)
# ---------------------------------------------------------------------------

# Markdown fenced code blocks whose info-string hints at JSON / data
_FENCED_JSON_RE = re.compile(
    r"```(?:json|jsonc|JSON)?\s*\n?\{[\s\S]*?\}\s*\n?```",
    re.MULTILINE,
)

# Markdown fenced code blocks that are entirely a JSON array
_FENCED_JSON_ARRAY_RE = re.compile(
    r"```(?:json|jsonc|JSON)?\s*\n?\[[\s\S]*?\]\s*\n?```",
    re.MULTILINE,
)

# Bare JSON objects (at least one key-value pair) that sit on their own line.
# We require the opening brace at the start of a line (after optional
# whitespace) to avoid stripping e.g. "{name}" inside a sentence.
_BARE_JSON_OBJECT_RE = re.compile(
    r"^[ \t]*\{[\s\S]*?"        # opening brace
    r"\"[^\"]+\"\s*:"          # at least one "key":
    r"[\s\S]*?\}[ \t]*$",       # closing brace
    re.MULTILINE,
)

# Lines that look like raw tool / function output labels
_TOOL_OUTPUT_LABEL_RE = re.compile(
    r"^[ \t]*(?:Tool (?:output|result|response)|Function (?:output|result|response))"
    r"[ \t]*[:=].*$",
    re.MULTILINE | re.IGNORECASE,
)

# Consecutive blank lines left after stripping → collapse to one
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _looks_like_json(text: str) -> bool:
    """Return True if *text* parses as a JSON object or array."""
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] not in ("{", "["):
        return False
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _strip_fenced_json(text: str) -> str:
    """Remove markdown fenced blocks that contain JSON."""
    text = _FENCED_JSON_RE.sub("", text)
    text = _FENCED_JSON_ARRAY_RE.sub("", text)
    return text


def _strip_bare_json_objects(text: str) -> str:
    """Remove bare JSON objects that span one or more lines."""

    def _replace(match: re.Match) -> str:
        candidate = match.group(0)
        if _looks_like_json(candidate):
            return ""
        return candidate

    return _BARE_JSON_OBJECT_RE.sub(_replace, text)


def _strip_tool_labels(text: str) -> str:
    return _TOOL_OUTPUT_LABEL_RE.sub("", text)


def _collapse_whitespace(text: str) -> str:
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sanitize_response(text: Optional[str]) -> str:
    """Remove structured / JSON data from an assistant reply.

    Returns the natural-language portion of the message, or an empty string
    if nothing remains.
    """
    if not text:
        return ""

    original = text

    text = _strip_fenced_json(text)
    text = _strip_bare_json_objects(text)
    text = _strip_tool_labels(text)
    text = _collapse_whitespace(text)

    if text != original:
        logger.debug(
            "response_pipeline: sanitised response (removed %d chars)",
            len(original) - len(text),
        )

    return text
