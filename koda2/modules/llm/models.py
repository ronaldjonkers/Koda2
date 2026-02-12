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
            "gpt-4o": (0.0025, 0.01),
            "gpt-4o-mini": (0.00015, 0.0006),
            "gpt-4-turbo": (0.01, 0.03),
            "claude-3-5-sonnet": (0.003, 0.015),
            "claude-3-haiku": (0.00025, 0.00125),
            "gemini-1.5-pro": (0.00125, 0.005),
            "gemini-1.5-flash": (0.000075, 0.0003),
        }
        rates = cost_per_1k.get(self.model, (0.001, 0.002))
        return (self.prompt_tokens / 1000 * rates[0]) + (self.completion_tokens / 1000 * rates[1])


# Model recommendations per task complexity
TASK_MODEL_MAP: dict[str, dict[str, str]] = {
    "simple": {
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku-20241022",
        "google": "gemini-1.5-flash",
        "openrouter": "meta-llama/llama-3.1-8b-instruct",
    },
    "standard": {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
        "google": "gemini-1.5-pro",
        "openrouter": "anthropic/claude-3.5-sonnet",
    },
    "complex": {
        "openai": "gpt-4o",
        "anthropic": "claude-3-5-sonnet-20241022",
        "google": "gemini-1.5-pro",
        "openrouter": "anthropic/claude-3.5-sonnet",
    },
}
