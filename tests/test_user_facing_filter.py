"""Tests for koda2.modules.messaging.user_facing_filter."""

import pytest

from koda2.modules.messaging.user_facing_filter import filter_for_user, is_user_safe


class TestFilterForUser:
    """Tests for filter_for_user function."""

    def test_plain_text_unchanged(self):
        text = "Sure! I've scheduled your meeting for 3pm tomorrow."
        assert filter_for_user(text) == text

    def test_none_returns_empty(self):
        assert filter_for_user(None) == ""

    def test_empty_returns_empty(self):
        assert filter_for_user("") == ""

    def test_strips_fenced_json_block(self):
        text = """Here's your summary.

```json
{"tool_call": "create_reminder", "arguments": {"time": "3pm"}}
```

I've set that up for you."""
        result = filter_for_user(text)
        assert '```json' not in result
        assert 'tool_call' not in result
        assert "Here's your summary." in result
        assert "I've set that up for you." in result

    def test_strips_tool_call_xml_block(self):
        text = """I'll create that reminder for you.

<tool_call>{"name": "create_reminder", "arguments": {"time": "3pm"}}</tool_call>

Done! Your reminder is set."""
        result = filter_for_user(text)
        assert '<tool_call>' not in result
        assert 'create_reminder' not in result
        assert "Done! Your reminder is set." in result

    def test_strips_standalone_json_object(self):
        text = """I found the information.

{"tool_call_id": "abc123", "name": "search", "arguments": {"query": "test"}}

Here are the results."""
        result = filter_for_user(text)
        assert 'tool_call_id' not in result
        assert 'Here are the results.' in result

    def test_strips_action_observation_lines(self):
        text = """Let me look that up.
Action: search_contacts
Action Input: {"name": "John"}
Observation: Found 1 contact
I found John's contact information."""
        result = filter_for_user(text)
        assert 'Action:' not in result
        assert 'Action Input:' not in result
        assert 'Observation:' not in result
        assert 'Let me look that up.' in result
        assert "I found John's contact information." in result

    def test_strips_pure_json_tool_response(self):
        text = '{"tool_call": "get_weather", "arguments": {"city": "NYC"}}'
        result = filter_for_user(text)
        assert result == ""

    def test_preserves_user_facing_json_mention(self):
        """If the user asks about JSON, the word 'JSON' in natural language should stay."""
        text = "JSON is a data format commonly used in web APIs."
        assert filter_for_user(text) == text

    def test_strips_function_call_block(self):
        text = """Sure, let me check.

```function_call
{"name": "check_calendar", "params": {"date": "2024-01-15"}}
```

You have 2 meetings tomorrow."""
        result = filter_for_user(text)
        assert '```function_call' not in result
        assert 'check_calendar' not in result
        assert 'You have 2 meetings tomorrow.' in result

    def test_strips_metadata_lines(self):
        text = """Here's what I found.
tool_call_id: call_abc123
function_name: search
The search returned 5 results."""
        result = filter_for_user(text)
        assert 'tool_call_id:' not in result
        assert 'function_name:' not in result
        assert 'The search returned 5 results.' in result

    def test_multiple_json_blocks_stripped(self):
        text = """Step 1 done.

```json
{"step": 1, "result": "ok"}
```

Step 2 done.

```json
{"step": 2, "result": "ok"}
```

All steps complete!"""
        result = filter_for_user(text)
        assert '```json' not in result
        assert 'Step 1 done.' in result
        assert 'Step 2 done.' in result
        assert 'All steps complete!' in result

    def test_preserves_normal_code_blocks(self):
        """Non-JSON code blocks should be preserved (user might ask about code)."""
        text = """Here's the Python code:

```python
print("hello world")
```

Hope that helps!"""
        result = filter_for_user(text)
        assert '```python' in result
        assert 'print("hello world")' in result

    def test_strips_result_json(self):
        text = '{"result": "success", "status": 200}'
        result = filter_for_user(text)
        assert result == ""

    def test_strips_json_array_of_objects(self):
        text = """Found these:

[{"id": 1, "name": "Task 1"}, {"id": 2, "name": "Task 2"}]

Let me know if you need more details."""
        result = filter_for_user(text)
        assert '"id"' not in result
        assert 'Let me know if you need more details.' in result

    def test_excessive_newlines_collapsed(self):
        text = "Hello.\n\n\n\n\nWorld."
        result = filter_for_user(text)
        assert '\n\n\n' not in result
        assert 'Hello.' in result
        assert 'World.' in result


class TestIsUserSafe:
    """Tests for is_user_safe function."""

    def test_clean_text_is_safe(self):
        assert is_user_safe("Hello, how can I help?") is True

    def test_json_block_is_not_safe(self):
        text = 'Hello ```json\n{"a": 1}\n``` bye'
        assert is_user_safe(text) is False

    def test_empty_is_safe(self):
        assert is_user_safe("") is True

    def test_none_like_empty_is_safe(self):
        assert is_user_safe("") is True
