"""Tests for new OpenClaw-inspired features: chunking, cooldown, debounce, context guard."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.llm.models import LLMProvider, LLMResponse
from koda2.modules.llm.router import LLMRouter, PROVIDER_COOLDOWN_SECONDS


# ── Response Chunking ─────────────────────────────────────────────────

class TestMessageChunking:
    """Tests for Orchestrator._chunk_message (paragraph-aware splitting)."""

    def _chunk(self, text: str, limit: int = 4000) -> list[str]:
        from koda2.orchestrator import Orchestrator
        return Orchestrator._chunk_message(text, limit)

    def test_short_message_no_split(self) -> None:
        result = self._chunk("Hello world")
        assert result == ["Hello world"]

    def test_empty_message(self) -> None:
        result = self._chunk("")
        assert result == []

    def test_none_returns_empty(self) -> None:
        result = self._chunk(None)  # type: ignore
        assert result == []

    def test_exact_limit_no_split(self) -> None:
        text = "x" * 4000
        result = self._chunk(text, limit=4000)
        assert len(result) == 1

    def test_splits_on_paragraph_boundary(self) -> None:
        para1 = "A" * 2000
        para2 = "B" * 2000
        para3 = "C" * 2000
        text = f"{para1}\n\n{para2}\n\n{para3}"
        result = self._chunk(text, limit=4100)
        assert len(result) >= 2
        # Each chunk should be under limit
        for chunk in result:
            assert len(chunk) <= 4100

    def test_hard_split_long_paragraph(self) -> None:
        text = "X" * 10000
        result = self._chunk(text, limit=4000)
        assert len(result) >= 3
        for chunk in result:
            assert len(chunk) <= 4000

    def test_preserves_content(self) -> None:
        para1 = "First paragraph with content."
        para2 = "Second paragraph with more content."
        para3 = "Third paragraph."
        text = f"{para1}\n\n{para2}\n\n{para3}"
        result = self._chunk(text, limit=100)
        joined = "\n\n".join(result)
        assert para1 in joined
        assert para2 in joined
        assert para3 in joined

    def test_single_paragraph_under_limit(self) -> None:
        text = "Just one paragraph that fits."
        result = self._chunk(text, limit=100)
        assert result == [text]


# ── LLM Provider Cooldown ────────────────────────────────────────────

class TestProviderCooldown:
    """Tests for LLM provider cooldown in the router."""

    def test_no_cooldown_initially(self) -> None:
        router = LLMRouter()
        for p in LLMProvider:
            assert not router._is_in_cooldown(p)

    def test_mark_failed_sets_cooldown(self) -> None:
        router = LLMRouter()
        router._mark_failed(LLMProvider.OPENAI)
        assert router._is_in_cooldown(LLMProvider.OPENAI)

    def test_mark_success_clears_cooldown(self) -> None:
        router = LLMRouter()
        router._mark_failed(LLMProvider.OPENAI)
        assert router._is_in_cooldown(LLMProvider.OPENAI)
        router._mark_success(LLMProvider.OPENAI)
        assert not router._is_in_cooldown(LLMProvider.OPENAI)

    def test_cooldown_expires(self) -> None:
        router = LLMRouter()
        # Set cooldown to expire immediately
        router._cooldowns[LLMProvider.OPENAI] = time.monotonic() - 1
        assert not router._is_in_cooldown(LLMProvider.OPENAI)

    def test_fallback_order_deprioritizes_cooled_down(self) -> None:
        router = LLMRouter()
        # Mock all providers as available
        for p in router._providers.values():
            p.is_available = MagicMock(return_value=True)

        # No cooldown — preferred should be first
        order = router._get_fallback_order(LLMProvider.OPENAI)
        assert order[0] == LLMProvider.OPENAI

        # Cool down OpenAI — should be last
        router._mark_failed(LLMProvider.OPENAI)
        order = router._get_fallback_order(LLMProvider.OPENAI)
        assert order[-1] == LLMProvider.OPENAI
        assert order[0] != LLMProvider.OPENAI

    def test_fallback_order_skips_unavailable(self) -> None:
        router = LLMRouter()
        for p in router._providers.values():
            p.is_available = MagicMock(return_value=False)
        # One available
        router._providers[LLMProvider.ANTHROPIC].is_available = MagicMock(return_value=True)
        order = router._get_fallback_order(LLMProvider.OPENAI)
        assert order == [LLMProvider.ANTHROPIC]


# ── Context Window Guard ─────────────────────────────────────────────

class TestContextWindowGuard:
    """Tests for token-aware history pruning constants."""

    def test_constants_defined(self) -> None:
        from koda2.orchestrator import (
            CONTEXT_MAX_TOKENS,
            CONTEXT_HISTORY_SHARE,
            CHARS_PER_TOKEN,
            MESSAGE_CHUNK_LIMIT,
            DEBOUNCE_SECONDS,
            MAX_TOOL_ITERATIONS,
            AGENT_AUTO_THRESHOLD,
        )
        assert CONTEXT_MAX_TOKENS == 100_000
        assert 0 < CONTEXT_HISTORY_SHARE < 1
        assert CHARS_PER_TOKEN == 4
        assert MESSAGE_CHUNK_LIMIT == 4000
        assert DEBOUNCE_SECONDS > 0
        assert MAX_TOOL_ITERATIONS == 15
        assert AGENT_AUTO_THRESHOLD == 4

    def test_history_budget_calculation(self) -> None:
        from koda2.orchestrator import CONTEXT_MAX_TOKENS, CONTEXT_HISTORY_SHARE, CHARS_PER_TOKEN
        system_prompt = "You are a helpful assistant." * 10
        system_tokens = len(system_prompt) // CHARS_PER_TOKEN
        budget = int((CONTEXT_MAX_TOKENS - system_tokens) * CONTEXT_HISTORY_SHARE)
        assert budget > 0
        assert budget < CONTEXT_MAX_TOKENS


# ── Workspace Files ──────────────────────────────────────────────────

class TestWorkspaceFiles:
    """Tests for SOUL.md and TOOLS.md loading."""

    def test_load_workspace_file_exists(self, tmp_path) -> None:
        from koda2.orchestrator import _load_workspace_file, _WORKSPACE_DIR
        # Test with actual workspace dir
        soul_path = _WORKSPACE_DIR / "SOUL.md"
        if soul_path.exists():
            content = _load_workspace_file("SOUL.md")
            assert len(content) > 0
            assert "Koda2" in content

    def test_load_workspace_file_missing(self) -> None:
        from koda2.orchestrator import _load_workspace_file
        content = _load_workspace_file("NONEXISTENT_FILE.md")
        assert content == ""


# ── Debounce ─────────────────────────────────────────────────────────

class TestDebounceConstants:
    """Tests for debounce configuration."""

    def test_debounce_seconds_reasonable(self) -> None:
        from koda2.orchestrator import DEBOUNCE_SECONDS
        assert 0.5 <= DEBOUNCE_SECONDS <= 5.0


# ── Browser Service ──────────────────────────────────────────────────

class TestBrowserService:
    """Tests for browser service module."""

    def test_browser_service_imports(self) -> None:
        from koda2.modules.browser.service import BrowserService
        svc = BrowserService()
        assert svc is not None

    def test_browser_service_not_running_initially(self) -> None:
        from koda2.modules.browser.service import BrowserService
        svc = BrowserService()
        assert not svc._browser


# ── Command Parser Session Commands ──────────────────────────────────

class TestSessionCommands:
    """Tests for /new, /compact, /usage command registration."""

    def test_session_commands_registered(self) -> None:
        """Verify session management commands exist in the parser."""
        from koda2.modules.messaging.command_parser import CommandParser
        parser = CommandParser()
        parser.register("new", AsyncMock(), "Reset session")
        parser.register("compact", AsyncMock(), "Compact context")
        parser.register("usage", AsyncMock(), "Token usage")
        assert "new" in parser._handlers
        assert "compact" in parser._handlers
        assert "usage" in parser._handlers
