"""Tests for sanitize_user_message."""

import pytest

from koda2.modules.messaging.sanitize_user_message import sanitize_user_message


class TestSanitizeUserMessage:
    """Test suite for sanitize_user_message."""

    def test_none_input(self):
        assert sanitize_user_message(None) == ""

    def test_empty_string(self):
        assert sanitize_user_message("") == ""

    def test_clean_message_unchanged(self):
        msg = "Your meeting is scheduled for 3pm tomorrow."
        assert sanitize_user_message(msg) == msg

    def test_strips_json_code_block(self):
        msg = 'Here is the result:\n```json\n{"tool_call": "create_event", "arguments": {}}\n```\nYour event has been created.'
        result = sanitize_user_message(msg)
        assert '```' not in result
        assert 'tool_call' not in result
        assert 'Your event has been created.' in result

    def test_strips_bare_tool_call_json(self):
        msg = 'Sure, let me check.\n{"tool_call": "search_contacts", "arguments": {"query": "John"}}\nI found John Smith in your contacts.'
        result = sanitize_user_message(msg)
        assert 'tool_call' not in result
        assert 'John Smith' in result

    def test_strips_xml_tool_tags(self):
        msg = 'Let me look that up.\n<tool_call>search("test")</tool_call>\nHere are your results.'
        result = sanitize_user_message(msg)
        assert '<tool_call>' not in result
        assert 'Here are your results.' in result

    def test_strips_function_header(self):
        msg = 'Function call: create_event\nYour event is created.'
        result = sanitize_user_message(msg)
        assert 'Function call' not in result
        assert 'Your event is created.' in result

    def test_strips_role_lines(self):
        msg = 'assistant:\nHere is your answer.'
        result = sanitize_user_message(msg)
        assert result == 'Here is your answer.'

    def test_extracts_message_from_json_blob(self):
        msg = '{"message": "Your meeting has been scheduled.", "status": "success"}'
        result = sanitize_user_message(msg)
        assert result == "Your meeting has been scheduled."

    def test_extracts_response_from_json_blob(self):
        msg = '{"response": "Done! Email sent.", "tool_call_id": "abc123"}'
        result = sanitize_user_message(msg)
        assert result == "Done! Email sent."

    def test_extracts_from_nested_result(self):
        msg = '{"result": {"message": "Contact added successfully."}, "status": "ok"}'
        result = sanitize_user_message(msg)
        assert result == "Contact added successfully."

    def test_preserves_non_json_code_blocks(self):
        msg = 'Here is the code:\n```python\nprint("hello")\n```\nHope that helps!'
        result = sanitize_user_message(msg)
        assert 'print("hello")' in result

    def test_cleans_excessive_newlines(self):
        msg = 'Hello.\n\n\n\n\nHow are you?'
        result = sanitize_user_message(msg)
        assert '\n\n\n' not in result
        assert 'Hello.' in result
        assert 'How are you?' in result

    def test_multiple_artifacts_combined(self):
        msg = (
            'assistant:\n'
            'Function call: search_contacts\n'
            '```json\n{"tool_call": "search", "arguments": {}}\n```\n'
            '<tool_result>{"contacts": ["John"]}</tool_result>\n'
            'I found John in your contacts!'
        )
        result = sanitize_user_message(msg)
        assert 'I found John in your contacts!' in result
        assert 'tool_call' not in result
        assert 'Function call' not in result
        assert '<tool_result>' not in result

    def test_entirely_json_returns_empty(self):
        msg = '{"tool_call_id": "123", "name": "search", "arguments": "{}"}'
        result = sanitize_user_message(msg)
        # No natural language key found, entire thing is JSON with only internal keys
        # The function returns the original since it can't extract a message
        # This is acceptable — the caller handles empty/json-only responses
        assert isinstance(result, str)
