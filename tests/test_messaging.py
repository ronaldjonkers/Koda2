"""Tests for messaging module (Telegram + WhatsApp)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.messaging.whatsapp_bot import WhatsAppBot
from koda2.modules.messaging.telegram_bot import TelegramBot


class TestTelegramBot:
    """Tests for the Telegram Bot integration."""

    @pytest.fixture
    def telegram(self):
        with patch("koda2.modules.messaging.telegram_bot.get_settings") as mock:
            mock.return_value = MagicMock(
                telegram_bot_token="test-token",
                telegram_allowed_user_ids="123,456",
                allowed_telegram_ids=[123, 456],
            )
            return TelegramBot()

    def test_is_configured(self, telegram) -> None:
        """Bot reports configured when token is set."""
        assert telegram.is_configured is True

    def test_not_configured_without_token(self) -> None:
        """Bot reports not configured without token."""
        with patch("koda2.modules.messaging.telegram_bot.get_settings") as mock:
            mock.return_value = MagicMock(
                telegram_bot_token="",
                allowed_telegram_ids=[],
            )
            bot = TelegramBot()
            assert bot.is_configured is False

    def test_check_user_allowed(self, telegram) -> None:
        """Allowed user IDs are checked correctly."""
        assert telegram._check_user_allowed(123) is True
        assert telegram._check_user_allowed(999) is False

    def test_check_user_allowed_no_restriction(self) -> None:
        """All users allowed when no IDs configured."""
        with patch("koda2.modules.messaging.telegram_bot.get_settings") as mock:
            mock.return_value = MagicMock(
                telegram_bot_token="token",
                allowed_telegram_ids=[],
            )
            bot = TelegramBot()
            assert bot._check_user_allowed(999) is True

    def test_register_command(self, telegram) -> None:
        """Commands are registered correctly."""
        async def handler(**kwargs):
            return "ok"

        telegram.register_command("/test", handler)
        assert "test" in telegram._command_handlers

    def test_register_command_without_slash(self, telegram) -> None:
        """Commands without leading slash are handled."""
        async def handler(**kwargs):
            return "ok"

        telegram.register_command("status", handler)
        assert "status" in telegram._command_handlers

    def test_set_message_handler(self, telegram) -> None:
        """Default message handler is set."""
        async def handler(**kwargs):
            return "ok"

        telegram.set_message_handler(handler)
        assert telegram._message_handler is not None


class TestWhatsAppBot:
    """Tests for the WhatsApp Business API integration."""

    @pytest.fixture
    def whatsapp(self):
        with patch("koda2.modules.messaging.whatsapp_bot.get_settings") as mock:
            mock.return_value = MagicMock(
                whatsapp_api_url="https://api.whatsapp.test",
                whatsapp_api_token="test-token",
            )
            return WhatsAppBot()

    def test_is_configured(self, whatsapp) -> None:
        """Bot reports configured when URL and token are set."""
        assert whatsapp.is_configured is True

    def test_not_configured(self) -> None:
        """Bot reports not configured without credentials."""
        with patch("koda2.modules.messaging.whatsapp_bot.get_settings") as mock:
            mock.return_value = MagicMock(whatsapp_api_url="", whatsapp_api_token="")
            bot = WhatsAppBot()
            assert bot.is_configured is False

    @pytest.mark.asyncio
    async def test_send_message_not_configured(self) -> None:
        """Sending when not configured returns status."""
        with patch("koda2.modules.messaging.whatsapp_bot.get_settings") as mock:
            mock.return_value = MagicMock(whatsapp_api_url="", whatsapp_api_token="")
            bot = WhatsAppBot()
            result = await bot.send_message("+31612345678", "Hello")
            assert result["status"] == "not_configured"

    @pytest.mark.asyncio
    async def test_send_message(self, whatsapp) -> None:
        """Sending a message via WhatsApp API."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {"messages": [{"id": "msg123"}]}
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            result = await whatsapp.send_message("+31612345678", "Hello!")
            assert "messages" in result
            mock_instance.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_media_not_configured(self) -> None:
        """send_media when not configured returns status."""
        with patch("koda2.modules.messaging.whatsapp_bot.get_settings") as mock:
            mock.return_value = MagicMock(whatsapp_api_url="", whatsapp_api_token="")
            bot = WhatsAppBot()
            result = await bot.send_media("+31612345678", "https://img.test/1.png")
            assert result["status"] == "not_configured"

    @pytest.mark.asyncio
    async def test_send_template_not_configured(self) -> None:
        """send_template when not configured returns status."""
        with patch("koda2.modules.messaging.whatsapp_bot.get_settings") as mock:
            mock.return_value = MagicMock(whatsapp_api_url="", whatsapp_api_token="")
            bot = WhatsAppBot()
            result = await bot.send_template("+31612345678", "welcome")
            assert result["status"] == "not_configured"

    @pytest.mark.asyncio
    async def test_process_webhook_text(self, whatsapp) -> None:
        """Processing a text webhook payload."""
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "+31612345678",
                            "type": "text",
                            "timestamp": "1707700000",
                            "text": {"body": "Hello!"},
                        }]
                    }
                }]
            }]
        }
        result = await whatsapp.process_webhook(payload)
        assert result is not None
        assert result["from"] == "+31612345678"
        assert result["text"] == "Hello!"

    @pytest.mark.asyncio
    async def test_process_webhook_image(self, whatsapp) -> None:
        """Processing an image webhook payload."""
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "+31612345678",
                            "type": "image",
                            "timestamp": "1707700000",
                            "image": {"id": "img123", "mime_type": "image/jpeg", "caption": "Photo"},
                        }]
                    }
                }]
            }]
        }
        result = await whatsapp.process_webhook(payload)
        assert result["type"] == "image"
        assert result["media_id"] == "img123"

    @pytest.mark.asyncio
    async def test_process_webhook_empty(self, whatsapp) -> None:
        """Processing empty webhook returns None."""
        result = await whatsapp.process_webhook({"entry": [{"changes": [{"value": {}}]}]})
        assert result is None

    @pytest.mark.asyncio
    async def test_process_webhook_invalid(self, whatsapp) -> None:
        """Processing invalid webhook returns None."""
        result = await whatsapp.process_webhook({})
        assert result is None
