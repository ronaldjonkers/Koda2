"""Tests for koda2.modules.messaging.outbound_sanitizer."""

import pytest

from koda2.modules.messaging.outbound_sanitizer import sanitize_outbound_message


class TestSanitizeOutboundMessage:
    """Test suite for sanitize_outbound_message."""

    def test_none_input(self):
        assert sanitize_outbound_message(None) == ""

    def test_empty_string(self):
        assert sanitize_outbound_message("") == ""

    def test_plain_text_unchanged(self):
        msg = "Hello! Your meeting is at 3 PM tomorrow."
        assert sanitize_outbound_message(msg) == msg

    def test_strips_fenced_json_block(self):
        msg = (
            "Here is your summary.\n"
            "```json\n"
            '{"status": "ok", "count": 3}\n'
            "```\n"
            "Let me know if you need anything else."
        )
        result = sanitize_outbound_message(msg)
        assert "```json" not in result
        assert '"status"' not in result
        assert "Here is your summary." in result
        assert "Let me know if you need anything else." in result

    def test_strips_standalone_json_object(self):
        msg = (
            "Done! I created the event.\n"
            '{"event_id": "abc123", "calendar": "primary", "created": true}\n'
            "Anything else?"
        )
        result = sanitize_outbound_message(msg)
        assert '"event_id"' not in result
        assert "Done! I created the event." in result
        assert "Anything else?" in result

    def test_keeps_simple_json_in_sentence(self):
        # A single key-value mentioned inline should NOT be stripped
        msg = 'The response was {"ok": true} which means success.'
        result = sanitize_outbound_message(msg)
        assert result == msg

    def test_strips_tool_call_xml_tags(self):
        msg = (
            "<tool_call>{\"name\": \"search\", \"args\": {}}\n</tool_call>\n"
            "I found 3 results for your query."
        )
        result = sanitize_outbound_message(msg)
        assert "<tool_call>" not in result
        assert "I found 3 results" in result

    def test_strips_tool_result_tags(self):
        msg = (
            "I checked your calendar.\n"
            "<tool_result>Event created successfully</tool_result>\n"
            "Your meeting is set for 2 PM."
        )
        result = sanitize_outbound_message(msg)
        assert "<tool_result>" not in result
        assert "Your meeting is set for 2 PM." in result

    def test_strips_function_call_style(self):
        msg = (
            'Function(name="send_email", arguments={"to": "a@b.com"})\n'
            "Email sent successfully!"
        )
        result = sanitize_outbound_message(msg)
        assert "Function(" not in result
        assert "Email sent successfully!" in result

    def test_strips_metadata_lines(self):
        msg = (
            "Tool result: {\"success\": true}\n"
            "I've completed the task for you."
        )
        result = sanitize_outbound_message(msg)
        assert "Tool result:" not in result
        assert "completed the task" in result

    def test_strips_react_action_blocks(self):
        msg = (
            '"action": "search_contacts", "action_input": {"query": "John"}\n'
            "I found John Smith in your contacts."
        )
        result = sanitize_outbound_message(msg)
        assert '"action":' not in result
        assert "John Smith" in result

    def test_strips_bracket_style_tool_markers(self):
        msg = (
            "[TOOL_CALL]search_calendar[/TOOL_CALL]\n"
            "You have 2 meetings today."
        )
        result = sanitize_outbound_message(msg)
        assert "[TOOL_CALL]" not in result
        assert "2 meetings today" in result

    def test_collapses_excessive_blank_lines(self):
        msg = "Hello.\n\n\n\n\nGoodbye."
        result = sanitize_outbound_message(msg)
        assert result == "Hello.\n\nGoodbye."

    def test_full_message_stripped_returns_empty(self):
        msg = '```json\n{"internal": "data", "status": "ok"}\n```'
        result = sanitize_outbound_message(msg)
        assert result == ""

    def test_mixed_content(self):
        msg = (
            "Great news!\n"
            "```json\n"
            '{"event_id": "123", "status": "created"}\n'
            "```\n"
            "<tool_result>success</tool_result>\n"
            "Tool output: done\n"
            "\n"
            "Your calendar event has been created for tomorrow at 10 AM.\n"
            '{"internal_log": "abc", "trace_id": "xyz"}\n'
            "Let me know if you need changes!"
        )
        result = sanitize_outbound_message(msg)
        assert "```json" not in result
        assert "<tool_result>" not in result
        assert "Tool output:" not in result
        assert '"internal_log"' not in result
        assert "Great news!" in result
        assert "calendar event has been created" in result
        assert "Let me know if you need changes!" in result
