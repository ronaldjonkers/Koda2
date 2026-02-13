"""Tests for the central orchestrator."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.llm.models import LLMResponse


@pytest.fixture
def mock_settings():
    """Mock settings for orchestrator."""
    with patch("koda2.config.get_settings") as mock:
        s = MagicMock()
        s.openai_api_key = "sk-test"
        s.anthropic_api_key = ""
        s.google_ai_api_key = ""
        s.openrouter_api_key = ""
        s.llm_default_provider = "openai"
        s.llm_default_model = "gpt-4o"
        s.koda2_env = "test"
        s.koda2_log_level = "WARNING"
        s.koda2_secret_key = "test"
        s.koda2_encryption_key = ""
        s.database_url = "sqlite+aiosqlite:///:memory:"
        s.chroma_persist_dir = "/tmp/koda2_test_orch"
        s.redis_url = ""
        s.telegram_bot_token = ""
        s.telegram_allowed_user_ids = ""
        s.whatsapp_enabled = False
        s.whatsapp_bridge_port = 3001
        s.api_port = 8000
        s.imap_server = ""
        s.imap_username = ""
        s.smtp_server = ""
        s.smtp_username = ""
        s.google_credentials_file = "nonexistent.json"
        s.google_token_file = "nonexistent.json"
        s.ews_server = ""
        s.ews_username = ""
        s.ews_password = ""
        s.ews_email = ""
        s.msgraph_client_id = ""
        s.msgraph_client_secret = ""
        s.msgraph_tenant_id = ""
        s.caldav_url = ""
        s.caldav_username = ""
        s.caldav_password = ""
        s.image_provider = "openai"
        s.stability_api_key = ""
        s.allowed_telegram_ids = []
        s.has_provider.side_effect = lambda p: p == "openai"
        mock.return_value = s
        yield s


class TestOrchestrator:
    """Tests for the Orchestrator class."""

    @pytest.fixture
    def orchestrator(self, mock_settings, tmp_path):
        """Create an orchestrator with mocked dependencies."""
        with patch("koda2.modules.memory.vector_store.get_chroma_client"), \
             patch("koda2.modules.memory.vector_store.get_collection") as mock_col:
            mock_collection = MagicMock()
            mock_collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]]}
            mock_collection.count.return_value = 0
            mock_col.return_value = mock_collection

            from koda2.orchestrator import Orchestrator
            orch = Orchestrator()

            orch.llm.complete = AsyncMock(return_value=LLMResponse(
                content="Hello! How can I help you today?",
                provider="openai",
                model="gpt-4o",
                prompt_tokens=50,
                completion_tokens=30,
                total_tokens=80,
                finish_reason="stop",
                tool_calls=None,
            ))

            orch.memory.add_conversation = AsyncMock()
            orch.memory.get_recent_conversations = AsyncMock(return_value=[])
            orch.memory.recall = MagicMock(return_value=[])
            orch.memory.store_memory = AsyncMock(return_value=MagicMock(id="mem1"))

            return orch

    @pytest.mark.asyncio
    async def test_process_message_general_chat(self, orchestrator) -> None:
        """General chat messages return a response."""
        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Hello!", "api")
        assert "response" in result
        assert result["tokens_used"] == 80
        assert result["iterations"] == 1

    @pytest.mark.asyncio
    async def test_process_message_stores_conversation(self, orchestrator) -> None:
        """Messages are stored in conversation history."""
        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            await orchestrator.process_message("user1", "Test message", "telegram")
        orchestrator.memory.add_conversation.assert_called()
        calls = orchestrator.memory.add_conversation.call_args_list
        assert calls[0].args[1] == "user"
        assert calls[0].args[2] == "Test message"

    @pytest.mark.asyncio
    async def test_process_message_with_tool_call(self, orchestrator) -> None:
        """Messages that trigger tool calls execute them and loop back."""
        # First call: LLM returns a tool call
        # Second call: LLM returns final text after seeing tool result
        orchestrator.llm.complete = AsyncMock(side_effect=[
            LLMResponse(
                content="",
                provider="openai",
                model="gpt-4o",
                prompt_tokens=50,
                completion_tokens=30,
                total_tokens=80,
                finish_reason="tool_calls",
                tool_calls=[{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "search_memory", "arguments": '{"query": "meetings"}'},
                }],
            ),
            LLMResponse(
                content="I found some meetings in your memory.",
                provider="openai",
                model="gpt-4o",
                prompt_tokens=80,
                completion_tokens=20,
                total_tokens=100,
                finish_reason="stop",
                tool_calls=None,
            ),
        ])

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Search my memories for meetings")
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool"] == "search_memory"
        assert result["iterations"] == 2

    @pytest.mark.asyncio
    async def test_process_message_llm_failure(self, orchestrator) -> None:
        """LLM failure returns graceful error."""
        orchestrator.llm.complete = AsyncMock(side_effect=RuntimeError("All providers failed"))

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Hello!")
        assert "error" in result
        assert "trouble" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_process_message_plain_text_response(self, orchestrator) -> None:
        """Plain text LLM response (no tool calls) is returned directly."""
        orchestrator.llm.complete = AsyncMock(return_value=LLMResponse(
            content="Just a plain text answer.",
            provider="openai",
            model="gpt-4o",
            prompt_tokens=10,
            completion_tokens=10,
            total_tokens=20,
            finish_reason="stop",
            tool_calls=None,
        ))

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Hi")
        assert result["response"] == "Just a plain text answer."
        assert result["iterations"] == 1

    def test_parse_llm_response_valid_json(self, orchestrator) -> None:
        """Valid JSON is parsed correctly."""
        content = json.dumps({"intent": "schedule_meeting", "response": "OK", "entities": {}, "actions": []})
        parsed = orchestrator._parse_llm_response(content)
        assert parsed["intent"] == "schedule_meeting"

    def test_parse_llm_response_code_block(self, orchestrator) -> None:
        """JSON wrapped in code blocks is parsed."""
        content = "```json\n" + json.dumps({"intent": "test", "response": "hi", "entities": {}, "actions": []}) + "\n```"
        parsed = orchestrator._parse_llm_response(content)
        assert parsed["intent"] == "test"

    def test_parse_llm_response_invalid_json(self, orchestrator) -> None:
        """Invalid JSON falls back to general_chat."""
        parsed = orchestrator._parse_llm_response("This is not JSON at all")
        assert parsed["intent"] == "general_chat"
        assert "This is not JSON" in parsed["response"]

    @pytest.mark.asyncio
    async def test_execute_action_unknown(self, orchestrator) -> None:
        """Unknown actions return unknown status."""
        result = await orchestrator._execute_action("user1", {"action": "fly_to_moon"}, {})
        assert result["status"] == "unknown_action"

    @pytest.mark.asyncio
    async def test_execute_action_check_calendar(self, orchestrator) -> None:
        """check_calendar action queries the calendar service."""
        orchestrator.calendar.list_events = AsyncMock(return_value=[])
        result = await orchestrator._execute_action(
            "user1",
            {"action": "check_calendar", "params": {"start": "2026-02-12T00:00:00", "end": "2026-02-13T00:00:00"}},
            {},
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_execute_action_find_contact(self, orchestrator) -> None:
        """find_contact action queries macOS contacts."""
        orchestrator.macos.find_contact = AsyncMock(return_value={"name": "John", "emails": ["john@test.com"]})
        result = await orchestrator._execute_action(
            "user1",
            {"action": "find_contact", "params": {"name": "John"}},
            {},
        )
        assert result["name"] == "John"

    @pytest.mark.asyncio
    async def test_execute_action_generate_image(self, orchestrator) -> None:
        """generate_image action calls the image service."""
        orchestrator.images.generate = AsyncMock(return_value=["https://img.example.com/1.png"])
        result = await orchestrator._execute_action(
            "user1",
            {"action": "generate_image", "params": {"prompt": "sunset"}},
            {},
        )
        assert "images" in result

    @pytest.mark.asyncio
    async def test_execute_action_send_email(self, orchestrator) -> None:
        """send_email action calls the email service."""
        orchestrator.email.send_email = AsyncMock(return_value=True)
        result = await orchestrator._execute_action(
            "user1",
            {"action": "send_email", "params": {"subject": "Test", "to": ["a@b.com"], "body": "Hi"}},
            {},
        )
        assert result["sent"] is True

    @pytest.mark.asyncio
    async def test_execute_action_read_email(self, orchestrator) -> None:
        """read_email action fetches emails."""
        orchestrator.email.fetch_emails = AsyncMock(return_value=[])
        result = await orchestrator._execute_action(
            "user1",
            {"action": "read_email", "params": {"unread_only": True, "limit": 5}},
            {},
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_execute_action_create_reminder(self, orchestrator) -> None:
        """create_reminder action calls macOS service."""
        orchestrator.macos.create_reminder = AsyncMock(return_value="Reminder created: Test")
        result = await orchestrator._execute_action(
            "user1",
            {"action": "create_reminder", "params": {"title": "Test"}},
            {},
        )
        assert "Reminder" in result

    @pytest.mark.asyncio
    async def test_execute_action_build_capability(self, orchestrator) -> None:
        """build_capability action triggers self-improvement."""
        orchestrator.self_improve.generate_plugin = AsyncMock(return_value="/plugins/test.py")
        result = await orchestrator._execute_action(
            "user1",
            {"action": "build_capability", "params": {"capability": "translate", "description": "Translate text"}},
            {},
        )
        assert result["status"] == "generated"
