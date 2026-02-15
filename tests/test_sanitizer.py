"""Tests for response sanitizer."""

import pytest
from koda2.modules.messaging.sanitizer import sanitize_response


class TestSanitizeResponse:
    """Test sanitize_response function."""

    def test_plain_text_unchanged(self):
        text = "Hello! How can I help you today?"
        assert sanitize_response(text) == text

    def test_full_json_extracts_message(self):
        text = '{"message": "Your meeting is at 3pm", "status": "ok"}'
        assert sanitize_response(text) == "Your meeting is at 3pm"

    def test_full_json_extracts_content(self):
        text = '{"content": "Email sent successfully", "id": 123}'
        assert sanitize_response(text) == "Email sent successfully"

    def test_full_json_extracts_text(self):
        text = '{"text": "Reminder set for tomorrow", "code": 200}'
        assert sanitize_response(text) == "Reminder set for tomorrow"

    def test_full_json_no_message_field(self):
        text = '{"status": "ok", "code": 200}'
        result = sanitize_response(text)
        assert "JSON" not in result
        assert "status" not in result

    def test_embedded_json_code_block_removed(self):
        text = 'Here is the result:\n```json\n{"key": "value"}\n```\nLet me know!'
        result = sanitize_response(text)
        assert '"key"' not in result
        assert "Let me know!" in result

    def test_empty_string(self):
        assert sanitize_response("") == ""

    def test_none_input(self):
        assert sanitize_response(None) == ""

    def test_mixed_text_with_json(self):
        text = 'I found the info. {"status": "success", "data": "internal"} Hope that helps!'
        result = sanitize_response(text)
        assert "Hope that helps" in result

    def test_json_array_full_response(self):
        text = '["item1", "item2", "item3"]'
        result = sanitize_response(text)
        assert "item1" in result

    def test_nested_json_message(self):
        text = '{"data": {"message": "Nested message here"}}'
        assert sanitize_response(text) == "Nested message here"

    def test_technical_lines_removed(self):
        text = 'Your meeting is set.\nDEBUG: cache hit\nSee you there!'
        result = sanitize_response(text)
        assert "DEBUG" not in result
        assert "Your meeting is set." in result
        assert "See you there!" in result

    def test_preserves_normal_braces(self):
        text = "Use the format {name} for templates."
        result = sanitize_response(text)
        assert "{name}" in result

    def test_json_response_field(self):
        text = '{"response": "All done!", "internal_id": "abc123"}'
        assert sanitize_response(text) == "All done!"
