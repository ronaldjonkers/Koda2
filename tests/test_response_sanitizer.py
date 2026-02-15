"""Tests for koda2.modules.messaging.response_sanitizer."""

import pytest
from koda2.modules.messaging.response_sanitizer import sanitize_response


class TestSanitizeResponse:
    """Tests for the sanitize_response function."""

    def test_plain_text_unchanged(self):
        text = "Sure, I've scheduled your meeting for 3pm tomorrow."
        assert sanitize_response(text) == text

    def test_empty_string(self):
        assert sanitize_response("") == ""

    def test_none_returns_empty(self):
        assert sanitize_response(None) == ""

    def test_strips_json_code_block(self):
        text = (
            "Here's your summary:\n\n"
            '```json\n{"status": "success", "count": 3}\n```\n\n'
            "Let me know if you need anything else."
        )
        result = sanitize_response(text)
        assert '```' not in result
        assert '"status"' not in result
        assert "Here's your summary:" in result
        assert "Let me know if you need anything else." in result

    def test_strips_json_array_code_block(self):
        text = (
            "Found these results:\n\n"
            '```json\n[{"name": "Alice"}, {"name": "Bob"}]\n```\n\n'
            "Would you like more details?"
        )
        result = sanitize_response(text)
        assert '```' not in result
        assert '"name"' not in result
        assert "Found these results:" in result

    def test_strips_standalone_json_object(self):
        text = (
            "I created the event.\n"
            '{\n  "event_id": "abc123",\n  "title": "Team Standup"\n}\n'
            "It's all set!"
        )
        result = sanitize_response(text)
        assert '"event_id"' not in result
        assert "I created the event." in result
        assert "It's all set!" in result

    def test_strips_tool_call_xml_tags(self):
        text = (
            "<tool_call>get_calendar</tool_call>\n"
            "Your calendar is clear for tomorrow."
        )
        result = sanitize_response(text)
        assert "<tool_call>" not in result
        assert "Your calendar is clear for tomorrow." in result

    def test_strips_function_xml_tags(self):
        text = (
            '<function=search_contacts>{"query": "John"}</function>\n'
            "I found John Smith in your contacts."
        )
        result = sanitize_response(text)
        assert "<function=" not in result
        assert "I found John Smith" in result

    def test_preserves_normal_braces_in_text(self):
        text = "The event {Team Standup} has been created."
        result = sanitize_response(text)
        # This should NOT be stripped because it doesn't look like JSON
        assert "{Team Standup}" in result

    def test_mixed_natural_language_and_json(self):
        text = (
            "I've sent the email successfully.\n\n"
            '```json\n'
            '{\n'
            '  "status": "sent",\n'
            '  "message_id": "msg_12345",\n'
            '  "recipients": ["alice@example.com"]\n'
            '}\n'
            '```\n\n'
            "The email was delivered to Alice."
        )
        result = sanitize_response(text)
        assert "I've sent the email successfully." in result
        assert "The email was delivered to Alice." in result
        assert '"status"' not in result
        assert '"message_id"' not in result

    def test_strips_tool_calls_key(self):
        text = (
            '"tool_calls": [{"function": "send_email"}]\n'
            "Your email has been sent."
        )
        result = sanitize_response(text)
        assert "tool_calls" not in result
        assert "Your email has been sent." in result

    def test_no_excessive_whitespace(self):
        text = (
            "Line one.\n\n\n\n\n\nLine two."
        )
        result = sanitize_response(text)
        assert "\n\n\n" not in result
        assert "Line one." in result
        assert "Line two." in result

    def test_multiple_json_blocks_stripped(self):
        text = (
            "First result:\n"
            '```json\n{"a": 1}\n```\n'
            "Second result:\n"
            '```json\n{"b": 2}\n```\n'
            "All done!"
        )
        result = sanitize_response(text)
        assert '```' not in result
        assert "All done!" in result

    def test_preserves_non_json_code_blocks(self):
        text = (
            "Here's the code:\n\n"
            '```python\nprint("hello world")\n```\n\n'
            "Let me know if that helps."
        )
        result = sanitize_response(text)
        # Non-JSON code blocks should be preserved
        assert 'print("hello world")' in result
