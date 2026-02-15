"""Tests for koda2.modules.messaging.output_sanitizer."""

import pytest
from koda2.modules.messaging.output_sanitizer import sanitize_response


def test_strips_fenced_json_block():
    text = 'Hier is het resultaat:\n```json\n{"key": "value", "nested": {"a": 1}}\n```\nKlaar!'
    result = sanitize_response(text)
    assert '{' not in result
    assert 'Klaar!' in result


def test_strips_bare_json_object():
    text = 'Resultaat:\n{"status": "ok", "data": {"items": [1,2,3], "count": 3}}\nDat was het.'
    result = sanitize_response(text)
    assert '"status"' not in result
    assert 'Dat was het.' in result


def test_strips_traceback():
    text = 'Er ging iets mis:\nTraceback (most recent call last):\n  File "x.py", line 1\nValueError: bad\nProbeer opnieuw.'
    result = sanitize_response(text)
    assert 'Traceback' not in result
    assert 'Probeer opnieuw' in result


def test_strips_internal_error_line():
    text = 'Internal server error: connection refused\nIk help je graag verder.'
    result = sanitize_response(text)
    assert 'Internal server error' not in result
    assert 'help je graag' in result


def test_strips_capability_metadata():
    text = 'api_key: sk-abc123\nHier is je antwoord.'
    result = sanitize_response(text)
    assert 'api_key' not in result
    assert 'antwoord' in result


def test_preserves_normal_text():
    text = 'Goedemorgen Ronald! Hoe kan ik je helpen vandaag?'
    result = sanitize_response(text)
    assert result == text


def test_fallback_when_everything_stripped():
    text = '{"internal": "data", "secret": "value", "more_keys": "aaaaaaaaaaaaaaaaaaa"}'
    result = sanitize_response(text)
    assert len(result) > 0
    assert 'JSON' not in result  # Should be a natural language fallback


def test_empty_input():
    assert sanitize_response('') == ''
    assert sanitize_response(None) is None


def test_small_json_like_preserved():
    """Small JSON-like strings (e.g. emoji shortcodes) should not be stripped."""
    text = 'De status is {"ok"}.'
    result = sanitize_response(text)
    # Small snippet (<50 chars) should be preserved
    assert 'status' in result
