"""Tests for WhatsApp send_media and incoming media handling."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open


class FakeResponse:
    """Fake aiohttp response."""

    def __init__(self, status, json_data=None, text_data="", content_type="application/octet-stream"):
        self.status = status
        self._json = json_data or {}
        self._text = text_data
        self.content_type = content_type

    async def json(self):
        return self._json

    async def text(self):
        return self._text

    async def read(self):
        return b"fake-file-bytes"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class FakeSession:
    """Fake aiohttp.ClientSession."""

    def __init__(self, responses):
        self._responses = responses
        self._call_idx = 0

    def post(self, *args, **kwargs):
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp

    def get(self, *args, **kwargs):
        resp = self._responses[self._call_idx]
        self._call_idx += 1
        return resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def whatsapp_config():
    return {
        "whatsapp_phone_number_id": "123456",
        "whatsapp_access_token": "test-token",
        "whatsapp_api_version": "v17.0",
    }


class TestSendMedia:
    """Tests for the send_media method."""

    def test_invalid_media_type(self, whatsapp_config):
        """send_media should reject invalid media types."""
        from koda2.modules.messaging.whatsapp_bot import WhatsAppBot

        bot = WhatsAppBot(whatsapp_config)
        result = asyncio.get_event_loop().run_until_complete(
            bot.send_media(to="1234567890", media_type="gif")
        )
        assert result is False

    def test_no_media_source(self, whatsapp_config):
        """send_media should reject when neither url nor path is given."""
        from koda2.modules.messaging.whatsapp_bot import WhatsAppBot

        bot = WhatsAppBot(whatsapp_config)
        result = asyncio.get_event_loop().run_until_complete(
            bot.send_media(to="1234567890", media_type="document")
        )
        assert result is False

    @patch("aiohttp.ClientSession")
    def test_send_media_with_path_success(self, mock_session_cls, whatsapp_config, tmp_path):
        """send_media should upload then send when given a valid file path."""
        from koda2.modules.messaging.whatsapp_bot import WhatsAppBot

        # Create a temp file
        test_file = tmp_path / "test.pdf"
        test_file.write_bytes(b"%PDF-1.4 fake content")

        upload_resp = FakeResponse(200, json_data={"id": "media-id-123"})
        send_resp = FakeResponse(200, json_data={"messages": [{"id": "msg-1"}]})

        session_instance = FakeSession([upload_resp, send_resp])
        mock_session_cls.return_value = session_instance

        bot = WhatsAppBot(whatsapp_config)
        result = asyncio.get_event_loop().run_until_complete(
            bot.send_media(
                to="1234567890",
                media_type="document",
                media_path=str(test_file),
                caption="Here is your PDF",
                filename="report.pdf",
            )
        )
        assert result is True

    @patch("aiohttp.ClientSession")
    def test_send_media_upload_failure_retries(self, mock_session_cls, whatsapp_config, tmp_path):
        """send_media should retry on upload failure."""
        from koda2.modules.messaging.whatsapp_bot import WhatsAppBot

        test_file = tmp_path / "test.png"
        test_file.write_bytes(b"fake-png")

        fail_resp = FakeResponse(500, text_data="Server Error")
        fail_resp2 = FakeResponse(500, text_data="Server Error")
        fail_resp3 = FakeResponse(500, text_data="Server Error")

        session_instance = FakeSession([fail_resp, fail_resp2, fail_resp3])
        mock_session_cls.return_value = session_instance

        bot = WhatsAppBot(whatsapp_config)
        result = asyncio.get_event_loop().run_until_complete(
            bot.send_media(
                to="1234567890",
                media_type="image",
                media_path=str(test_file),
            )
        )
        assert result is False


class TestDownloadWhatsAppMedia:
    """Tests for the download helper."""

    @patch("aiohttp.ClientSession")
    def test_download_success(self, mock_session_cls):
        from koda2.modules.messaging.whatsapp_media_download import download_whatsapp_media

        url_resp = FakeResponse(200, json_data={"url": "https://example.com/media/file"})
        dl_resp = FakeResponse(200)

        session_instance = FakeSession([url_resp, dl_resp])
        mock_session_cls.return_value = session_instance

        result = asyncio.get_event_loop().run_until_complete(
            download_whatsapp_media(
                media_id="media-123",
                access_token="test-token",
            )
        )
        assert result == b"fake-file-bytes"

    def test_download_missing_params(self):
        from koda2.modules.messaging.whatsapp_media_download import download_whatsapp_media

        result = asyncio.get_event_loop().run_until_complete(
            download_whatsapp_media(media_id="", access_token="token")
        )
        assert result is None

        result = asyncio.get_event_loop().run_until_complete(
            download_whatsapp_media(media_id="id", access_token="")
        )
        assert result is None
