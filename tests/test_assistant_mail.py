"""Tests for the assistant email service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.email.assistant_mail import AssistantEmailConfig, AssistantMailService


class TestAssistantEmailConfig:
    """Tests for the AssistantEmailConfig dataclass."""

    def test_is_configured_true(self) -> None:
        cfg = AssistantEmailConfig(
            smtp_server="smtp.example.com",
            smtp_username="user@example.com",
            smtp_password="secret",
            email_address="ai@example.com",
        )
        assert cfg.is_configured is True

    def test_is_configured_false_missing_server(self) -> None:
        cfg = AssistantEmailConfig(
            smtp_username="user@example.com",
            smtp_password="secret",
            email_address="ai@example.com",
        )
        assert cfg.is_configured is False

    def test_is_configured_false_missing_password(self) -> None:
        cfg = AssistantEmailConfig(
            smtp_server="smtp.example.com",
            smtp_username="user@example.com",
            email_address="ai@example.com",
        )
        assert cfg.is_configured is False

    def test_to_dict_hides_password(self) -> None:
        cfg = AssistantEmailConfig(
            smtp_server="smtp.example.com",
            smtp_username="user",
            smtp_password="secret123",
            email_address="ai@example.com",
        )
        d = cfg.to_dict(hide_password=True)
        assert d["smtp_password"] == "••••••••"
        assert d["smtp_server"] == "smtp.example.com"
        assert d["is_configured"] is True

    def test_to_dict_shows_password(self) -> None:
        cfg = AssistantEmailConfig(
            smtp_server="smtp.example.com",
            smtp_username="user",
            smtp_password="secret123",
            email_address="ai@example.com",
        )
        d = cfg.to_dict(hide_password=False)
        assert d["smtp_password"] == "secret123"

    def test_defaults(self) -> None:
        cfg = AssistantEmailConfig()
        assert cfg.smtp_port == 587
        assert cfg.smtp_use_tls is True
        assert cfg.is_configured is False


class TestAssistantMailService:
    """Tests for the AssistantMailService."""

    @pytest.fixture
    def service(self) -> AssistantMailService:
        with patch("koda2.modules.email.assistant_mail.get_settings") as mock_settings:
            s = MagicMock()
            s.assistant_smtp_server = ""
            s.assistant_smtp_port = 587
            s.assistant_smtp_username = ""
            s.assistant_smtp_password = ""
            s.assistant_smtp_use_tls = True
            s.assistant_email_address = ""
            s.assistant_email_display_name = ""
            s.assistant_name = "Koda2"
            mock_settings.return_value = s
            yield AssistantMailService(account_service=None)

    @pytest.fixture
    def configured_service(self) -> AssistantMailService:
        with patch("koda2.modules.email.assistant_mail.get_settings") as mock_settings:
            s = MagicMock()
            s.assistant_smtp_server = "smtp.example.com"
            s.assistant_smtp_port = 587
            s.assistant_smtp_username = "bot@example.com"
            s.assistant_smtp_password = "secret"
            s.assistant_smtp_use_tls = True
            s.assistant_email_address = "bot@example.com"
            s.assistant_email_display_name = "Koda2 Bot"
            s.assistant_name = "Koda2"
            mock_settings.return_value = s
            yield AssistantMailService(account_service=None)

    @pytest.mark.asyncio
    async def test_get_config_env_fallback(self, service: AssistantMailService) -> None:
        """Without DB config, falls back to env (empty in this test)."""
        cfg = await service.get_config()
        assert cfg.is_configured is False

    @pytest.mark.asyncio
    async def test_get_config_env_configured(self, configured_service: AssistantMailService) -> None:
        """Env with valid settings returns configured config."""
        cfg = await configured_service.get_config()
        assert cfg.is_configured is True
        assert cfg.smtp_server == "smtp.example.com"
        assert cfg.email_address == "bot@example.com"
        assert cfg.display_name == "Koda2 Bot"

    @pytest.mark.asyncio
    async def test_send_email_not_configured(self, service: AssistantMailService) -> None:
        """Sending when not configured returns False."""
        result = await service.send_email(
            to=["user@example.com"],
            subject="Test",
            body_text="Hello",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_email_success(self, configured_service: AssistantMailService) -> None:
        """Sending with valid config succeeds (SMTP mocked)."""
        with patch("koda2.modules.email.assistant_mail.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = AsyncMock(return_value=True)
            result = await configured_service.send_email(
                to=["user@example.com"],
                subject="Test Subject",
                body_text="Hello there",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_test_connection_not_configured(self, service: AssistantMailService) -> None:
        """Testing connection when not configured returns failure."""
        ok, msg = await service.test_connection()
        assert ok is False
        assert "not configured" in msg.lower()

    @pytest.mark.asyncio
    async def test_test_connection_success(self, configured_service: AssistantMailService) -> None:
        """Testing connection with valid config succeeds (SMTP mocked)."""
        with patch("koda2.modules.email.assistant_mail.asyncio") as mock_asyncio:
            mock_asyncio.wait_for = AsyncMock(return_value=True)
            ok, msg = await configured_service.test_connection()
            assert ok is True
            assert "successful" in msg.lower()
