"""WhatsApp Business API integration."""

from __future__ import annotations

from typing import Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from executiveai.config import get_settings
from executiveai.logging_config import get_logger

logger = get_logger(__name__)


class WhatsAppBot:
    """WhatsApp Business API client for sending and receiving messages."""

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.whatsapp_api_url and self._settings.whatsapp_api_token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.whatsapp_api_token}",
            "Content-Type": "application/json",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send_message(self, to: str, text: str) -> dict[str, Any]:
        """Send a text message via WhatsApp."""
        if not self.is_configured:
            logger.warning("whatsapp_not_configured")
            return {"status": "not_configured"}

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._settings.whatsapp_api_url}/messages",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            logger.info("whatsapp_message_sent", to=to)
            return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send_media(
        self, to: str, media_url: str, media_type: str = "image", caption: str = "",
    ) -> dict[str, Any]:
        """Send a media message (image, document, audio, video)."""
        if not self.is_configured:
            return {"status": "not_configured"}

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": media_type,
            media_type: {"link": media_url},
        }
        if caption and media_type in ("image", "video", "document"):
            payload[media_type]["caption"] = caption

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._settings.whatsapp_api_url}/messages",
                json=payload,
                headers=self._headers(),
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send_template(
        self, to: str, template_name: str, language: str = "en",
        parameters: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Send a pre-approved WhatsApp template message."""
        if not self.is_configured:
            return {"status": "not_configured"}

        template: dict[str, Any] = {
            "name": template_name,
            "language": {"code": language},
        }
        if parameters:
            template["components"] = parameters

        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": template,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._settings.whatsapp_api_url}/messages",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    async def process_webhook(self, payload: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process incoming WhatsApp webhook payload."""
        try:
            entry = payload.get("entry", [{}])[0]
            changes = entry.get("changes", [{}])[0]
            value = changes.get("value", {})
            messages = value.get("messages", [])

            if not messages:
                return None

            msg = messages[0]
            result = {
                "from": msg.get("from", ""),
                "type": msg.get("type", ""),
                "timestamp": msg.get("timestamp", ""),
            }

            if msg["type"] == "text":
                result["text"] = msg["text"]["body"]
            elif msg["type"] in ("image", "document", "audio", "video"):
                media = msg[msg["type"]]
                result["media_id"] = media.get("id", "")
                result["mime_type"] = media.get("mime_type", "")
                result["caption"] = media.get("caption", "")

            logger.info("whatsapp_message_received", from_=result["from"], type=result["type"])
            return result

        except (KeyError, IndexError) as exc:
            logger.error("whatsapp_webhook_parse_error", error=str(exc))
            return None
