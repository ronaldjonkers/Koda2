"""Outbound message sanitizer.

Strips JSON blocks, tool-call metadata, and internal artifacts from
messages before they reach the end user (WhatsApp, Dashboard, etc.).
"""

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Fenced code blocks labelled json / JSON
_FENCED_JSON_RE = re.compile(
    r"```(?:json|JSON)\s*\n?.*?```",
    re.DOTALL,
)

# Generic fenced code blocks that contain only a JSON object/array
_FENCED_GENERIC_JSON_RE = re.compile(
    r"```\s*\n?(\s*[{\[].+?[}\]])\s*\n?```",
    re.DOTALL,
)

# Standalone JSON objects that span an entire line-group and look like
# internal data (at least two key-value pairs).  We anchor on newlines
# (or start/end of string) so we don't strip JSON that is clearly part
# of a sentence.
_STANDALONE_JSON_RE = re.compile(
    r"(?:^|\n)\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})\s*(?:\n|$)",
    re.DOTALL,
)

# Tool / function call markers that various LLMs emit
_TOOL_CALL_PATTERNS: list[re.Pattern] = [
    # OpenAI-style function_call / tool_calls leakage
    re.compile(r"<\|?(?:function_call|tool_call|plugin|action)[|>].*?<\|?/(?:function_call|tool_call|plugin|action)[|>]", re.DOTALL | re.IGNORECASE),
    # <tool_call>...</tool_call>  or  <tool_result>...</tool_result>
    re.compile(r"</?tool_(?:call|result|use|response)[^>]*>.*?(?:</tool_(?:call|result|use|response)>)", re.DOTALL | re.IGNORECASE),
    # Inline tags without closing (single-line)
    re.compile(r"</?tool_(?:call|result|use|response)[^>]*>", re.IGNORECASE),
    # [TOOL_CALL] ... [/TOOL_CALL]  bracket style
    re.compile(r"\[/?TOOL_(?:CALL|RESULT|RESPONSE)\].*?(?:\[/TOOL_(?:CALL|RESULT|RESPONSE)\])", re.DOTALL | re.IGNORECASE),
    re.compile(r"\[/?TOOL_(?:CALL|RESULT|RESPONSE)\]", re.IGNORECASE),
    # Function(name=..., arguments=...) style
    re.compile(r"Function\s*\(\s*name\s*=.*?\)", re.DOTALL | re.IGNORECASE),
    # "action": ... / "action_input": ... blocks (ReAct-style)
    re.compile(r'"action"\s*:\s*"[^"]+"\s*,?\s*"action_input"\s*:.*?(?:\n|$)', re.DOTALL | re.IGNORECASE),
]

# Lines that are purely metadata labels (e.g. "Tool result:", "Function output:")
_META_LINE_RE = re.compile(
    r"^\s*(?:Tool (?:call|result|output|response)|Function (?:call|output|result)|Action (?:result|output)|Observation)\s*[:=].*$",
    re.MULTILINE | re.IGNORECASE,
)


def _looks_like_internal_json(text: str) -> bool:
    """Heuristic: does a JSON-ish string look like internal data?"""
    # Must have at least 2 key-like patterns
    keys = re.findall(r'"[a-z_]+"\s*:', text, re.IGNORECASE)
    return len(keys) >= 2


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sanitize_outbound_message(text: str | None) -> str:
    """Sanitize a message before sending it to the end user.

    Returns the cleaned natural-language portion of *text*, or an empty
    string if nothing meaningful remains.
    """
    if not text:
        return text or ""

    original_length = len(text)
    result = text

    # 1. Remove fenced JSON code blocks
    result = _FENCED_JSON_RE.sub("", result)

    # 2. Remove generic fenced blocks that contain only JSON
    def _strip_generic_fenced(m: re.Match) -> str:
        inner = m.group(1)
        if _looks_like_internal_json(inner):
            return ""
        return m.group(0)  # keep non-JSON fenced blocks

    result = _FENCED_GENERIC_JSON_RE.sub(_strip_generic_fenced, result)

    # 3. Remove tool / function call markers
    for pattern in _TOOL_CALL_PATTERNS:
        result = pattern.sub("", result)

    # 4. Remove metadata label lines
    result = _META_LINE_RE.sub("", result)

    # 5. Remove standalone JSON objects that look internal
    def _strip_standalone_json(m: re.Match) -> str:
        candidate = m.group(1)
        if _looks_like_internal_json(candidate):
            return "\n"
        return m.group(0)

    result = _STANDALONE_JSON_RE.sub(_strip_standalone_json, result)

    # 6. Collapse excessive blank lines
    result = re.sub(r"\n{3,}", "\n\n", result).strip()

    if len(result) < original_length:
        removed = original_length - len(result)
        logger.debug(
            "Outbound sanitizer removed %d chars from message (orig=%d)",
            removed,
            original_length,
        )

    return result
