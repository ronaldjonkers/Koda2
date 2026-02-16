"""Smart Model Router — picks the optimal LLM model per task complexity.

Supports four backends (checked in order):
1. **OpenRouter** — multi-model gateway with free/cheap tiers
2. **Anthropic direct** — native Claude API (claude-sonnet-4, claude-3.5-haiku)
3. **Google Gemini direct** — native Gemini API (gemini-2.0-flash, gemini-1.5-pro)
4. **OpenAI direct** — GPT-4o / GPT-4o-mini fallback

Model selection per task type:
- LIGHT (free/cheap): signal analysis, classification, documentation, simple fixes
- MEDIUM: error analysis, plan revision, moderate code changes
- HEAVY (Claude Sonnet 4): complex code generation, self-correction, architecture
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
        "anthropic/claude-3-5-haiku-20241022",  # fast + capable
        "google/gemini-2.0-flash-001",          # good balance
        "openai/gpt-4o-mini",                   # affordable
    ],
    TaskComplexity.HEAVY: [
        "anthropic/claude-sonnet-4-20250514",   # best for code
        "anthropic/claude-3-5-sonnet-20241022", # fallback
        "openai/gpt-4o",                        # fallback
    ],
}

# Anthropic direct API model mapping (when using ANTHROPIC_API_KEY)
ANTHROPIC_MODELS: dict[TaskComplexity, str] = {
    TaskComplexity.LIGHT: "claude-3-5-haiku-20241022",
    TaskComplexity.MEDIUM: "claude-3-5-haiku-20241022",
    TaskComplexity.HEAVY: "claude-sonnet-4-20250514",
}

# OpenAI fallbacks (when not using OpenRouter or Anthropic)
OPENAI_FALLBACKS: dict[TaskComplexity, str] = {
    TaskComplexity.LIGHT: "gpt-4o-mini",
    TaskComplexity.MEDIUM: "gpt-4o-mini",
    TaskComplexity.HEAVY: "gpt-4o",
}

# Google Gemini direct API model mapping (when using GOOGLE_AI_API_KEY)
GOOGLE_MODELS: dict[TaskComplexity, str] = {
    TaskComplexity.LIGHT: "gemini-2.0-flash",
    TaskComplexity.MEDIUM: "gemini-2.0-flash",
    TaskComplexity.HEAVY: "gemini-1.5-pro",
}

# Backend type returned by select_model
BACKEND_OPENROUTER = "openrouter"
BACKEND_ANTHROPIC = "anthropic"
BACKEND_GOOGLE = "google"
BACKEND_OPENAI = "openai"

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

    Checks API keys in order: OpenRouter → Anthropic → Google → OpenAI.

    Returns:
        (url_or_backend, model_id, complexity)
        For OpenRouter/OpenAI: url is the full API endpoint.
        For Anthropic/Google: url is the backend constant (uses SDK).
    """
    settings = get_settings()
    complexity = get_complexity(task_type)

    # Priority 1: OpenRouter (multi-model gateway)
    if settings.openrouter_api_key:
        models = MODEL_TIERS[complexity]
        model = models[0]
        return OPENROUTER_URL, model, complexity

    # Priority 2: Anthropic direct API (native Claude SDK)
    if settings.anthropic_api_key:
        model = ANTHROPIC_MODELS[complexity]
        return BACKEND_ANTHROPIC, model, complexity

    # Priority 3: Google Gemini direct API (native google-genai SDK)
    if settings.google_ai_api_key:
        model = GOOGLE_MODELS[complexity]
        return BACKEND_GOOGLE, model, complexity

    # Priority 4: OpenAI direct
    if settings.openai_api_key:
        model = OPENAI_FALLBACKS[complexity]
        return "https://api.openai.com/v1/chat/completions", model, complexity

    raise RuntimeError(
        "No API key configured (need OPENROUTER_API_KEY, ANTHROPIC_API_KEY, "
        "GOOGLE_AI_API_KEY, or OPENAI_API_KEY)"
    )


async def _call_anthropic_direct(
    system: str,
    user: str,
    model: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 16000,
    timeout: int = 120,
) -> str:
    """Call the Anthropic Messages API directly using the official SDK."""
    import anthropic

    settings = get_settings()
    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=float(timeout),
    )

    response = await client.messages.create(
        model=model,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=temperature,
        max_tokens=max_tokens,
    )

    content = ""
    for block in response.content:
        if hasattr(block, "text"):
            content += block.text

    logger.info(
        "supervisor_llm_usage",
        model=model,
        backend="anthropic",
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
    )

    return content


async def _call_google_direct(
    system: str,
    user: str,
    model: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 16000,
    timeout: int = 120,
) -> str:
    """Call the Google Gemini API directly using the google-genai SDK."""
    import asyncio
    from google import genai
    from google.genai import types

    settings = get_settings()
    client = genai.Client(api_key=settings.google_ai_api_key)

    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: client.models.generate_content(
            model=model,
            contents=user,
            config=config,
        ),
    )

    content = response.text or ""

    usage = getattr(response, "usage_metadata", None)
    p_tokens = getattr(usage, "prompt_token_count", 0) or 0
    c_tokens = getattr(usage, "candidates_token_count", 0) or 0

    logger.info(
        "supervisor_llm_usage",
        model=model,
        backend="google",
        prompt_tokens=p_tokens,
        completion_tokens=c_tokens,
    )

    return content


async def _call_http_api(
    url: str,
    api_key: str,
    system: str,
    user: str,
    model: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 16000,
    timeout: int = 120,
) -> str:
    """Call an OpenAI-compatible HTTP API (OpenRouter or OpenAI)."""
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

        usage = data.get("usage", {})
        if usage:
            logger.info(
                "supervisor_llm_usage",
                model=model,
                backend="http",
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
            )

        return content


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

    Automatically selects the best backend and model based on task type
    and available API keys (OpenRouter → Anthropic → Google → OpenAI).

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
    url_or_backend, model, complexity = select_model(task_type)

    logger.info(
        "supervisor_llm_call",
        task_type=task_type,
        complexity=complexity.value,
        model=model,
        backend=url_or_backend[:20],
    )

    settings = get_settings()

    if url_or_backend == BACKEND_ANTHROPIC:
        return await _call_anthropic_direct(
            system, user, model,
            temperature=temperature, max_tokens=max_tokens, timeout=timeout,
        )

    if url_or_backend == BACKEND_GOOGLE:
        return await _call_google_direct(
            system, user, model,
            temperature=temperature, max_tokens=max_tokens, timeout=timeout,
        )

    # OpenRouter or OpenAI — both use OpenAI-compatible HTTP API
    api_key = settings.openrouter_api_key or settings.openai_api_key
    if not api_key:
        raise RuntimeError("No API key for HTTP LLM call")

    return await _call_http_api(
        url_or_backend, api_key, system, user, model,
        temperature=temperature, max_tokens=max_tokens, timeout=timeout,
    )
