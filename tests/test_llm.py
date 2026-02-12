"""Tests for the LLM router and provider abstraction."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.llm.models import (
    ChatMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    TASK_MODEL_MAP,
)
from koda2.modules.llm.providers import OpenAIProvider, AnthropicProvider
from koda2.modules.llm.router import LLMRouter


class TestLLMModels:
    """Tests for LLM data models."""

    def test_llm_response_cost_estimation(self) -> None:
        """Cost estimation works for known models."""
        resp = LLMResponse(
            content="test",
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        cost = resp.estimated_cost
        assert cost > 0
        assert isinstance(cost, float)

    def test_llm_response_unknown_model_cost(self) -> None:
        """Unknown models get default cost rates."""
        resp = LLMResponse(
            content="test",
            model="unknown-model",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        assert resp.estimated_cost > 0

    def test_task_model_map_has_all_complexities(self) -> None:
        """TASK_MODEL_MAP has entries for simple, standard, complex."""
        assert "simple" in TASK_MODEL_MAP
        assert "standard" in TASK_MODEL_MAP
        assert "complex" in TASK_MODEL_MAP

    def test_chat_message_defaults(self) -> None:
        """ChatMessage has sensible defaults."""
        msg = ChatMessage(content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_llm_request_defaults(self) -> None:
        """LLMRequest has proper defaults."""
        req = LLMRequest(messages=[ChatMessage(content="Hi")])
        assert req.temperature == 0.7
        assert req.max_tokens == 4096
        assert req.stream is False


class TestOpenAIProvider:
    """Tests for the OpenAI provider."""

    def test_is_available_with_key(self) -> None:
        """Provider reports available when API key is set."""
        with patch("koda2.modules.llm.providers.get_settings") as mock:
            mock.return_value = MagicMock(openai_api_key="sk-test")
            provider = OpenAIProvider()
            assert provider.is_available() is True

    def test_is_not_available_without_key(self) -> None:
        """Provider reports unavailable when API key is empty."""
        with patch("koda2.modules.llm.providers.get_settings") as mock:
            mock.return_value = MagicMock(openai_api_key="")
            provider = OpenAIProvider()
            assert provider.is_available() is False

    @pytest.mark.asyncio
    async def test_complete(self, mock_openai) -> None:
        """OpenAI completion returns proper LLMResponse."""
        with patch("koda2.modules.llm.providers.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(openai_api_key="sk-test")
            provider = OpenAIProvider()
            response = await provider.complete(
                messages=[ChatMessage(content="Hello")],
                model="gpt-4o",
            )
            assert isinstance(response, LLMResponse)
            assert response.provider == LLMProvider.OPENAI
            assert response.total_tokens == 30


class TestAnthropicProvider:
    """Tests for the Anthropic provider."""

    def test_is_available_with_key(self) -> None:
        """Provider reports available when API key is set."""
        with patch("koda2.modules.llm.providers.get_settings") as mock:
            mock.return_value = MagicMock(anthropic_api_key="sk-ant-test")
            provider = AnthropicProvider()
            assert provider.is_available() is True

    @pytest.mark.asyncio
    async def test_complete(self, mock_anthropic) -> None:
        """Anthropic completion returns proper LLMResponse."""
        with patch("koda2.modules.llm.providers.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(anthropic_api_key="sk-ant-test")
            provider = AnthropicProvider()
            response = await provider.complete(
                messages=[ChatMessage(content="Hello")],
                model="claude-3-5-sonnet-20241022",
            )
            assert isinstance(response, LLMResponse)
            assert response.provider == LLMProvider.ANTHROPIC


class TestLLMRouter:
    """Tests for the LLM router."""

    def test_available_providers(self) -> None:
        """Router lists only providers with valid keys."""
        with patch("koda2.modules.llm.providers.get_settings") as mock:
            mock.return_value = MagicMock(
                openai_api_key="sk-test",
                anthropic_api_key="",
                google_ai_api_key="",
                openrouter_api_key="",
                llm_default_provider="openai",
                llm_default_model="gpt-4o",
            )
            router = LLMRouter()
            available = router.available_providers
            assert LLMProvider.OPENAI in available
            assert LLMProvider.ANTHROPIC not in available

    def test_select_model(self) -> None:
        """select_model returns appropriate model for complexity."""
        with patch("koda2.modules.llm.providers.get_settings") as mock:
            mock.return_value = MagicMock(
                openai_api_key="sk-test",
                anthropic_api_key="",
                google_ai_api_key="",
                openrouter_api_key="",
                llm_default_provider="openai",
                llm_default_model="gpt-4o",
            )
            router = LLMRouter()
            simple_model = router.select_model(LLMProvider.OPENAI, "simple")
            assert "mini" in simple_model
            standard_model = router.select_model(LLMProvider.OPENAI, "standard")
            assert "gpt-4o" in standard_model

    @pytest.mark.asyncio
    async def test_complete_with_fallback(self, mock_openai) -> None:
        """Router falls back to next provider on failure."""
        with patch("koda2.modules.llm.providers.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openai_api_key="sk-test",
                anthropic_api_key="",
                google_ai_api_key="",
                openrouter_api_key="",
                llm_default_provider="openai",
                llm_default_model="gpt-4o",
            )
            router = LLMRouter()
            request = LLMRequest(messages=[ChatMessage(content="Hello")])
            response = await router.complete(request)
            assert response.content is not None

    @pytest.mark.asyncio
    async def test_quick_method(self, mock_openai) -> None:
        """Quick convenience method works."""
        with patch("koda2.modules.llm.providers.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                openai_api_key="sk-test",
                anthropic_api_key="",
                google_ai_api_key="",
                openrouter_api_key="",
                llm_default_provider="openai",
                llm_default_model="gpt-4o",
            )
            router = LLMRouter()
            result = await router.quick("Hello")
            assert isinstance(result, str)
