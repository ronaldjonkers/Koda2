"""Tests for the assistant email service (IMAP + SMTP)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.email.assistant_mail import (
    AssistantEmailConfig,
    AssistantInboxMessage,
    AssistantMailService,
    auto_port,
    DEFAULT_PORTS,
    ENCRYPTION_OPTIONS,
)


class TestAutoPort:
    """Tests for the auto_port helper."""

    def test_imap_ssl(self) -> None:
        assert auto_port("imap", "ssl") == 993

    def test_imap_starttls(self) -> None:
        assert auto_port("imap", "starttls") == 143

    def test_smtp_ssl(self) -> None:
        assert auto_port("smtp", "ssl") == 465

    def test_smtp_starttls(self) -> None:
        assert auto_port("smtp", "starttls") == 587

    def test_smtp_none(self) -> None:
        assert auto_port("smtp", "none") == 25

    def test_unknown_protocol(self) -> None:
        assert auto_port("pop3", "ssl") == 0


class TestAssistantEmailConfig:
    """Tests for the AssistantEmailConfig dataclass."""

    def test_smtp_configured_true(self) -> None:
        cfg = AssistantEmailConfig(
            smtp_server="smtp.example.com",
            smtp_username="user@example.com",
            smtp_password="secret",
            email_address="ai@example.com",
        )
        assert cfg.smtp_configured is True
        assert cfg.is_configured is True

    def test_imap_configured_true(self) -> None:
        cfg = AssistantEmailConfig(
            imap_server="imap.example.com",
            imap_username="user@example.com",
            imap_password="secret",
            email_address="ai@example.com",
        )
        assert cfg.imap_configured is True

    def test_fully_configured(self) -> None:
        cfg = AssistantEmailConfig(
            imap_server="imap.example.com", imap_username="u", imap_password="p",
            smtp_server="smtp.example.com", smtp_username="u", smtp_password="p",
            email_address="ai@example.com",
        )
        assert cfg.fully_configured is True

    def test_not_configured_missing_server(self) -> None:
        cfg = AssistantEmailConfig(
            smtp_username="user@example.com",
            smtp_password="secret",
            email_address="ai@example.com",
        )
        assert cfg.smtp_configured is False
        assert cfg.is_configured is False

    def test_to_dict_hides_both_passwords(self) -> None:
        cfg = AssistantEmailConfig(
            imap_server="i", imap_username="u", imap_password="imap_secret",
            smtp_server="s", smtp_username="u", smtp_password="smtp_secret",
            email_address="ai@example.com",
        )
        d = cfg.to_dict(hide_password=True)
        assert d["imap_password"] == "••••••••"
        assert d["smtp_password"] == "••••••••"
        assert d["fully_configured"] is True

    def test_to_dict_shows_passwords(self) -> None:
        cfg = AssistantEmailConfig(
            smtp_server="s", smtp_username="u", smtp_password="mypass",
            email_address="ai@example.com",
        )
        d = cfg.to_dict(hide_password=False)
        assert d["smtp_password"] == "mypass"

    def test_defaults(self) -> None:
        cfg = AssistantEmailConfig()
        assert cfg.smtp_port == 587
        assert cfg.imap_port == 993
        assert cfg.smtp_encryption == "starttls"
        assert cfg.imap_encryption == "ssl"
        assert cfg.check_interval == 10
        assert cfg.is_configured is False
        assert cfg.fully_configured is False

    def test_encryption_in_to_dict(self) -> None:
        cfg = AssistantEmailConfig(imap_encryption="starttls", smtp_encryption="ssl")
        d = cfg.to_dict()
        assert d["imap_encryption"] == "starttls"
        assert d["smtp_encryption"] == "ssl"
        assert d["check_interval"] == 10


class TestAssistantInboxMessage:
    """Tests for the inbox message dataclass."""

    def test_to_dict_truncates_body(self) -> None:
        msg = AssistantInboxMessage(
            uid="1", subject="Test", sender="a@b.com",
            body_text="x" * 1000,
        )
        d = msg.to_dict()
        assert len(d["body_text"]) == 500

    def test_to_dict_fields(self) -> None:
        msg = AssistantInboxMessage(uid="42", subject="Hi", sender="a@b.com", is_read=True)
        d = msg.to_dict()
        assert d["uid"] == "42"
        assert d["is_read"] is True


class TestAssistantMailService:
    """Tests for the AssistantMailService."""

    def _make_settings(self, **overrides) -> MagicMock:
        s = MagicMock()
        defaults = {
            "assistant_imap_server": "", "assistant_imap_port": 993,
            "assistant_imap_username": "", "assistant_imap_password": "",
            "assistant_imap_use_ssl": True,
            "assistant_smtp_server": "", "assistant_smtp_port": 587,
            "assistant_smtp_username": "", "assistant_smtp_password": "",
            "assistant_smtp_use_tls": True,
            "assistant_email_address": "", "assistant_email_display_name": "",
            "assistant_email_check_interval": 10, "assistant_name": "Koda2",
        }
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(s, k, v)
        return s

    @pytest.fixture
    def service(self) -> AssistantMailService:
        with patch("koda2.modules.email.assistant_mail.get_settings") as m:
            m.return_value = self._make_settings()
            yield AssistantMailService(account_service=None)

    @pytest.fixture
    def smtp_service(self) -> AssistantMailService:
        with patch("koda2.modules.email.assistant_mail.get_settings") as m:
            m.return_value = self._make_settings(
                assistant_smtp_server="smtp.example.com",
                assistant_smtp_username="bot@example.com",
                assistant_smtp_password="secret",
                assistant_email_address="bot@example.com",
                assistant_email_display_name="Koda2 Bot",
            )
            yield AssistantMailService(account_service=None)

    @pytest.fixture
    def full_service(self) -> AssistantMailService:
        with patch("koda2.modules.email.assistant_mail.get_settings") as m:
            m.return_value = self._make_settings(
                assistant_imap_server="imap.example.com",
                assistant_imap_username="bot@example.com",
                assistant_imap_password="secret",
                assistant_smtp_server="smtp.example.com",
                assistant_smtp_username="bot@example.com",
                assistant_smtp_password="secret",
                assistant_email_address="bot@example.com",
                assistant_email_display_name="Koda2 Bot",
            )
            yield AssistantMailService(account_service=None)

    @pytest.mark.asyncio
    async def test_get_config_env_fallback(self, service: AssistantMailService) -> None:
        cfg = await service.get_config()
        assert cfg.is_configured is False
        assert cfg.imap_configured is False

    @pytest.mark.asyncio
    async def test_get_config_smtp_only(self, smtp_service: AssistantMailService) -> None:
        cfg = await smtp_service.get_config()
        assert cfg.smtp_configured is True
        assert cfg.imap_configured is False
        assert cfg.smtp_server == "smtp.example.com"

    @pytest.mark.asyncio
    async def test_get_config_fully_configured(self, full_service: AssistantMailService) -> None:
        cfg = await full_service.get_config()
        assert cfg.fully_configured is True
        assert cfg.display_name == "Koda2 Bot"

    @pytest.mark.asyncio
    async def test_send_email_not_configured(self, service: AssistantMailService) -> None:
        result = await service.send_email(to=["u@e.com"], subject="T", body_text="Hi")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_email_success(self, smtp_service: AssistantMailService) -> None:
        with patch("koda2.modules.email.assistant_mail.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = AsyncMock(return_value=None)
            result = await smtp_service.send_email(
                to=["user@example.com"], subject="Test", body_text="Hello",
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_test_smtp_not_configured(self, service: AssistantMailService) -> None:
        ok, msg = await service.test_smtp()
        assert ok is False
        assert "not configured" in msg.lower()

    @pytest.mark.asyncio
    async def test_test_imap_not_configured(self, service: AssistantMailService) -> None:
        ok, msg = await service.test_imap()
        assert ok is False
        assert "not configured" in msg.lower()

    @pytest.mark.asyncio
    async def test_test_connection_nothing(self, service: AssistantMailService) -> None:
        ok, msg = await service.test_connection()
        assert ok is False
        assert "nothing" in msg.lower()

    @pytest.mark.asyncio
    async def test_test_smtp_success(self, smtp_service: AssistantMailService) -> None:
        with patch("koda2.modules.email.assistant_mail.asyncio") as mock_asyncio:
            mock_asyncio.wait_for = AsyncMock(return_value=None)
            ok, msg = await smtp_service.test_smtp()
            assert ok is True
            assert "smtp" in msg.lower()

    @pytest.mark.asyncio
    async def test_test_imap_success(self, full_service: AssistantMailService) -> None:
        with patch("koda2.modules.email.assistant_mail.asyncio") as mock_asyncio:
            mock_asyncio.wait_for = AsyncMock(return_value=None)
            ok, msg = await full_service.test_imap()
            assert ok is True
            assert "imap" in msg.lower()

    @pytest.mark.asyncio
    async def test_test_connection_both(self, full_service: AssistantMailService) -> None:
        with patch("koda2.modules.email.assistant_mail.asyncio") as mock_asyncio:
            mock_asyncio.wait_for = AsyncMock(return_value=None)
            ok, msg = await full_service.test_connection()
            assert ok is True
            assert "imap" in msg.lower()
            assert "smtp" in msg.lower()

    @pytest.mark.asyncio
    async def test_fetch_emails_not_configured(self, service: AssistantMailService) -> None:
        emails = await service.fetch_emails()
        assert emails == []

    @pytest.mark.asyncio
    async def test_check_inbox_not_configured(self, service: AssistantMailService) -> None:
        emails = await service.check_inbox()
        assert emails == []

    @pytest.mark.asyncio
    async def test_reply_email(self, smtp_service: AssistantMailService) -> None:
        original = AssistantInboxMessage(
            uid="123", subject="Hello", sender="user@test.com",
            recipients=["bot@example.com"],
        )
        with patch.object(smtp_service, "send_email", new_callable=AsyncMock, return_value=True) as mock_send:
            result = await smtp_service.reply_email(original, body_text="Thanks!")
            assert result is True
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            assert call_kwargs["to"] == ["user@test.com"]
            assert call_kwargs["subject"] == "Re: Hello"
