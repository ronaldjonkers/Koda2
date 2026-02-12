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

    @pytest.mark.asyncio
    async def test_is_configured(self, telegram) -> None:
        """Bot reports configured when token is set."""
        assert await telegram.is_configured() is True

    @pytest.mark.asyncio
    async def test_not_configured_without_token(self) -> None:
        """Bot reports not configured without token."""
        with patch("koda2.modules.messaging.telegram_bot.get_settings") as mock:
            mock.return_value = MagicMock(
                telegram_bot_token="",
                allowed_telegram_ids=[],
            )
            bot = TelegramBot()
            assert await bot.is_configured() is False

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
    """Tests for the WhatsApp Web bridge integration."""

    @pytest.fixture
    def whatsapp(self):
        with patch("koda2.modules.messaging.whatsapp_bot.get_settings") as mock:
            mock.return_value = MagicMock(
                whatsapp_enabled=True,
                whatsapp_bridge_port=3001,
                api_port=8000,
            )
            return WhatsAppBot()

    @pytest.fixture
    def whatsapp_disabled(self):
        with patch("koda2.modules.messaging.whatsapp_bot.get_settings") as mock:
            mock.return_value = MagicMock(
                whatsapp_enabled=False,
                whatsapp_bridge_port=3001,
                api_port=8000,
            )
            return WhatsAppBot()

    def test_is_configured(self, whatsapp) -> None:
        """Bot reports configured when enabled."""
        assert whatsapp.is_configured is True

    def test_not_configured(self, whatsapp_disabled) -> None:
        """Bot reports not configured when disabled."""
        assert whatsapp_disabled.is_configured is False

    def test_bridge_url(self, whatsapp) -> None:
        """Bridge URL is constructed from port."""
        assert whatsapp.bridge_url == "http://localhost:3001"

    @pytest.mark.asyncio
    async def test_send_message_not_configured(self, whatsapp_disabled) -> None:
        """Sending when not configured returns status."""
        result = await whatsapp_disabled.send_message("+31612345678", "Hello")
        assert result["status"] == "not_configured"

    @pytest.mark.asyncio
    async def test_send_message(self, whatsapp) -> None:
        """Sending a message via bridge."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "sent", "id": "msg123"}
            mock_response.raise_for_status = MagicMock()

            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            result = await whatsapp.send_message("+31612345678", "Hello!")
            assert result["status"] == "sent"
            mock_instance.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self, whatsapp) -> None:
        """Sending when bridge not connected returns status."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.json.return_value = {"error": "WhatsApp not connected"}

            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_instance

            result = await whatsapp.send_message("+31612345678", "Hello!")
            assert result["status"] == "not_connected"

    @pytest.mark.asyncio
    async def test_send_media_not_configured(self, whatsapp_disabled) -> None:
        """send_media when not configured returns status."""
        result = await whatsapp_disabled.send_media("+31612345678", "https://img.test/1.png")
        assert result["status"] == "not_configured"

    @pytest.mark.asyncio
    async def test_get_status_bridge_down(self, whatsapp) -> None:
        """get_status when bridge is down returns error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.return_value = mock_instance

            result = await whatsapp.get_status()
            assert result["ready"] is False

    @pytest.mark.asyncio
    async def test_get_qr_bridge_down(self, whatsapp) -> None:
        """get_qr when bridge is down returns error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.return_value = mock_instance

            result = await whatsapp.get_qr()
            assert result["status"] == "bridge_unavailable"

    @pytest.mark.asyncio
    async def test_process_webhook_self_message(self, whatsapp) -> None:
        """Processing a self-message webhook payload."""
        payload = {
            "from": "31612345678@c.us",
            "to": "31612345678@c.us",
            "fromMe": True,
            "isToSelf": True,
            "body": "Hello Koda2!",
            "type": "chat",
            "timestamp": 1707700000,
            "chatName": "You",
            "hasMedia": False,
        }
        result = await whatsapp.process_webhook(payload)
        assert result is not None
        assert result["text"] == "Hello Koda2!"
        assert result["is_self_message"] is True

    @pytest.mark.asyncio
    async def test_process_webhook_other_message(self, whatsapp) -> None:
        """Messages from others are ignored (not self-messages)."""
        payload = {
            "from": "31699999999@c.us",
            "to": "31612345678@c.us",
            "fromMe": False,
            "isToSelf": False,
            "body": "Hey!",
            "type": "chat",
            "timestamp": 1707700000,
        }
        result = await whatsapp.process_webhook(payload)
        assert result is None

    @pytest.mark.asyncio
    async def test_process_webhook_outgoing_to_other(self, whatsapp) -> None:
        """Outgoing messages to others are ignored."""
        payload = {
            "from": "31612345678@c.us",
            "to": "31699999999@c.us",
            "fromMe": True,
            "isToSelf": False,
            "body": "Hi there",
            "type": "chat",
            "timestamp": 1707700000,
        }
        result = await whatsapp.process_webhook(payload)
        assert result is None

    @pytest.mark.asyncio
    async def test_process_webhook_self_chat_via_wid(self, whatsapp) -> None:
        """Self-message detected via chatId matching myWid (Message yourself chat)."""
        payload = {
            "from": "31612345678@c.us",
            "to": "status@broadcast",
            "fromMe": True,
            "isToSelf": False,
            "body": "Note to self via Koda2",
            "type": "chat",
            "timestamp": 1707700000,
            "chatName": "You",
            "hasMedia": False,
            "myWid": "31612345678@c.us",
            "chatId": "31612345678@c.us",
        }
        result = await whatsapp.process_webhook(payload)
        assert result is not None
        assert result["text"] == "Note to self via Koda2"
        assert result["is_self_message"] is True

    @pytest.mark.asyncio
    async def test_process_webhook_self_chat_via_to_equals_wid(self, whatsapp) -> None:
        """Self-message detected via msg.to matching myWid."""
        payload = {
            "from": "some_other_id@c.us",
            "to": "31612345678@c.us",
            "fromMe": True,
            "isToSelf": False,
            "body": "Another self note",
            "type": "chat",
            "timestamp": 1707700000,
            "myWid": "31612345678@c.us",
            "chatId": "31612345678@c.us",
        }
        result = await whatsapp.process_webhook(payload)
        assert result is not None
        assert result["is_self_message"] is True

    @pytest.mark.asyncio
    async def test_get_messages_empty(self, whatsapp) -> None:
        """get_messages returns empty when bridge is down."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.return_value = mock_instance

            result = await whatsapp.get_messages()
            assert result == []

    @pytest.mark.asyncio
    async def test_get_contacts_empty(self, whatsapp) -> None:
        """get_contacts returns empty when bridge is down."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.return_value = mock_instance

            result = await whatsapp.get_contacts()
            assert result == []

    @pytest.mark.asyncio
    async def test_stop_no_process(self, whatsapp) -> None:
        """stop() is safe when no bridge process exists."""
        await whatsapp.stop()

    @pytest.mark.asyncio
    async def test_logout_bridge_down(self, whatsapp) -> None:
        """logout when bridge is down returns error."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_instance.post = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.return_value = mock_instance

            result = await whatsapp.logout()
            assert "error" in result
