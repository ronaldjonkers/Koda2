"""WhatsApp media sending via Business API."""
import logging
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)

MEDIA_TYPES = {"document", "image", "audio", "video", "sticker"}


async def send_media(
    phone_number_id: str,
    recipient: str,
    media_type: str,
    access_token: str,
    media_url: Optional[str] = None,
    media_id: Optional[str] = None,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
    api_version: str = "v17.0",
) -> Dict[str, Any]:
    """Send a media message to a WhatsApp user.

    Args:
        phone_number_id: The WhatsApp Business phone number ID.
        recipient: Recipient phone number in international format.
        media_type: One of 'document', 'image', 'audio', 'video', 'sticker'.
        access_token: WhatsApp Business API access token.
        media_url: Public URL of the media file (mutually exclusive with media_id).
        media_id: Previously uploaded media ID (mutually exclusive with media_url).
        caption: Optional caption (supported for image and document).
        filename: Optional filename (for document type).
        api_version: Graph API version.

    Returns:
        API response dict on success, or error dict.
    """
    if media_type not in MEDIA_TYPES:
        return {"error": f"Unsupported media_type '{media_type}'. Use one of {MEDIA_TYPES}"}

    if not media_url and not media_id:
        return {"error": "Either media_url or media_id must be provided"}

    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Build media object
    media_obj: Dict[str, Any] = {}
    if media_id:
        media_obj["id"] = media_id
    else:
        media_obj["link"] = media_url

    if caption and media_type in ("image", "document"):
        media_obj["caption"] = caption
    if filename and media_type == "document":
        media_obj["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": media_type,
        media_type: media_obj,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            result = resp.json()
            logger.info(
                "Sent %s to %s via phone_number_id %s",
                media_type, recipient, phone_number_id,
            )
            return result
    except httpx.HTTPStatusError as exc:
        body = exc.response.text
        logger.error(
            "HTTP %s sending %s to %s: %s",
            exc.response.status_code, media_type, recipient, body,
        )
        return {"error": f"HTTP {exc.response.status_code}", "detail": body}
    except Exception as exc:
        logger.error("Failed to send %s to %s: %s", media_type, recipient, exc)
        return {"error": str(exc)}


async def upload_and_send_media(
    phone_number_id: str,
    recipient: str,
    media_type: str,
    file_bytes: bytes,
    mime_type: str,
    access_token: str,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
    api_version: str = "v17.0",
) -> Dict[str, Any]:
    """Upload media to WhatsApp servers then send it.

    Useful when you have raw bytes rather than a public URL.
    """
    upload_url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/media"
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {
                "file": (filename or "file", file_bytes, mime_type),
            }
            data = {
                "messaging_product": "whatsapp",
                "type": mime_type,
            }
            resp = await client.post(
                upload_url, headers=headers, data=data, files=files
            )
            resp.raise_for_status()
            media_id = resp.json().get("id")
            if not media_id:
                return {"error": "Upload succeeded but no media ID returned"}
    except Exception as exc:
        logger.error("Media upload failed: %s", exc)
        return {"error": f"Upload failed: {exc}"}

    return await send_media(
        phone_number_id=phone_number_id,
        recipient=recipient,
        media_type=media_type,
        access_token=access_token,
        media_id=media_id,
        caption=caption,
        filename=filename,
        api_version=api_version,
    )
