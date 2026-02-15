"""Tests for koda2.modules.messaging.response_pipeline."""

import pytest

from koda2.modules.messaging.response_pipeline import sanitize_response


class TestSanitizeResponse:
    """Verify JSON / structured data is stripped while prose is kept."""

    def test_plain_text_unchanged(self):
        msg = "Sure! I've scheduled your meeting for 3 PM tomorrow."
        assert sanitize_response(msg) == msg

    def test_none_returns_empty(self):
        assert sanitize_response(None) == ""

    def test_empty_returns_empty(self):
        assert sanitize_response("") == ""

    def test_strips_fenced_json_block(self):
        msg = (
            "Here is the result:\n"
            "```json\n"
            '{"status": "ok", "id": 123}\n'
            "```\n"
            "Your meeting has been created."
        )
        result = sanitize_response(msg)
        assert "{" not in result
        assert "Your meeting has been created" in result

    def test_strips_bare_json_object(self):
        msg = (
            "Done! I created the event.\n"
            '{"event_id": "abc-123", "calendar": "primary"}\n'
            "Let me know if you need anything else."
        )
        result = sanitize_response(msg)
        assert "event_id" not in result
        assert "Let me know" in result

    def test_strips_tool_output_label(self):
        msg = (
            "Tool output: {\"success\": true}\n"
            "I've completed the task."
        )
        result = sanitize_response(msg)
        assert "Tool output" not in result
        assert "completed the task" in result

    def test_preserves_curly_braces_in_prose(self):
        msg = "Use the format {name} to insert your name."
        assert sanitize_response(msg) == msg

    def test_strips_multiple_json_blocks(self):
        msg = (
            "First result:\n"
            "```json\n{\"a\": 1}\n```\n"
            "Second result:\n"
            "```json\n{\"b\": 2}\n```\n"
            "All done."
        )
        result = sanitize_response(msg)
        assert "{" not in result
        assert "All done" in result

    def test_strips_fenced_json_array(self):
        msg = (
            "Here are your tasks:\n"
            '```json\n[{"task": "Buy milk"}, {"task": "Call dentist"}]\n```\n'
            "Let me know if you want to add more."
        )
        result = sanitize_response(msg)
        assert "Buy milk" not in result
        assert "Let me know" in result

    def test_collapses_extra_blank_lines(self):
        msg = "Hello.\n\n\n\n\nGoodbye."
        result = sanitize_response(msg)
        assert result == "Hello.\n\nGoodbye."

    def test_large_nested_json_stripped(self):
        import json
        blob = json.dumps({"users": [{"id": i, "name": f"User {i}"} for i in range(20)]})
        msg = f"Here are the users:\n{blob}\nThat's everyone."
        result = sanitize_response(msg)
        assert "users" not in result
        assert "everyone" in result
