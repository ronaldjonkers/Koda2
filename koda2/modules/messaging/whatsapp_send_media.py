"""WhatsApp media sending via the WhatsApp Business API.

Supports sending images, documents, audio, and video to recipients.
"""

import logging
import httpx
from typing import Optional

from koda2.config import get_settings

logger = logging.getLogger(__name__)

SUPPORTED_MEDIA_TYPES = {"image", "document", "audio", "video"}

SUPPORTED_DOCUMENT_EXTENSIONS = {
    ".pdf", ".txt", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".csv", ".rtf", ".odt", ".ods", ".odp",
}

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".amr", ".aac", ".m4a"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".3gp"}


async def send_whatsapp_media(
    recipient: str,
    media_type: str,
    media_url: Optional[str] = None,
    media_id: Optional[str] = None,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
) -> dict:
    """Send media to a WhatsApp recipient via the WhatsApp Business API.

    Args:
        recipient: Phone number in international format (e.g. "+1234567890").
        media_type: One of 'image', 'document', 'audio', 'video'.
        media_url: Public URL of the media file. Either media_url or media_id is required.
        media_id: WhatsApp media ID (if already uploaded). Either media_url or media_id is required.
        caption: Optional caption (supported for image and document types).
        filename: Optional filename (used for document type).

    Returns:
        dict with 'success' bool and 'message' or 'error' string.
    """
    settings = get_settings()

    # --- Validation ---
    media_type = media_type.lower().strip()
    if media_type not in SUPPORTED_MEDIA_TYPES:
        return {
            "success": False,
            "error": f"Unsupported media type '{media_type}'. Must be one of: {', '.join(sorted(SUPPORTED_MEDIA_TYPES))}.",
        }

    if not media_url and not media_id:
        return {
            "success": False,
            "error": "Either media_url or media_id must be provided.",
        }

    recipient = recipient.strip().lstrip("+")
    if not recipient.isdigit() or len(recipient) < 7:
        return {
            "success": False,
            "error": f"Invalid recipient phone number: '{recipient}'.",
        }

    whatsapp_token = getattr(settings, "WHATSAPP_API_TOKEN", None) or getattr(settings, "WHATSAPP_TOKEN", None)
    phone_number_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None)

    if not whatsapp_token or not phone_number_id:
        logger.error("WhatsApp API credentials not configured (WHATSAPP_API_TOKEN / WHATSAPP_PHONE_NUMBER_ID)")
        return {
            "success": False,
            "error": "WhatsApp API credentials are not configured. Please set WHATSAPP_API_TOKEN and WHATSAPP_PHONE_NUMBER_ID.",
        }

    api_version = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")
    base_url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"

    # --- Build payload ---
    media_object: dict = {}
    if media_id:
        media_object["id"] = media_id
    elif media_url:
        media_object["link"] = media_url

    # Caption is supported for image and document
    if caption and media_type in ("image", "document"):
        media_object["caption"] = caption

    # Filename is relevant for documents
    if filename and media_type == "document":
        media_object["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": media_type,
        media_type: media_object,
    }

    headers = {
        "Authorization": f"Bearer {whatsapp_token}",
        "Content-Type": "application/json",
    }

    # --- Send request ---
    try:
        logger.info(
            "Sending WhatsApp %s to %s (url=%s, id=%s, filename=%s)",
            media_type,
            recipient,
            media_url,
            media_id,
            filename,
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(base_url, json=payload, headers=headers)

        if response.status_code in (200, 201):
            data = response.json()
            message_id = None
            if "messages" in data and data["messages"]:
                message_id = data["messages"][0].get("id")
            logger.info(
                "WhatsApp %s sent successfully to %s (message_id=%s)",
                media_type,
                recipient,
                message_id,
            )
            return {
                "success": True,
                "message": f"{media_type.capitalize()} sent successfully to +{recipient}.",
                "message_id": message_id,
            }
        else:
            error_body = response.text
            logger.error(
                "WhatsApp media send failed: status=%s body=%s",
                response.status_code,
                error_body,
            )
            # Try to extract a human-readable error
            try:
                err_data = response.json()
                err_msg = (
                    err_data.get("error", {}).get("message")
                    or err_data.get("error", {}).get("error_data", {}).get("details")
                    or error_body
                )
            except Exception:
                err_msg = error_body

            return {
                "success": False,
                "error": f"Failed to send {media_type}: {err_msg}",
            }

    except httpx.TimeoutException:
        logger.error("Timeout sending WhatsApp %s to %s", media_type, recipient)
        return {
            "success": False,
            "error": f"Request timed out while sending {media_type}. Please try again.",
        }
    except Exception as exc:
        logger.exception("Unexpected error sending WhatsApp %s to %s", media_type, recipient)
        return {
            "success": False,
            "error": f"Unexpected error sending {media_type}: {str(exc)}",
        }
