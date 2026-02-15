"""Outbound guard: final sanitization before any message reaches a user.

This is the SINGLE canonical place where user-facing text is cleaned.
It runs at the network boundary (WhatsApp send, WebSocket send) so
nothing can bypass it.
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns that should never appear in user-facing messages
_JSON_BLOCK_RE = re.compile(
    r"```(?:json)?\s*\n?\{[\s\S]*?\}\s*\n?```",
    re.IGNORECASE,
)
_BARE_JSON_OBJECT_RE = re.compile(
    r'(?:^|\n)\s*\{\s*"[a-zA-Z_]+"\s*:.*?\}\s*(?:$|\n)',
    re.DOTALL,
)
_TOOL_CALL_RE = re.compile(
    r"<tool_call>.*?</tool_call>",
    re.DOTALL | re.IGNORECASE,
)
_FUNCTION_RESULT_RE = re.compile(
    r"<function_result>.*?</function_result>",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_RESULT_RE = re.compile(
    r"<tool_result>.*?</tool_result>",
    re.DOTALL | re.IGNORECASE,
)
# Catches lines like: {"status": "success", "reminder_id": "abc123", ...}
_INLINE_JSON_RE = re.compile(
    r'\{"(?:status|success|error|result|id|reminder_id|invoice_id|task_id|event_id|message_id)"\s*:.*?\}',
    re.DOTALL,
)
# Action confirmation blocks: "Action: CREATE_REMINDER\nResult: {...}"
_ACTION_BLOCK_RE = re.compile(
    r"Action:\s*[A-Z_]+\s*\n\s*Result:\s*\{.*?\}",
    re.DOTALL,
)


def sanitize_outbound(text: Optional[str]) -> str:
    """Strip internal/technical artifacts from a user-facing message.

    This function is intentionally aggressive: it is better to remove
    something borderline than to leak raw JSON to a user.

    Args:
        text: The raw response text (may be None).

    Returns:
        Cleaned text safe for user consumption.  Never returns empty
        string – falls back to a polite default.
    """
    if not text:
        return "Done."

    original = text
    cleaned = text

    # 1. Remove fenced JSON code blocks
    cleaned = _JSON_BLOCK_RE.sub("", cleaned)

    # 2. Remove XML-style tool/function tags
    cleaned = _TOOL_CALL_RE.sub("", cleaned)
    cleaned = _FUNCTION_RESULT_RE.sub("", cleaned)
    cleaned = _TOOL_RESULT_RE.sub("", cleaned)

    # 3. Remove action confirmation blocks
    cleaned = _ACTION_BLOCK_RE.sub("", cleaned)

    # 4. Remove inline JSON objects that look like API responses
    cleaned = _INLINE_JSON_RE.sub("", cleaned)

    # 5. Remove bare JSON objects (multi-line)
    cleaned = _BARE_JSON_OBJECT_RE.sub("", cleaned)

    # 6. Remove any remaining lines that are purely JSON-like
    lines = cleaned.split("\n")
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                json.loads(stripped)
                # It's valid JSON – skip this line
                continue
            except (json.JSONDecodeError, ValueError):
                pass
        filtered_lines.append(line)
    cleaned = "\n".join(filtered_lines)

    # 7. Collapse excessive whitespace left by removals
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    if cleaned != original:
        logger.info(
            "Outbound guard sanitized response (removed %d chars)",
            len(original) - len(cleaned),
        )
        logger.debug("Original: %s", original[:500])
        logger.debug("Cleaned:  %s", cleaned[:500])

    if not cleaned:
        return "Done."

    return cleaned
