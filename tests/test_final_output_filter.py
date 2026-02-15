"""Tests for the final output filter."""

import pytest
from koda2.modules.messaging.final_output_filter import filter_for_user


class TestFilterForUser:
    """Test filter_for_user function."""

    def test_plain_text_passes_through(self):
        msg = "Sure, I've scheduled your meeting for 3pm tomorrow."
        assert filter_for_user(msg) == msg

    def test_empty_returns_fallback(self):
        assert filter_for_user("") == ""
        assert filter_for_user(None) == ""
        assert filter_for_user("", fallback="Working on it...") == "Working on it..."

    def test_strips_fenced_tool_call_json(self):
        msg = (
            "Let me check your calendar.\n\n"
            '```json\n{"tool_calls": [{"name": "get_calendar", "arguments": {}}]}\n```'
        )
        result = filter_for_user(msg)
        assert "tool_calls" not in result
        assert "Let me check your calendar" in result

    def test_strips_standalone_tool_call_json(self):
        msg = (
            "Here you go!\n"
            '{"name": "send_email", "arguments": {"to": "bob@x.com"}, "type": "function"}'
        )
        result = filter_for_user(msg)
        assert "send_email" not in result
        assert "Here you go" in result

    def test_pure_tool_call_returns_fallback(self):
        msg = '{"tool_calls": [{"name": "search", "arguments": {"q": "test"}, "type": "function"}]}'
        assert filter_for_user(msg) == ""
        assert filter_for_user(msg, fallback="Working on it...") == "Working on it..."

    def test_json_with_content_field_extracted(self):
        msg = '{"role": "assistant", "content": "Hello! How can I help?", "tool_calls": [{"name": "x", "type": "function"}]}'
        result = filter_for_user(msg)
        assert result == "Hello! How can I help?"

    def test_normal_json_in_response_preserved(self):
        """JSON that doesn't look like tool calls should be kept."""
        msg = 'Here is the data:\n```json\n{"temperature": 72, "humidity": 45}\n```'
        result = filter_for_user(msg)
        assert "temperature" in result

    def test_mixed_text_and_tool_call(self):
        msg = (
            "I'll send that email for you right away.\n\n"
            '```json\n'
            '{"tool_calls": [{"id": "call_123", "type": "function", '
            '"function": {"name": "send_email", "arguments": "{\\"to\\": \\"bob@x.com\\"}"}}]}\n'
            '```\n\n'
            "Is there anything else you need?"
        )
        result = filter_for_user(msg)
        assert "send that email" in result
        assert "anything else" in result
        assert "tool_calls" not in result

    def test_multiline_whitespace_collapsed(self):
        msg = "Hello\n\n\n\n\n\nWorld"
        result = filter_for_user(msg)
        assert result == "Hello\n\nWorld"
