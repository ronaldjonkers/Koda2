"""Tests for configuration module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from koda2.config import Settings


class TestSettings:
    """Tests for the Settings configuration class."""

    @patch.dict(os.environ, {}, clear=True)
    def test_default_values(self) -> None:
        """Settings loads with sane defaults."""
        s = Settings(
            koda2_env="test",
            database_url="sqlite+aiosqlite:///:memory:",
            koda2_log_level="INFO",
            _env_file=None,
        )
        assert s.koda2_env == "test"
        assert s.api_port == 8000
        assert s.koda2_log_level == "INFO"
        assert s.llm_default_provider == "openai"

    def test_data_dir_creation(self, tmp_path) -> None:
        """data_dir property creates the directory."""
        s = Settings(koda2_env="test", database_url="sqlite+aiosqlite:///:memory:")
        path = s.data_dir
        assert path.exists()

    def test_allowed_telegram_ids_parsing(self) -> None:
        """Telegram IDs are parsed from comma-separated string."""
        s = Settings(
            koda2_env="test",
            database_url="sqlite+aiosqlite:///:memory:",
            telegram_allowed_user_ids="123, 456, 789",
        )
        assert s.allowed_telegram_ids == [123, 456, 789]

    def test_allowed_telegram_ids_empty(self) -> None:
        """Empty telegram IDs returns empty list."""
        s = Settings(
            koda2_env="test",
            database_url="sqlite+aiosqlite:///:memory:",
            telegram_allowed_user_ids="",
        )
        assert s.allowed_telegram_ids == []

    def test_has_provider(self) -> None:
        """has_provider checks for API key presence."""
        s = Settings(
            koda2_env="test",
            database_url="sqlite+aiosqlite:///:memory:",
            openai_api_key="sk-test-key",
        )
        assert s.has_provider("openai") is True
        assert s.has_provider("anthropic") is False
        assert s.has_provider("unknown") is False

    def test_encryption_key_empty(self) -> None:
        """Empty encryption key is allowed (ephemeral key generated at runtime)."""
        s = Settings(
            koda2_env="test",
            database_url="sqlite+aiosqlite:///:memory:",
            koda2_encryption_key="",
        )
        assert s.koda2_encryption_key == ""
