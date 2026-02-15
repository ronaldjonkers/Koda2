"""Handle incoming WhatsApp media messages.

Downloads media from the WhatsApp Cloud API and provides structured
context that can be injected into LLM conversations.
"""

import aiohttp
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Directory for downloaded media
MEDIA_DOWNLOAD_DIR = os.path.join(tempfile.gettempdir(), "koda2_whatsapp_media")

MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/aac": ".aac",
    "video/mp4": ".mp4",
    "video/3gpp": ".3gp",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


def _ensure_download_dir():
    """Ensure the media download directory exists."""
    os.makedirs(MEDIA_DOWNLOAD_DIR, exist_ok=True)


async def download_whatsapp_media(
    media_id: str,
    phone_number_id: str = None,
    access_token: str = None,
) -> Optional[dict]:
    """Download media from WhatsApp Cloud API by media ID.

    Args:
        media_id: The WhatsApp media ID from the webhook payload.
        phone_number_id: WhatsApp phone number ID. Falls back to config.
        access_token: WhatsApp access token. Falls back to config.

    Returns:
        dict with keys: 'file_path', 'mime_type', 'media_id', 'filename' or None on failure.
    """
    from koda2.config import get_config

    config = get_config()
    access_token = access_token or getattr(config, "WHATSAPP_ACCESS_TOKEN", None) or config.config.get("whatsapp", {}).get("access_token")

    if not access_token:
        logger.error("WhatsApp access_token not configured for media download")
        return None

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        async with aiohttp.ClientSession() as session:
            # Step 1: Get the media URL from the media ID
            media_url_endpoint = f"https://graph.facebook.com/v18.0/{media_id}"
            async with session.get(media_url_endpoint, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Failed to get media URL for {media_id}: {resp.status} {body}")
                    return None
                media_info = await resp.json()

            download_url = media_info.get("url")
            mime_type = media_info.get("mime_type", "application/octet-stream")

            if not download_url:
                logger.error(f"No download URL in media info for {media_id}")
                return None

            # Step 2: Download the actual media binary
            async with session.get(download_url, headers=headers) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to download media from {download_url}: {resp.status}")
                    return None

                _ensure_download_dir()
                ext = MIME_EXTENSIONS.get(mime_type, "")
                filename = f"{media_id}{ext}"
                file_path = os.path.join(MEDIA_DOWNLOAD_DIR, filename)

                with open(file_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)

            file_size = os.path.getsize(file_path)
            logger.info(f"Downloaded media {media_id}: {file_path} ({file_size} bytes, {mime_type})")

            return {
                "file_path": file_path,
                "mime_type": mime_type,
                "media_id": media_id,
                "filename": filename,
                "file_size": file_size,
            }

    except Exception as e:
        logger.exception(f"Error downloading media {media_id}: {e}")
        return None


def build_media_context(
    media_info: dict,
    media_type: str,
    caption: str = None,
    sender: str = None,
) -> str:
    """Build a text context string describing received media for the LLM.

    Args:
        media_info: Dict returned by download_whatsapp_media.
        media_type: The WhatsApp message type ('image', 'document', 'audio', 'video').
        caption: Optional caption sent with the media.
        sender: Optional sender phone number.

    Returns:
        A context string to inject into the LLM conversation.
    """
    parts = []
    parts.append(f"[Received {media_type} via WhatsApp]")

    if sender:
        parts.append(f"From: {sender}")

    if media_info:
        parts.append(f"File: {media_info.get('filename', 'unknown')}")
        parts.append(f"MIME type: {media_info.get('mime_type', 'unknown')}")
        size = media_info.get('file_size', 0)
        if size > 0:
            if size > 1024 * 1024:
                parts.append(f"Size: {size / (1024*1024):.1f} MB")
            else:
                parts.append(f"Size: {size / 1024:.1f} KB")
        parts.append(f"Local path: {media_info.get('file_path', 'N/A')}")

    if caption:
        parts.append(f"Caption: {caption}")

    return "\n".join(parts)


async def extract_media_from_webhook_message(message: dict) -> Optional[dict]:
    """Extract and download media from a WhatsApp webhook message object.

    Args:
        message: The message object from the WhatsApp webhook payload.

    Returns:
        dict with 'media_info', 'media_type', 'caption', 'context' keys, or None.
    """
    media_types = ["image", "audio", "video", "document"]

    for mtype in media_types:
        media_obj = message.get(mtype)
        if media_obj:
            media_id = media_obj.get("id")
            if not media_id:
                logger.warning(f"Received {mtype} message without media ID")
                return None

            caption = media_obj.get("caption")
            sender = message.get("from", "unknown")

            logger.info(f"Processing incoming {mtype} from {sender}, media_id={media_id}")

            media_info = await download_whatsapp_media(media_id)

            context = build_media_context(
                media_info=media_info,
                media_type=mtype,
                caption=caption,
                sender=sender,
            )

            return {
                "media_info": media_info,
                "media_type": mtype,
                "caption": caption,
                "context": context,
                "sender": sender,
            }

    return None
