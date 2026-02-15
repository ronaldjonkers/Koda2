"""Output sanitizer: removes JSON, technical data, and internal metadata from responses."""

import re
import json
import logging

logger = logging.getLogger(__name__)

# Patterns to detect and remove
_JSON_OBJECT_RE = re.compile(r'```(?:json)?\s*\{[\s\S]*?\}\s*```', re.MULTILINE)
_JSON_ARRAY_RE = re.compile(r'```(?:json)?\s*\[[\s\S]*?\]\s*```', re.MULTILINE)
_INLINE_JSON_OBJECT_RE = re.compile(r'(?<!\w)\{\s*"[^"]+"\s*:', re.MULTILINE)
_INLINE_JSON_ARRAY_RE = re.compile(r'(?<!\w)\[\s*\{\s*"[^"]+"\s*:', re.MULTILINE)
_TRACEBACK_RE = re.compile(r'Traceback \(most recent call last\)[\s\S]*?(?:\n\S|$)', re.MULTILINE)
_INTERNAL_ERROR_RE = re.compile(
    r'(?:(?:Internal(?:\s+server)?\s+error|Exception|Error|KeyError|TypeError|ValueError|AttributeError|RuntimeError)'
    r'\s*[:].+)',
    re.IGNORECASE,
)
_CAPABILITY_META_RE = re.compile(
    r'(?:capabilities|tools|functions|api_key|token|secret|password)\s*[:=]\s*[\S]+',
    re.IGNORECASE,
)
# Detect raw JSON objects that span multiple lines (not inside code fences)
_BARE_JSON_BLOCK_RE = re.compile(
    r'^\s*\{[\s\S]{20,}?\}\s*$', re.MULTILINE
)


def sanitize_response(text: str) -> str:
    """Remove JSON blocks, tracebacks, internal errors, and metadata from response text.

    Args:
        text: The raw response text from the LLM / orchestrator.

    Returns:
        Cleaned text safe for end-user consumption.
    """
    if not text:
        return text

    original = text

    # 1. Remove fenced JSON code blocks
    text = _JSON_OBJECT_RE.sub('', text)
    text = _JSON_ARRAY_RE.sub('', text)

    # 2. Remove bare multi-line JSON objects
    text = _BARE_JSON_BLOCK_RE.sub('', text)

    # 3. Remove tracebacks
    text = _TRACEBACK_RE.sub('', text)

    # 4. Remove internal error lines
    text = _INTERNAL_ERROR_RE.sub('', text)

    # 5. Remove capability / secret metadata lines
    text = _CAPABILITY_META_RE.sub('', text)

    # 6. Remove inline JSON that looks like tool output (heuristic: starts with {"key":)
    #    We only strip if it looks like a full JSON blob (>50 chars on one logical line)
    def _strip_inline_json(match: re.Match) -> str:
        # Find the end of the JSON object by brace counting
        start = match.start()
        brace_count = 0
        i = start
        while i < len(text):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    snippet = text[start:i + 1]
                    if len(snippet) > 50:
                        return ''
                    return snippet
            i += 1
        return match.group(0)

    # Apply inline JSON stripping iteratively (max 10 passes to avoid infinite loops)
    for _ in range(10):
        m = _INLINE_JSON_OBJECT_RE.search(text)
        if not m:
            break
        # Find matching closing brace
        start = m.start()
        brace_count = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break
        snippet = text[start:end]
        if len(snippet) > 50:
            text = text[:start] + text[end:]
        else:
            break  # Small JSON-like string, probably intentional

    # Clean up excessive whitespace left behind
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    if text != original:
        logger.info("Output sanitizer removed technical content from response (len %d -> %d)",
                    len(original), len(text))

    # If sanitization removed everything, return a fallback
    if not text:
        text = "Ik heb de informatie verwerkt, maar er is geen samenvatting beschikbaar. Kan ik je ergens anders mee helpen?"
        logger.warning("Output sanitizer stripped entire response; returning fallback.")

    return text
