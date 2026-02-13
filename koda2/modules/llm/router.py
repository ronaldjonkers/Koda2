"""LLM Router — intelligent provider selection with fallback."""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.llm.models import (
    ChatMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    TASK_MODEL_MAP,
)
from koda2.modules.llm.providers import (
    AnthropicProvider,
    BaseLLMProvider,
    GoogleProvider,
    OpenAIProvider,
    OpenRouterProvider,
)

logger = get_logger(__name__)


# Provider cooldown after failure (seconds) — inspired by OpenClaw auth-profiles
PROVIDER_COOLDOWN_SECONDS = 60


class LLMRouter:
    """Routes LLM requests to the optimal provider with automatic fallback."""

    def __init__(self) -> None:
        self._providers: dict[LLMProvider, BaseLLMProvider] = {
            LLMProvider.OPENAI: OpenAIProvider(),
            LLMProvider.ANTHROPIC: AnthropicProvider(),
            LLMProvider.GOOGLE: GoogleProvider(),
            LLMProvider.OPENROUTER: OpenRouterProvider(),
        }
        self._settings = get_settings()
        # Track provider failures for cooldown
        self._cooldowns: dict[LLMProvider, float] = {}

    @property
    def available_providers(self) -> list[LLMProvider]:
        """List providers with valid credentials."""
        return [p for p, impl in self._providers.items() if impl.is_available()]

    def _is_in_cooldown(self, provider: LLMProvider) -> bool:
        """Check if a provider is in cooldown after a recent failure."""
        cooldown_until = self._cooldowns.get(provider, 0)
        return time.monotonic() < cooldown_until

    def _mark_failed(self, provider: LLMProvider) -> None:
        """Put a provider in cooldown after failure."""
        self._cooldowns[provider] = time.monotonic() + PROVIDER_COOLDOWN_SECONDS
        logger.warning("llm_provider_cooldown", provider=provider.value, seconds=PROVIDER_COOLDOWN_SECONDS)

    def _mark_success(self, provider: LLMProvider) -> None:
        """Clear cooldown on success."""
        self._cooldowns.pop(provider, None)

    def _get_fallback_order(self, preferred: LLMProvider) -> list[LLMProvider]:
        """Build fallback chain, deprioritizing cooled-down providers."""
        available = []
        cooled_down = []
        for p in [preferred] + [x for x in LLMProvider if x != preferred]:
            if not self._providers[p].is_available():
                continue
            if p in available or p in cooled_down:
                continue
            if self._is_in_cooldown(p):
                cooled_down.append(p)
            else:
                available.append(p)
        # Try non-cooled-down first, then cooled-down as last resort
        return available + cooled_down

    def select_model(
        self,
        provider: LLMProvider,
        complexity: str = "standard",
    ) -> str:
        """Select the optimal model for a given task complexity."""
        return TASK_MODEL_MAP.get(complexity, TASK_MODEL_MAP["standard"]).get(
            provider.value, "gpt-4o"
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Route a completion request with automatic fallback on failure."""
        provider = request.provider or LLMProvider(self._settings.llm_default_provider)
        model = request.model or self._settings.llm_default_model
        fallback_chain = self._get_fallback_order(provider)

        last_error: Optional[Exception] = None
        for p in fallback_chain:
            impl = self._providers[p]
            if not impl.is_available():
                continue
            try:
                current_model = model if p == provider else self.select_model(p)
                response = await impl.complete(
                    messages=request.messages,
                    model=current_model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    system_prompt=request.system_prompt,
                    tools=request.tools,
                )
                self._mark_success(p)
                if p != provider:
                    logger.warning("llm_fallback_used", original=provider, fallback=p)
                logger.info(
                    "llm_completion",
                    provider=p,
                    model=current_model,
                    tokens=response.total_tokens,
                    cost=f"${response.estimated_cost:.6f}",
                )
                return response
            except Exception as exc:
                last_error = exc
                self._mark_failed(p)
                logger.error("llm_provider_failed", provider=p, error=str(exc))

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream a completion with fallback."""
        provider = request.provider or LLMProvider(self._settings.llm_default_provider)
        model = request.model or self._settings.llm_default_model
        fallback_chain = self._get_fallback_order(provider)

        last_error: Optional[Exception] = None
        for p in fallback_chain:
            impl = self._providers[p]
            if not impl.is_available():
                continue
            try:
                current_model = model if p == provider else self.select_model(p)
                async for chunk in impl.stream(
                    messages=request.messages,
                    model=current_model,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    system_prompt=request.system_prompt,
                ):
                    yield chunk
                return
            except Exception as exc:
                last_error = exc
                logger.error("llm_stream_failed", provider=p, error=str(exc))

        raise RuntimeError(f"All LLM providers failed for streaming. Last error: {last_error}")

    async def quick(self, prompt: str, system: str = "", complexity: str = "simple") -> str:
        """Convenience method for quick single-turn completions."""
        provider = LLMProvider(self._settings.llm_default_provider)
        model = self.select_model(provider, complexity)
        request = LLMRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            provider=provider,
            model=model,
            system_prompt=system or None,
        )
        response = await self.complete(request)
        return response.content
