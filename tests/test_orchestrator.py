"""Tests for the central orchestrator — agent loop architecture (v0.3.0)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.llm.models import ChatMessage, LLMResponse


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


def _make_text_response(content: str, tokens: int = 80) -> LLMResponse:
    """Helper: create a plain-text LLM response (no tool calls)."""
    return LLMResponse(
        content=content,
        provider="openai",
        model="gpt-4o",
        prompt_tokens=tokens // 2,
        completion_tokens=tokens // 2,
        total_tokens=tokens,
        finish_reason="stop",
        tool_calls=None,
    )


def _make_tool_response(tool_calls: list[dict], content: str = "", tokens: int = 80) -> LLMResponse:
    """Helper: create an LLM response with tool calls."""
    return LLMResponse(
        content=content,
        provider="openai",
        model="gpt-4o",
        prompt_tokens=tokens // 2,
        completion_tokens=tokens // 2,
        total_tokens=tokens,
        finish_reason="tool_calls",
        tool_calls=tool_calls,
    )


class TestAgentLoop:
    """Tests for the process_message agent loop."""

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

            orch.llm.complete = AsyncMock(return_value=_make_text_response("Hello!"))
            orch.memory.add_conversation = AsyncMock()
            orch.memory.get_recent_conversations = AsyncMock(return_value=[])
            orch.memory.recall = MagicMock(return_value=[])
            orch.memory.store_memory = AsyncMock(return_value=MagicMock(id="mem1"))

            return orch

    @pytest.mark.asyncio
    async def test_simple_chat_no_tools(self, orchestrator) -> None:
        """Simple chat returns text directly, 1 iteration, no tool calls."""
        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Hello!", "api")
        assert result["response"] == "Hello!"
        assert result["iterations"] == 1
        assert result["tool_calls"] == []
        assert result["tokens_used"] == 80

    @pytest.mark.asyncio
    async def test_stores_user_and_assistant_messages(self, orchestrator) -> None:
        """Both user and assistant messages are stored in memory."""
        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            await orchestrator.process_message("user1", "Test", "telegram")
        calls = orchestrator.memory.add_conversation.call_args_list
        assert len(calls) == 2
        assert calls[0].args[1] == "user"
        assert calls[0].args[2] == "Test"
        assert calls[1].args[1] == "assistant"

    @pytest.mark.asyncio
    async def test_single_tool_call_loop(self, orchestrator) -> None:
        """LLM calls one tool, sees result, then responds with text."""
        orchestrator.llm.complete = AsyncMock(side_effect=[
            _make_tool_response([{
                "id": "call_1",
                "type": "function",
                "function": {"name": "search_memory", "arguments": '{"query": "meetings"}'},
            }]),
            _make_text_response("Found 3 meetings.", tokens=60),
        ])

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Search meetings")
        assert result["iterations"] == 2
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["tool"] == "search_memory"
        assert result["tool_calls"][0]["status"] == "success"
        assert result["tokens_used"] == 140

    @pytest.mark.asyncio
    async def test_multi_tool_call_in_one_response(self, orchestrator) -> None:
        """LLM calls multiple tools in a single response (parallel tool calls)."""
        orchestrator.llm.complete = AsyncMock(side_effect=[
            _make_tool_response([
                {"id": "c1", "type": "function", "function": {"name": "check_calendar", "arguments": '{"start": "2026-02-13T00:00:00", "end": "2026-02-14T00:00:00"}'}},
                {"id": "c2", "type": "function", "function": {"name": "read_email", "arguments": '{"unread_only": true}'}},
            ]),
            _make_text_response("You have no events and no unread emails."),
        ])
        orchestrator.calendar.list_events = AsyncMock(return_value=[])
        orchestrator.email.fetch_emails = AsyncMock(return_value=[])

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "What's my day look like?")
        assert result["iterations"] == 2
        assert len(result["tool_calls"]) == 2

    @pytest.mark.asyncio
    async def test_multi_iteration_loop(self, orchestrator) -> None:
        """LLM does multiple iterations: tool → result → tool → result → text."""
        orchestrator.llm.complete = AsyncMock(side_effect=[
            _make_tool_response([{"id": "c1", "type": "function", "function": {"name": "list_directory", "arguments": '{"path": "."}'}}]),
            _make_tool_response([{"id": "c2", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "README.md"}'}}]),
            _make_text_response("The README contains project info."),
        ])
        orchestrator.macos.list_directory = AsyncMock(return_value=["README.md", "setup.py"])
        orchestrator.macos.read_file = AsyncMock(return_value="# Project")

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Read the README")
        assert result["iterations"] == 3
        assert len(result["tool_calls"]) == 2

    @pytest.mark.asyncio
    async def test_tool_execution_error_continues(self, orchestrator) -> None:
        """Tool execution error is fed back to LLM, which can recover."""
        orchestrator.llm.complete = AsyncMock(side_effect=[
            _make_tool_response([{"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": '{"path": "/nonexistent"}'}}]),
            _make_text_response("The file doesn't exist."),
        ])
        orchestrator.macos.read_file = AsyncMock(side_effect=FileNotFoundError("Not found"))

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Read /nonexistent")
        assert result["iterations"] == 2
        assert result["tool_calls"][0]["status"] == "error"
        assert "Not found" in result["tool_calls"][0]["error"]

    @pytest.mark.asyncio
    async def test_llm_failure_returns_error(self, orchestrator) -> None:
        """LLM failure returns graceful error response."""
        orchestrator.llm.complete = AsyncMock(side_effect=RuntimeError("Provider down"))

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Hello!")
        assert "error" in result
        assert "trouble" in result["response"].lower()

    @pytest.mark.asyncio
    async def test_auto_offload_to_agent(self, orchestrator) -> None:
        """>=4 tool calls in first response triggers auto-offload to background agent."""
        from koda2.modules.agent.models import AgentTask, AgentStatus
        mock_task = AgentTask(id="task-123", user_id="user1", original_request="complex", status=AgentStatus.RUNNING)
        orchestrator.agent.create_task = AsyncMock(return_value=mock_task)

        orchestrator.llm.complete = AsyncMock(return_value=_make_tool_response([
            {"id": f"c{i}", "type": "function", "function": {"name": f"tool_{i}", "arguments": "{}"}}
            for i in range(5)
        ]))

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Build a website")
        assert "background" in result["response"].lower() or "agent" in result["response"].lower()
        assert any(tc.get("status") == "auto_offloaded" for tc in result["tool_calls"])
        orchestrator.agent.create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_offload_below_threshold(self, orchestrator) -> None:
        """<4 tool calls in first response runs inline, not offloaded."""
        orchestrator.llm.complete = AsyncMock(side_effect=[
            _make_tool_response([
                {"id": "c1", "type": "function", "function": {"name": "search_memory", "arguments": '{"query": "x"}'}},
                {"id": "c2", "type": "function", "function": {"name": "check_calendar", "arguments": '{"start": "2026-01-01T00:00:00"}'}},
            ]),
            _make_text_response("Done."),
        ])
        orchestrator.calendar.list_events = AsyncMock(return_value=[])

        with patch("koda2.orchestrator.log_action", new_callable=AsyncMock):
            result = await orchestrator.process_message("user1", "Check stuff")
        assert result["iterations"] == 2
        assert not any(tc.get("status") == "auto_offloaded" for tc in result["tool_calls"])


class TestToolDefinitions:
    """Tests for tool definition generation from command registry."""

    @pytest.fixture
    def orchestrator(self, mock_settings):
        with patch("koda2.modules.memory.vector_store.get_chroma_client"), \
             patch("koda2.modules.memory.vector_store.get_collection") as mock_col:
            mock_collection = MagicMock()
            mock_collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]]}
            mock_collection.count.return_value = 0
            mock_col.return_value = mock_collection

            from koda2.orchestrator import Orchestrator
            return Orchestrator()

    def test_tool_definitions_generated(self, orchestrator) -> None:
        """Tool definitions are generated from command registry."""
        tools = orchestrator._get_tool_definitions()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_tool_definitions_openai_format(self, orchestrator) -> None:
        """Each tool follows OpenAI function-calling format."""
        tools = orchestrator._get_tool_definitions()
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            assert func["parameters"]["type"] == "object"

    def test_known_commands_present(self, orchestrator) -> None:
        """Key commands like run_shell, send_email are in tool definitions."""
        tools = orchestrator._get_tool_definitions()
        names = {t["function"]["name"] for t in tools}
        assert "run_shell" in names
        assert "send_email" in names
        assert "check_calendar" in names
        assert "read_file" in names


class TestExecuteAction:
    """Tests for _execute_action (tool execution)."""

    @pytest.fixture
    def orchestrator(self, mock_settings):
        with patch("koda2.modules.memory.vector_store.get_chroma_client"), \
             patch("koda2.modules.memory.vector_store.get_collection") as mock_col:
            mock_collection = MagicMock()
            mock_collection.query.return_value = {"documents": [[]], "metadatas": [[]], "distances": [[]], "ids": [[]]}
            mock_collection.count.return_value = 0
            mock_col.return_value = mock_collection

            from koda2.orchestrator import Orchestrator
            orch = Orchestrator()
            orch.memory.store_memory = AsyncMock(return_value=MagicMock(id="mem1"))
            return orch

    @pytest.mark.asyncio
    async def test_unknown_action(self, orchestrator) -> None:
        """Unknown actions return unknown_action status."""
        result = await orchestrator._execute_action("user1", {"action": "fly_to_moon"}, {})
        assert result["status"] == "unknown_action"

    @pytest.mark.asyncio
    async def test_check_calendar(self, orchestrator) -> None:
        """check_calendar queries the calendar service."""
        orchestrator.calendar.list_events = AsyncMock(return_value=[])
        result = await orchestrator._execute_action(
            "user1",
            {"action": "check_calendar", "params": {"start": "2026-02-12T00:00:00", "end": "2026-02-13T00:00:00"}},
            {},
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_find_contact(self, orchestrator) -> None:
        """find_contact queries macOS contacts."""
        orchestrator.macos.find_contact = AsyncMock(return_value={"name": "John", "emails": ["john@test.com"]})
        result = await orchestrator._execute_action(
            "user1", {"action": "find_contact", "params": {"name": "John"}}, {},
        )
        assert result["name"] == "John"

    @pytest.mark.asyncio
    async def test_generate_image(self, orchestrator) -> None:
        """generate_image calls the image service."""
        orchestrator.images.generate = AsyncMock(return_value=["https://img.example.com/1.png"])
        result = await orchestrator._execute_action(
            "user1", {"action": "generate_image", "params": {"prompt": "sunset"}}, {},
        )
        assert "images" in result

    @pytest.mark.asyncio
    async def test_send_email(self, orchestrator) -> None:
        """send_email calls the email service."""
        orchestrator.email.send_email = AsyncMock(return_value=True)
        result = await orchestrator._execute_action(
            "user1", {"action": "send_email", "params": {"subject": "Test", "to": ["a@b.com"], "body": "Hi"}}, {},
        )
        assert result["sent"] is True

    @pytest.mark.asyncio
    async def test_read_email(self, orchestrator) -> None:
        """read_email fetches emails."""
        orchestrator.email.fetch_emails = AsyncMock(return_value=[])
        result = await orchestrator._execute_action(
            "user1", {"action": "read_email", "params": {"unread_only": True, "limit": 5}}, {},
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_run_shell(self, orchestrator) -> None:
        """run_shell executes shell commands."""
        orchestrator.macos.run_shell = AsyncMock(return_value={"stdout": "hello", "returncode": 0})
        result = await orchestrator._execute_action(
            "user1", {"action": "run_shell", "params": {"command": "echo hello"}}, {},
        )
        assert result["stdout"] == "hello"

    @pytest.mark.asyncio
    async def test_write_file(self, orchestrator) -> None:
        """write_file creates files."""
        orchestrator.macos.write_file = AsyncMock(return_value="/tmp/test.txt")
        result = await orchestrator._execute_action(
            "user1", {"action": "write_file", "params": {"path": "/tmp/test.txt", "content": "hello"}}, {},
        )
        assert result["status"] == "written"

    @pytest.mark.asyncio
    async def test_create_reminder(self, orchestrator) -> None:
        """create_reminder calls macOS service."""
        orchestrator.macos.create_reminder = AsyncMock(return_value="Reminder created: Test")
        result = await orchestrator._execute_action(
            "user1", {"action": "create_reminder", "params": {"title": "Test"}}, {},
        )
        assert "Reminder" in result


class TestChatMessageModel:
    """Tests for the updated ChatMessage model with tool support."""

    def test_basic_message(self) -> None:
        """Basic message has defaults."""
        msg = ChatMessage(content="Hello")
        assert msg.role == "user"
        assert msg.tool_calls is None
        assert msg.tool_call_id is None

    def test_assistant_with_tool_calls(self) -> None:
        """Assistant message can carry tool_calls."""
        msg = ChatMessage(
            role="assistant",
            content="",
            tool_calls=[{"id": "c1", "function": {"name": "test", "arguments": "{}"}}],
        )
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["function"]["name"] == "test"

    def test_tool_result_message(self) -> None:
        """Tool result message has role=tool and tool_call_id."""
        msg = ChatMessage(role="tool", content='{"result": "ok"}', tool_call_id="c1")
        assert msg.role == "tool"
        assert msg.tool_call_id == "c1"
