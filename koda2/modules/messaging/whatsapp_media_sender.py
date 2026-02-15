"""WhatsApp media sending service.

Provides a unified interface for sending media (images, documents, audio, video)
via the WhatsApp Business API. Supports both media URLs and local file uploads.
"""

import os
import logging
import mimetypes
from pathlib import Path
from typing import Optional

import httpx

from koda2.config import get_settings

logger = logging.getLogger(__name__)

MEDIA_TYPES = {"image", "document", "audio", "video"}

# Mapping of media type to common MIME types for validation
MEDIA_MIME_PREFIXES = {
    "image": ["image/"],
    "audio": ["audio/"],
    "video": ["video/"],
    "document": [],  # documents accept any MIME type
}


class WhatsAppMediaSendError(Exception):
    """Raised when media sending fails."""


async def upload_media_file(
    file_path: str,
    mime_type: Optional[str] = None,
) -> str:
    """Upload a local file to WhatsApp media endpoint and return the media ID.

    Args:
        file_path: Absolute or relative path to the file.
        mime_type: Optional MIME type override. Auto-detected if not provided.

    Returns:
        The media ID string from WhatsApp.

    Raises:
        WhatsAppMediaSendError: If upload fails.
    """
    settings = get_settings()
    path = Path(file_path)

    if not path.exists():
        raise WhatsAppMediaSendError(f"File not found: {file_path}")

    if not mime_type:
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "application/octet-stream"

    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    api_version = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")

    if not phone_number_id or not access_token:
        raise WhatsAppMediaSendError(
            "WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN must be configured"
        )

    upload_url = (
        f"https://graph.facebook.com/{api_version}/{phone_number_id}/media"
    )

    headers = {"Authorization": f"Bearer {access_token}"}

    logger.info("Uploading media file %s (%s) to WhatsApp", path.name, mime_type)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(path, "rb") as f:
                files = {
                    "file": (path.name, f, mime_type),
                }
                data = {
                    "messaging_product": "whatsapp",
                    "type": mime_type,
                }
                resp = await client.post(
                    upload_url, headers=headers, files=files, data=data
                )

        if resp.status_code != 200:
            logger.error(
                "WhatsApp media upload failed: %s %s", resp.status_code, resp.text
            )
            raise WhatsAppMediaSendError(
                f"Media upload failed ({resp.status_code}): {resp.text}"
            )

        result = resp.json()
        media_id = result.get("id")
        if not media_id:
            raise WhatsAppMediaSendError(
                f"No media ID in upload response: {result}"
            )

        logger.info("Media uploaded successfully, ID: %s", media_id)
        return media_id

    except httpx.HTTPError as exc:
        logger.error("HTTP error during media upload: %s", exc)
        raise WhatsAppMediaSendError(f"HTTP error during upload: {exc}") from exc


def _build_media_object(
    media_type: str,
    media_url: Optional[str] = None,
    media_id: Optional[str] = None,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
) -> dict:
    """Build the media object for the WhatsApp messages payload."""
    media_obj: dict = {}

    if media_id:
        media_obj["id"] = media_id
    elif media_url:
        media_obj["link"] = media_url
    else:
        raise WhatsAppMediaSendError(
            "Either media_url or media_id must be provided"
        )

    # Caption is supported for image, video, and document
    if caption and media_type in {"image", "video", "document"}:
        media_obj["caption"] = caption

    # Filename only applies to documents
    if filename and media_type == "document":
        media_obj["filename"] = filename

    return media_obj


async def send_whatsapp_media(
    recipient: str,
    media_type: str,
    media_source: str,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
) -> dict:
    """Send media via WhatsApp Business API.

    This is the main entry point, designed to be registered as an AI tool.

    Args:
        recipient: Phone number in international format (e.g. "+1234567890").
        media_type: One of 'image', 'document', 'audio', 'video'.
        media_source: A URL (http/https) or a local file path.
        caption: Optional caption text (image, video, document only).
        filename: Optional display filename (document only).

    Returns:
        Dict with 'success', 'message_id', and details.

    Raises:
        WhatsAppMediaSendError: On any failure.
    """
    # --- Validate media type ---
    media_type = media_type.lower().strip()
    if media_type not in MEDIA_TYPES:
        raise WhatsAppMediaSendError(
            f"Invalid media_type '{media_type}'. Must be one of: {MEDIA_TYPES}"
        )

    # --- Normalize recipient ---
    recipient = recipient.strip().replace(" ", "").replace("-", "")
    if recipient.startswith("+"):
        recipient = recipient[1:]

    # --- Determine if source is URL or file path ---
    is_url = media_source.startswith("http://") or media_source.startswith("https://")

    media_id: Optional[str] = None
    media_url: Optional[str] = None

    if is_url:
        media_url = media_source
        logger.info(
            "Sending %s to %s via URL: %s", media_type, recipient, media_url
        )
    else:
        # Local file — upload first
        logger.info(
            "Uploading local file %s before sending as %s to %s",
            media_source,
            media_type,
            recipient,
        )
        media_id = await upload_media_file(media_source)

        # Default filename for documents from the file path
        if media_type == "document" and not filename:
            filename = Path(media_source).name

    # --- Build API payload ---
    settings = get_settings()
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    access_token = settings.WHATSAPP_ACCESS_TOKEN
    api_version = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")

    if not phone_number_id or not access_token:
        raise WhatsAppMediaSendError(
            "WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN must be configured"
        )

    messages_url = (
        f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    )

    media_obj = _build_media_object(
        media_type=media_type,
        media_url=media_url,
        media_id=media_id,
        caption=caption,
        filename=filename,
    )

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": media_type,
        media_type: media_obj,
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    logger.info("Sending %s message to %s", media_type, recipient)
    logger.debug("Payload: %s", payload)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(messages_url, headers=headers, json=payload)

        if resp.status_code not in (200, 201):
            logger.error(
                "WhatsApp send media failed: %s %s", resp.status_code, resp.text
            )
            raise WhatsAppMediaSendError(
                f"Send failed ({resp.status_code}): {resp.text}"
            )

        result = resp.json()
        message_id = None
        messages = result.get("messages", [])
        if messages:
            message_id = messages[0].get("id")

        logger.info(
            "Media sent successfully. Type=%s, Recipient=%s, MessageID=%s",
            media_type,
            recipient,
            message_id,
        )

        return {
            "success": True,
            "message_id": message_id,
            "media_type": media_type,
            "recipient": recipient,
        }

    except httpx.HTTPError as exc:
        logger.error("HTTP error sending media: %s", exc)
        raise WhatsAppMediaSendError(f"HTTP error sending media: {exc}") from exc
