"""Data models for the LLM abstraction layer."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


class LLMProvider(StrEnum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENROUTER = "openrouter"


class ChatMessage(BaseModel):
    """A single message in a conversation."""

    role: str = "user"
    content: str = ""
    name: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class LLMRequest(BaseModel):
    """Unified request model across all LLM providers."""

    messages: list[ChatMessage]
    provider: Optional[LLMProvider] = None
    model: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = False
    system_prompt: Optional[str] = None
    tools: Optional[list[dict[str, Any]]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Unified response model from any LLM provider."""

    content: str = ""
    provider: LLMProvider = LLMProvider.OPENAI
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    tool_calls: Optional[list[dict[str, Any]]] = None
    raw: Optional[dict[str, Any]] = None

    @property
    def estimated_cost(self) -> float:
        """Rough cost estimate in USD based on token counts."""
        cost_per_1k: dict[str, tuple[float, float]] = {
            # OpenAI
            "gpt-4o": (0.0025, 0.01),
            "gpt-4o-mini": (0.00015, 0.0006),
            "gpt-4-turbo": (0.01, 0.03),
            # Anthropic (direct API)
            "claude-sonnet-4-20250514": (0.003, 0.015),
            "claude-3-5-sonnet-20241022": (0.003, 0.015),
            "claude-3-5-haiku-20241022": (0.0008, 0.004),
            "claude-3-haiku-20240307": (0.00025, 0.00125),
            # Legacy short names (for backward compat)
            "claude-3-5-sonnet": (0.003, 0.015),
            "claude-3-haiku": (0.00025, 0.00125),
            # Google
            "gemini-1.5-pro": (0.00125, 0.005),
            "gemini-1.5-flash": (0.000075, 0.0003),
            "gemini-2.0-flash": (0.000075, 0.0003),
        }
        rates = cost_per_1k.get(self.model, (0.001, 0.002))
        return (self.prompt_tokens / 1000 * rates[0]) + (self.completion_tokens / 1000 * rates[1])


# Model recommendations per task complexity
TASK_MODEL_MAP: dict[str, dict[str, str]] = {
    "simple": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-haiku-20241022",
        "google": "gemini-2.0-flash",
        "openrouter": "google/gemini-2.0-flash-001",
    },
    "standard": {
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-20250514",
        "google": "gemini-1.5-pro",
        "openrouter": "anthropic/claude-sonnet-4-20250514",
    },
    "complex": {
        "openai": "gpt-4o",
        "anthropic": "claude-sonnet-4-20250514",
        "google": "gemini-1.5-pro",
        "openrouter": "anthropic/claude-sonnet-4-20250514",
    },
}
