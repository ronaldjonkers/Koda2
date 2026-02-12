"""Shared test fixtures and configuration."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("EXECUTIVEAI_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CHROMA_PERSIST_DIR", "/tmp/executiveai_test_chroma")
os.environ.setdefault("EXECUTIVEAI_SECRET_KEY", "test-secret-key-do-not-use")
os.environ.setdefault("EXECUTIVEAI_LOG_LEVEL", "WARNING")

from executiveai.config import Settings, get_settings
from executiveai.database import Base


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def settings() -> Settings:
    """Return test settings."""
    return Settings(
        executiveai_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        chroma_persist_dir="/tmp/executiveai_test_chroma",
        executiveai_secret_key="test-secret-key",
        executiveai_log_level="WARNING",
    )


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean in-memory database session for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def mock_openai():
    """Mock the OpenAI client."""
    with patch("openai.AsyncOpenAI") as mock:
        client = MagicMock()
        mock.return_value = client

        completion = MagicMock()
        completion.choices = [MagicMock()]
        completion.choices[0].message.content = '{"intent": "general_chat", "response": "Hello!", "entities": {}, "actions": []}'
        completion.choices[0].message.tool_calls = None
        completion.choices[0].finish_reason = "stop"
        completion.usage = MagicMock()
        completion.usage.prompt_tokens = 10
        completion.usage.completion_tokens = 20
        completion.usage.total_tokens = 30

        client.chat.completions.create = AsyncMock(return_value=completion)
        yield client


@pytest.fixture
def mock_anthropic():
    """Mock the Anthropic client."""
    with patch("anthropic.AsyncAnthropic") as mock:
        client = MagicMock()
        mock.return_value = client

        response = MagicMock()
        response.content = [MagicMock()]
        response.content[0].text = "Hello from Claude!"
        response.usage.input_tokens = 10
        response.usage.output_tokens = 20
        response.stop_reason = "end_turn"

        client.messages.create = AsyncMock(return_value=response)
        yield client


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test file operations."""
    return tmp_path
