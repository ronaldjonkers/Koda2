"""Concrete LLM provider implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.llm.models import ChatMessage, LLMProvider, LLMResponse

logger = get_logger(__name__)


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    provider: LLMProvider

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Generate a completion from the provider."""

    @abstractmethod
    async def stream(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream a completion from the provider."""

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider has valid credentials."""


class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT models provider."""

    provider = LLMProvider.OPENAI

    def __init__(self) -> None:
        self._settings = get_settings()

    def is_available(self) -> bool:
        return bool(self._settings.openai_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def complete(
        self,
        messages: list[ChatMessage],
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        import openai

        client = openai.AsyncOpenAI(api_key=self._settings.openai_api_key)
        msgs: list[dict[str, Any]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            msg: dict[str, Any] = {"role": m.role}
            if m.role == "assistant" and m.tool_calls:
                msg["content"] = m.content or None
                msg["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}
                    for tc in m.tool_calls
                ]
            elif m.role == "tool":
                msg["content"] = m.content
                msg["tool_call_id"] = m.tool_call_id
            else:
                msg["content"] = m.content
            msgs.append(msg)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in choice.message.tool_calls
            ]

        return LLMResponse(
            content=choice.message.content or "",
            provider=self.provider,
            model=model,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            finish_reason=choice.finish_reason or "",
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        import openai

        client = openai.AsyncOpenAI(api_key=self._settings.openai_api_key)
        msgs: list[dict[str, Any]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend({"role": m.role, "content": m.content} for m in messages)

        stream = await client.chat.completions.create(
            model=model, messages=msgs, temperature=temperature,
            max_tokens=max_tokens, stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude models provider."""

    provider = LLMProvider.ANTHROPIC

    def __init__(self) -> None:
        self._settings = get_settings()

    def is_available(self) -> bool:
        return bool(self._settings.anthropic_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def complete(
        self,
        messages: list[ChatMessage],
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)

        # Build messages with tool call support
        msgs: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "assistant" and m.tool_calls:
                # Anthropic: assistant message with tool_use blocks
                blocks: list[dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    import json as _json
                    args = tc["function"]["arguments"]
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": _json.loads(args) if isinstance(args, str) else args,
                    })
                msgs.append({"role": "assistant", "content": blocks})
            elif m.role == "tool":
                # Anthropic: tool results are user messages with tool_result blocks
                msgs.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}],
                })
            else:
                msgs.append({"role": m.role, "content": m.content})

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if tools:
            # Convert OpenAI-format tools to Anthropic format
            anthropic_tools = []
            for tool in tools:
                func = tool.get("function", {})
                anthropic_tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                })
            kwargs["tools"] = anthropic_tools

        response = await client.messages.create(**kwargs)

        content = ""
        tool_calls = None
        for block in response.content:
            if hasattr(block, "text"):
                content += block.text
            elif block.type == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                import json as _json
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": _json.dumps(block.input) if isinstance(block.input, dict) else block.input,
                    },
                })

        return LLMResponse(
            content=content,
            provider=self.provider,
            model=model,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            finish_reason=response.stop_reason or "",
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        model: str = "claude-sonnet-4-20250514",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        msgs = [{"role": m.role, "content": m.content} for m in messages]

        kwargs: dict[str, Any] = {
            "model": model, "messages": msgs,
            "max_tokens": max_tokens, "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text


class GoogleProvider(BaseLLMProvider):
    """Google Gemini models provider — uses the new google-genai SDK."""

    provider = LLMProvider.GOOGLE

    def __init__(self) -> None:
        self._settings = get_settings()

    def is_available(self) -> bool:
        return bool(self._settings.google_ai_api_key)

    def _get_client(self):
        """Create a google-genai Client."""
        from google import genai
        return genai.Client(api_key=self._settings.google_ai_api_key)

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list:
        """Convert OpenAI-format tool definitions to google-genai format."""
        from google.genai import types
        declarations = []
        for tool in tools:
            func = tool.get("function", {})
            declarations.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return [types.Tool(function_declarations=declarations)]

    def _build_contents(
        self, messages: list[ChatMessage],
    ) -> list:
        """Convert ChatMessage list to google-genai Content objects."""
        import json as _json
        from google.genai import types

        contents = []
        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                parts = []
                if msg.content:
                    parts.append(types.Part.from_text(text=msg.content))
                for tc in msg.tool_calls:
                    args = tc["function"]["arguments"]
                    args_dict = _json.loads(args) if isinstance(args, str) else args
                    parts.append(types.Part.from_function_call(
                        name=tc["function"]["name"],
                        args=args_dict,
                    ))
                contents.append(types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                try:
                    result_data = _json.loads(msg.content)
                except (ValueError, TypeError):
                    result_data = {"result": msg.content}
                # Recover the tool name from the preceding assistant message
                tool_name = "tool_result"
                for prev in reversed(contents):
                    if prev.role == "model" and prev.parts:
                        for p in prev.parts:
                            if hasattr(p, "function_call") and p.function_call:
                                tool_name = p.function_call.name
                                break
                        break
                parts = [types.Part.from_function_response(
                    name=tool_name,
                    response=result_data,
                )]
                contents.append(types.Content(role="user", parts=parts))
            elif msg.role == "user":
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=msg.content)],
                ))
            else:
                # assistant text-only
                contents.append(types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=msg.content)],
                ))
        return contents

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def complete(
        self,
        messages: list[ChatMessage],
        model: str = "gemini-2.0-flash",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        import asyncio
        from google.genai import types

        client = self._get_client()
        contents = self._build_contents(messages)

        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        if tools:
            config_kwargs["tools"] = self._convert_tools(tools)

        config = types.GenerateContentConfig(**config_kwargs)

        # google-genai Client is sync — run in executor for async
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            ),
        )

        # Extract usage
        usage = getattr(response, "usage_metadata", None)
        p_tokens = getattr(usage, "prompt_token_count", 0) or 0
        c_tokens = getattr(usage, "candidates_token_count", 0) or 0

        # Parse response for text and function calls
        content = ""
        tool_calls = None
        if response.candidates:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    content += part.text
                elif hasattr(part, "function_call") and part.function_call and part.function_call.name:
                    if tool_calls is None:
                        tool_calls = []
                    import json as _json
                    fc = part.function_call
                    args_dict = dict(fc.args) if fc.args else {}
                    tool_calls.append({
                        "id": f"gemini_{fc.name}_{len(tool_calls)}",
                        "type": "function",
                        "function": {
                            "name": fc.name,
                            "arguments": _json.dumps(args_dict),
                        },
                    })

        return LLMResponse(
            content=content,
            provider=self.provider,
            model=model,
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            total_tokens=p_tokens + c_tokens,
            finish_reason="stop",
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        model: str = "gemini-2.0-flash",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        import asyncio
        from google.genai import types

        client = self._get_client()

        config_kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_prompt:
            config_kwargs["system_instruction"] = system_prompt
        config = types.GenerateContentConfig(**config_kwargs)

        # Stream via sync generator in executor
        def _stream():
            return client.models.generate_content_stream(
                model=model,
                contents=messages[-1].content,
                config=config,
            )

        loop = asyncio.get_event_loop()
        stream_iter = await loop.run_in_executor(None, _stream)
        for chunk in stream_iter:
            if chunk.text:
                yield chunk.text


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter multi-model gateway provider."""

    provider = LLMProvider.OPENROUTER
    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self) -> None:
        self._settings = get_settings()

    def is_available(self) -> bool:
        return bool(self._settings.openrouter_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def complete(
        self,
        messages: list[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
        tools: Optional[list[dict[str, Any]]] = None,
    ) -> LLMResponse:
        # Use configured model if not specified
        if model is None:
            model = self._settings.openrouter_model
        msgs: list[dict[str, Any]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            msg_dict: dict[str, Any] = {"role": m.role}
            if m.role == "assistant" and m.tool_calls:
                msg_dict["content"] = m.content or None
                msg_dict["tool_calls"] = [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}
                    for tc in m.tool_calls
                ]
            elif m.role == "tool":
                msg_dict["content"] = m.content
                msg_dict["tool_call_id"] = m.tool_call_id
            else:
                msg_dict["content"] = m.content
            msgs.append(msg_dict)

        payload: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        tool_calls = None
        raw_tool_calls = choice.get("message", {}).get("tool_calls")
        if raw_tool_calls:
            tool_calls = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]},
                }
                for tc in raw_tool_calls
            ]

        return LLMResponse(
            content=choice["message"].get("content") or "",
            provider=self.provider,
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            finish_reason=choice.get("finish_reason", ""),
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> AsyncIterator[str]:
        # Use configured model if not specified
        if model is None:
            model = self._settings.openrouter_model
        msgs: list[dict[str, str]] = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend({"role": m.role, "content": m.content} for m in messages)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.BASE_URL}/chat/completions",
                json={"model": model, "messages": msgs, "temperature": temperature,
                       "max_tokens": max_tokens, "stream": True},
                headers={
                    "Authorization": f"Bearer {self._settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120,
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        import json
                        chunk = json.loads(line[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        if content := delta.get("content"):
                            yield content
