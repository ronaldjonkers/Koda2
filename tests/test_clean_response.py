"""Tests for koda2.modules.messaging.clean_response."""
import json
import pytest

from koda2.modules.messaging.clean_response import clean_response


class TestCleanResponse:
    """Test suite for clean_response."""

    def test_plain_text_unchanged(self):
        msg = "Sure! I've set a reminder for 3pm tomorrow."
        assert clean_response(msg) == msg

    def test_empty_string_returns_fallback(self):
        assert clean_response("") == "Done \u2705"
        assert clean_response(None) == "Done \u2705"
        assert clean_response("   ") == "Done \u2705"

    def test_strips_fenced_tool_json(self):
        msg = (
            "Here's what I did:\n"
            "```json\n"
            '{"tool_call_id": "abc123", "name": "create_reminder", "arguments": "{}"}\n'
            "```\n"
            "Your reminder has been created!"
        )
        result = clean_response(msg)
        assert "tool_call_id" not in result
        assert "Your reminder has been created!" in result

    def test_keeps_user_requested_json(self):
        msg = '```json\n{"name": "Alice", "age": 30}\n```'
        result = clean_response(msg)
        assert '"name"' in result
        assert '"Alice"' in result

    def test_pure_tool_metadata_json(self):
        data = {
            "role": "assistant",
            "content": "I've created your reminder.",
            "tool_calls": [{"id": "tc_1", "function": {"name": "create_reminder"}}],
        }
        msg = json.dumps(data)
        result = clean_response(msg)
        assert result == "I've created your reminder."

    def test_pure_action_result_json_success(self):
        data = {"status": "success", "message": "Reminder created for 3pm tomorrow."}
        msg = json.dumps(data)
        result = clean_response(msg)
        assert result == "Reminder created for 3pm tomorrow."

    def test_pure_action_result_json_error(self):
        data = {"status": "error", "error": "Calendar not connected."}
        msg = json.dumps(data)
        result = clean_response(msg)
        assert "Calendar not connected" in result

    def test_pure_json_no_message_field(self):
        data = {"success": True}
        msg = json.dumps(data)
        result = clean_response(msg)
        assert "Done" in result

    def test_inline_tool_json_stripped(self):
        msg = (
            'I created the reminder. {"tool_call_id": "x", "name": "create_reminder", '
            '"arguments": "{}"} Let me know if you need anything else.'
        )
        result = clean_response(msg)
        assert "tool_call_id" not in result
        assert "I created the reminder" in result
        assert "Let me know" in result

    def test_multiline_collapse(self):
        msg = "Hello\n\n\n\n\nWorld"
        result = clean_response(msg)
        assert result == "Hello\n\nWorld"

    def test_mixed_text_and_metadata(self):
        msg = (
            "I've scheduled your meeting.\n"
            '```json\n{"role": "tool", "content": "ok", "tool_call_id": "123"}\n```\n'
            "Is there anything else you need?"
        )
        result = clean_response(msg)
        assert "I've scheduled your meeting" in result
        assert "Is there anything else" in result
        assert "tool_call_id" not in result
