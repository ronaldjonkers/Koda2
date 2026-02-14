"""Smart Model Router — picks the optimal LLM model per task complexity.

When using OpenRouter, the supervisor selects models based on task type:
- FREE/CHEAP models for: signal analysis, classification, documentation, simple fixes
- MID-TIER models for: error analysis, plan revision, moderate code changes
- TOP-TIER (Claude Sonnet 4) for: complex code generation, self-correction, architecture

This saves costs while ensuring complex tasks get the best model.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import httpx

from koda2.config import get_settings
from koda2.logging_config import get_logger

logger = get_logger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class TaskComplexity(StrEnum):
    """Complexity level for model selection."""

    LIGHT = "light"       # classification, summaries, docs
    MEDIUM = "medium"     # error analysis, plan revision, moderate changes
    HEAVY = "heavy"       # complex code generation, architecture, self-correction


# Model tiers per complexity — OpenRouter model IDs
# Ordered by preference (first available wins)
MODEL_TIERS: dict[TaskComplexity, list[str]] = {
    TaskComplexity.LIGHT: [
        "google/gemini-2.0-flash-001",         # fast, free-tier eligible
        "meta-llama/llama-3.1-8b-instruct",    # free on OpenRouter
        "google/gemma-2-9b-it:free",            # free
        "mistralai/mistral-7b-instruct:free",   # free
    ],
    TaskComplexity.MEDIUM: [
        "anthropic/claude-3.5-haiku-20241022",  # fast + capable
        "google/gemini-2.0-flash-001",          # good balance
        "openai/gpt-4o-mini",                   # affordable
    ],
    TaskComplexity.HEAVY: [
        "anthropic/claude-sonnet-4-20250514",   # best for code
        "anthropic/claude-3.5-sonnet",          # fallback
        "openai/gpt-4o",                        # fallback
    ],
}

# OpenAI fallbacks (when not using OpenRouter)
OPENAI_FALLBACKS: dict[TaskComplexity, str] = {
    TaskComplexity.LIGHT: "gpt-4o-mini",
    TaskComplexity.MEDIUM: "gpt-4o-mini",
    TaskComplexity.HEAVY: "gpt-4o",
}

# Map task descriptions to complexity
TASK_COMPLEXITY_MAP: dict[str, TaskComplexity] = {
    # Light tasks
    "signal_analysis": TaskComplexity.LIGHT,
    "classify_feedback": TaskComplexity.LIGHT,
    "documentation": TaskComplexity.LIGHT,
    "commit_message": TaskComplexity.LIGHT,
    "changelog": TaskComplexity.LIGHT,
    "hygiene_check": TaskComplexity.LIGHT,
    # Medium tasks
    "error_analysis": TaskComplexity.MEDIUM,
    "crash_analysis": TaskComplexity.MEDIUM,
    "plan_revision": TaskComplexity.MEDIUM,
    "simple_fix": TaskComplexity.MEDIUM,
    # Heavy tasks
    "code_generation": TaskComplexity.HEAVY,
    "plan_improvement": TaskComplexity.HEAVY,
    "self_correction": TaskComplexity.HEAVY,
    "feature_implementation": TaskComplexity.HEAVY,
    "architecture": TaskComplexity.HEAVY,
    "repair": TaskComplexity.HEAVY,
}


def get_complexity(task_type: str) -> TaskComplexity:
    """Determine complexity from a task type string."""
    return TASK_COMPLEXITY_MAP.get(task_type, TaskComplexity.MEDIUM)


def select_model(task_type: str) -> tuple[str, str, TaskComplexity]:
    """Select the best model for a given task type.

    Returns:
        (url, model_id, complexity)
    """
    settings = get_settings()
    api_key = settings.openrouter_api_key or settings.openai_api_key or ""
    complexity = get_complexity(task_type)

    if api_key.startswith("sk-or-"):
        # OpenRouter — pick from tier
        models = MODEL_TIERS[complexity]
        model = models[0]  # Use first preference
        return OPENROUTER_URL, model, complexity
    else:
        # Direct OpenAI
        model = OPENAI_FALLBACKS[complexity]
        return "https://api.openai.com/v1/chat/completions", model, complexity


async def call_llm(
    system: str,
    user: str,
    task_type: str = "code_generation",
    *,
    temperature: float = 0.3,
    max_tokens: int = 16000,
    timeout: int = 120,
) -> str:
    """Call the LLM with smart model routing.

    Args:
        system: System prompt
        user: User prompt
        task_type: Task type for model selection (see TASK_COMPLEXITY_MAP)
        temperature: LLM temperature
        max_tokens: Max output tokens
        timeout: HTTP timeout in seconds

    Returns:
        LLM response text
    """
    settings = get_settings()
    api_key = settings.openrouter_api_key or settings.openai_api_key
    if not api_key:
        raise RuntimeError("No API key for supervisor LLM (need OPENROUTER_API_KEY or OPENAI_API_KEY)")

    url, model, complexity = select_model(task_type)

    logger.info(
        "supervisor_llm_call",
        task_type=task_type,
        complexity=complexity.value,
        model=model,
    )

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        if resp.status_code != 200:
            body = resp.text[:500]
            logger.error("supervisor_llm_failed", status=resp.status_code, body=body, model=model)
            resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Log token usage if available
        usage = data.get("usage", {})
        if usage:
            logger.info(
                "supervisor_llm_usage",
                model=model,
                task_type=task_type,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )

        return content
