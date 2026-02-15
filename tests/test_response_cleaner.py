"""Tests for the response cleaner module."""

import pytest
from koda2.modules.messaging.response_cleaner import clean_response


class TestCleanResponse:
    """Tests for clean_response function."""

    def test_plain_text_unchanged(self):
        """Plain text responses should pass through unchanged."""
        text = "Hello! How can I help you today?"
        assert clean_response(text) == text

    def test_empty_string(self):
        assert clean_response("") == ""

    def test_none_like_empty(self):
        assert clean_response("   ") == "   "

    def test_entire_response_json_with_message(self):
        """When entire response is JSON with a message field, extract it."""
        response = '{"message": "Your meeting has been scheduled for 3 PM."}'
        assert clean_response(response) == "Your meeting has been scheduled for 3 PM."

    def test_entire_response_json_with_content(self):
        response = '{"content": "Here is your summary.", "status": "ok"}'
        assert clean_response(response) == "Here is your summary."

    def test_entire_response_json_with_text(self):
        response = '{"text": "Done! I sent the email.", "email_id": "123"}'
        assert clean_response(response) == "Done! I sent the email."

    def test_entire_response_json_with_response_field(self):
        response = '{"response": "I found 3 contacts matching your query."}'
        assert clean_response(response) == "I found 3 contacts matching your query."

    def test_entire_response_json_no_message_field(self):
        """JSON without a known message field should return original."""
        response = '{"id": 123, "status": "ok"}'
        assert clean_response(response) == response

    def test_json_code_block_entire_response(self):
        """A response that's entirely a JSON code block with a message field."""
        response = '```json\n{"message": "Meeting created successfully."}\n```'
        assert clean_response(response) == "Meeting created successfully."

    def test_json_code_block_in_mixed_content(self):
        """JSON code blocks should be stripped from mixed content."""
        response = 'Here is what I found:\n\n```json\n{"events": [1, 2, 3]}\n```\n\nYou have 3 events today.'
        cleaned = clean_response(response)
        assert '```' not in cleaned
        assert 'events' not in cleaned
        assert 'Here is what I found' in cleaned
        assert 'You have 3 events today' in cleaned

    def test_standalone_json_in_mixed_content(self):
        """Standalone JSON objects should be stripped from mixed content."""
        response = 'I scheduled your meeting.\n{"event_id": "abc123", "status": "created"}\nAnything else?'
        cleaned = clean_response(response)
        assert 'event_id' not in cleaned
        assert 'I scheduled your meeting' in cleaned
        assert 'Anything else?' in cleaned

    def test_nested_message_field(self):
        """Should find message in nested dict."""
        response = '{"data": {"message": "Nested message here"}, "status": "ok"}'
        assert clean_response(response) == "Nested message here"

    def test_multiline_natural_language(self):
        """Multi-line natural language should pass through."""
        text = "Here are your tasks:\n1. Buy groceries\n2. Call dentist\n3. Review report"
        assert clean_response(text) == text

    def test_json_like_but_not_json(self):
        """Text that looks like JSON but isn't should pass through."""
        text = "The format is {name: value} for each entry."
        assert clean_response(text) == text

    def test_multiple_json_code_blocks(self):
        """Multiple JSON code blocks should all be removed."""
        response = (
            'First result:\n```json\n{"a": 1}\n```\n'
            'Second result:\n```json\n{"b": 2}\n```\n'
            'That\'s all!'
        )
        cleaned = clean_response(response)
        assert '```' not in cleaned
        assert 'That\'s all!' in cleaned

    def test_priority_of_message_fields(self):
        """'message' field should be preferred over 'text'."""
        response = '{"message": "Primary", "text": "Secondary"}'
        assert clean_response(response) == "Primary"

    def test_cleaning_does_not_remove_all_content(self):
        """If cleaning would remove everything, return original."""
        # A standalone JSON array with no surrounding text
        response = '[1, 2, 3]'
        result = clean_response(response)
        # Should return original since it's JSON with no extractable message
        assert result == response
