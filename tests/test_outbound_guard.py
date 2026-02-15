"""Tests for koda2.modules.messaging.outbound_guard."""
import pytest
from koda2.modules.messaging.outbound_guard import sanitize_outbound


class TestSanitizeOutbound:
    def test_none_returns_default(self):
        assert sanitize_outbound(None) == "Done."

    def test_empty_string_returns_default(self):
        assert sanitize_outbound("") == "Done."

    def test_plain_text_unchanged(self):
        msg = "Sure! I've scheduled your meeting for 3 PM tomorrow."
        assert sanitize_outbound(msg) == msg

    def test_strips_fenced_json_block(self):
        msg = 'Here is the result:\n```json\n{"status": "success", "id": "123"}\n```\nAll done!'
        result = sanitize_outbound(msg)
        assert "{" not in result
        assert "All done!" in result

    def test_strips_bare_json_object(self):
        msg = 'I created the reminder.\n{"reminder_id": "abc", "status": "created"}'
        result = sanitize_outbound(msg)
        assert "reminder_id" not in result
        assert "I created the reminder." in result

    def test_strips_tool_call_tags(self):
        msg = "Let me check that. <tool_call>get_calendar()</tool_call> Here are your events."
        result = sanitize_outbound(msg)
        assert "<tool_call>" not in result
        assert "Here are your events." in result

    def test_strips_function_result_tags(self):
        msg = 'Done! <function_result>{"ok": true}</function_result>'
        result = sanitize_outbound(msg)
        assert "<function_result>" not in result
        assert "Done!" in result

    def test_strips_tool_result_tags(self):
        msg = '<tool_result>{"events": []}</tool_result>You have no events today.'
        result = sanitize_outbound(msg)
        assert "<tool_result>" not in result
        assert "You have no events today." in result

    def test_strips_inline_status_json(self):
        msg = 'Reminder set! {"status": "success", "reminder_id": "r123"}'
        result = sanitize_outbound(msg)
        assert "status" not in result
        assert "Reminder set!" in result

    def test_strips_action_block(self):
        msg = 'Action: CREATE_REMINDER\nResult: {"id": "123"}\nYour reminder is set.'
        result = sanitize_outbound(msg)
        assert "CREATE_REMINDER" not in result
        assert "Your reminder is set." in result

    def test_preserves_normal_braces(self):
        msg = "The meeting is at {location TBD} tomorrow."
        result = sanitize_outbound(msg)
        assert "{location TBD}" in result

    def test_multiple_json_blocks_stripped(self):
        msg = 'First: ```json\n{"a": 1}\n```\nMiddle text.\n```json\n{"b": 2}\n```\nEnd.'
        result = sanitize_outbound(msg)
        assert "{" not in result
        assert "Middle text." in result
        assert "End." in result

    def test_only_json_returns_default(self):
        msg = '{"status": "success"}'
        result = sanitize_outbound(msg)
        assert result == "Done."

    def test_collapses_excessive_newlines(self):
        msg = "Hello.\n\n\n\n\n\nGoodbye."
        result = sanitize_outbound(msg)
        assert "\n\n\n" not in result
        assert "Hello." in result
        assert "Goodbye." in result
