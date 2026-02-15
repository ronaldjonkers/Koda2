"""Response sanitizer to strip raw JSON and technical data from user-facing messages."""

import json
import re
import logging

logger = logging.getLogger(__name__)


def sanitize_response(text: str) -> str:
    """Sanitize a response before sending to the user.
    
    - If the entire response is a JSON object/array, extract the human-readable
      'message', 'content', 'text', or 'response' field.
    - Strip inline JSON objects/arrays from mixed text.
    - Remove lines that look like technical/system data.
    
    Args:
        text: The raw response text from the LLM or orchestrator.
        
    Returns:
        Cleaned, human-readable text.
    """
    if not text or not isinstance(text, str):
        return text or ""
    
    stripped = text.strip()
    
    # Case 1: Entire response is a JSON object or array
    if (stripped.startswith('{') and stripped.endswith('}')) or \
       (stripped.startswith('[') and stripped.endswith(']')):
        try:
            parsed = json.loads(stripped)
            extracted = _extract_message_from_json(parsed)
            if extracted:
                logger.debug("Sanitizer: extracted message from full-JSON response")
                return extracted
            else:
                # JSON with no recognizable message field — return generic fallback
                logger.warning("Sanitizer: full-JSON response with no message field, suppressing")
                return "Done. Let me know if you need anything else."
        except (json.JSONDecodeError, ValueError):
            # Not valid JSON despite looking like it — fall through to regex cleaning
            pass
    
    # Case 2: Mixed text with embedded JSON blocks
    cleaned = _strip_embedded_json(stripped)
    
    # Case 3: Remove lines that look like raw technical data
    cleaned = _strip_technical_lines(cleaned)
    
    # Clean up excessive whitespace from removals
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    
    if not cleaned:
        logger.warning("Sanitizer: entire response was technical data, returning fallback")
        return "Done. Let me know if you need anything else."
    
    return cleaned


def _extract_message_from_json(data) -> str | None:
    """Try to extract a human-readable message from parsed JSON."""
    if isinstance(data, dict):
        # Try common message field names in priority order
        for key in ('message', 'content', 'text', 'response', 'reply', 'answer', 'summary'):
            if key in data and isinstance(data[key], str) and data[key].strip():
                return data[key].strip()
        # Try nested 'data' dict
        if 'data' in data and isinstance(data['data'], dict):
            return _extract_message_from_json(data['data'])
    elif isinstance(data, list):
        # If it's a list of strings, join them
        if all(isinstance(item, str) for item in data):
            return '\n'.join(data)
        # If list of dicts, try first item
        if data and isinstance(data[0], dict):
            return _extract_message_from_json(data[0])
    return None


def _strip_embedded_json(text: str) -> str:
    """Remove JSON objects and arrays embedded within regular text."""
    # Remove ```json ... ``` code blocks
    text = re.sub(r'```json\s*\n?.*?\n?```', '', text, flags=re.DOTALL)
    # Remove ``` ... ``` code blocks that contain JSON
    def _remove_json_codeblocks(match):
        content = match.group(1).strip()
        if content.startswith('{') or content.startswith('['):
            try:
                json.loads(content)
                return ''  # Valid JSON in code block — remove
            except (json.JSONDecodeError, ValueError):
                pass
        return match.group(0)  # Keep non-JSON code blocks
    
    text = re.sub(r'```\s*\n?(.*?)\n?```', _remove_json_codeblocks, text, flags=re.DOTALL)
    
    # Remove inline JSON objects { ... } that span significant content
    # Be careful not to remove things like {name} placeholders
    def _remove_inline_json(match):
        candidate = match.group(0)
        if len(candidate) < 10:
            return candidate  # Too short to be meaningful JSON
        try:
            json.loads(candidate)
            return ''  # Valid JSON — remove
        except (json.JSONDecodeError, ValueError):
            return candidate  # Not valid JSON — keep
    
    # Match balanced braces (simple heuristic for single-level)
    text = re.sub(r'\{[^{}]{10,}\}', _remove_inline_json, text)
    
    return text


def _strip_technical_lines(text: str) -> str:
    """Remove lines that look like technical/system output."""
    technical_patterns = [
        r'^\s*\{.*\}\s*$',           # Lines that are just JSON objects
        r'^\s*\[.*\]\s*$',           # Lines that are just JSON arrays
        r'^\s*"[a-z_]+"\s*:',        # Lines starting with JSON keys
        r'^\s*DEBUG\s*:',             # Debug output
        r'^\s*ERROR\s*:',             # Error output  
        r'^\s*TRACE\s*:',             # Trace output
        r'^\s*status_code\s*[=:]',    # HTTP status codes
        r'^\s*traceback',             # Python tracebacks
    ]
    
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        is_technical = False
        for pattern in technical_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                is_technical = True
                break
        if not is_technical:
            cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)
