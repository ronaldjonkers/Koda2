"""Unified WhatsApp media service for sending and receiving media.

Consolidates media sending (documents, images, audio, video) and
incoming media download/processing into a single service.
"""

import logging
import mimetypes
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx

from koda2.config import settings

logger = logging.getLogger(__name__)


class MediaType(str, Enum):
    DOCUMENT = "document"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    STICKER = "sticker"


MEDIA_DOWNLOAD_DIR = os.path.join(
    tempfile.gettempdir(), "koda2_whatsapp_media"
)

# Ensure download directory exists
os.makedirs(MEDIA_DOWNLOAD_DIR, exist_ok=True)


def _get_api_headers() -> dict:
    """Get WhatsApp Business API headers."""
    token = getattr(settings, "WHATSAPP_API_TOKEN", None) or getattr(
        settings, "WHATSAPP_TOKEN", None
    )
    if not token:
        raise ValueError("WHATSAPP_API_TOKEN is not configured")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _get_api_base_url() -> str:
    """Get WhatsApp Business API base URL."""
    phone_number_id = getattr(settings, "WHATSAPP_PHONE_NUMBER_ID", None)
    if not phone_number_id:
        raise ValueError("WHATSAPP_PHONE_NUMBER_ID is not configured")
    api_version = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")
    return f"https://graph.facebook.com/{api_version}/{phone_number_id}"


async def send_media(
    phone_number: str,
    media_type: str,
    media_url: Optional[str] = None,
    media_path: Optional[str] = None,
    caption: Optional[str] = None,
    filename: Optional[str] = None,
) -> dict:
    """Send media via WhatsApp Business API.

    Supports sending documents, images, audio, and video either by URL
    (link) or by first uploading a local file.

    Args:
        phone_number: Recipient phone number in international format.
        media_type: One of 'document', 'image', 'audio', 'video', 'sticker'.
        media_url: Public URL of the media to send (mutually exclusive with media_path).
        media_path: Local file path to upload and send (mutually exclusive with media_url).
        caption: Optional caption (supported for document, image, video).
        filename: Optional filename for documents.

    Returns:
        dict with 'success' bool and 'message_id' or 'error'.
    """
    # Validate media_type
    try:
        mt = MediaType(media_type.lower())
    except ValueError:
        valid = [m.value for m in MediaType]
        return {"success": False, "error": f"Invalid media_type '{media_type}'. Must be one of {valid}"}

    if not media_url and not media_path:
        return {"success": False, "error": "Either media_url or media_path must be provided"}

    if media_url and media_path:
        return {"success": False, "error": "Provide either media_url or media_path, not both"}

    logger.info(
        "Sending %s to %s (url=%s, path=%s)",
        mt.value,
        phone_number,
        media_url,
        media_path,
    )

    try:
        headers = _get_api_headers()
        base_url = _get_api_base_url()

        # If local file, upload first to get a media ID
        media_id = None
        if media_path:
            media_id = await _upload_media(media_path, headers, base_url)
            if not media_id:
                return {"success": False, "error": f"Failed to upload media from {media_path}"}

        # Build the media object
        media_object = {}
        if media_id:
            media_object["id"] = media_id
        elif media_url:
            media_object["link"] = media_url

        # Add caption where supported
        if caption and mt in (MediaType.DOCUMENT, MediaType.IMAGE, MediaType.VIDEO):
            media_object["caption"] = caption

        # Add filename for documents
        if mt == MediaType.DOCUMENT:
            if filename:
                media_object["filename"] = filename
            elif media_path:
                media_object["filename"] = os.path.basename(media_path)

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": mt.value,
            mt.value: media_object,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{base_url}/messages",
                headers=headers,
                json=payload,
            )

        if response.status_code in (200, 201):
            data = response.json()
            message_id = data.get("messages", [{}])[0].get("id", "unknown")
            logger.info(
                "Media sent successfully: type=%s, to=%s, message_id=%s",
                mt.value,
                phone_number,
                message_id,
            )
            return {"success": True, "message_id": message_id}
        else:
            error_detail = response.text
            logger.error(
                "Failed to send media: status=%d, response=%s",
                response.status_code,
                error_detail,
            )
            return {"success": False, "error": f"API error {response.status_code}: {error_detail}"}

    except Exception as e:
        logger.exception("Error sending media to %s: %s", phone_number, e)
        return {"success": False, "error": str(e)}


async def _upload_media(
    file_path: str, headers: dict, base_url: str
) -> Optional[str]:
    """Upload a local file to WhatsApp Media API and return the media ID."""
    path = Path(file_path)
    if not path.exists():
        logger.error("File not found: %s", file_path)
        return None

    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    upload_headers = {
        "Authorization": headers["Authorization"],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            with open(file_path, "rb") as f:
                response = await client.post(
                    f"{base_url}/media",
                    headers=upload_headers,
                    data={"messaging_product": "whatsapp", "type": mime_type},
                    files={"file": (path.name, f, mime_type)},
                )

        if response.status_code in (200, 201):
            media_id = response.json().get("id")
            logger.info("Uploaded media %s -> id=%s", file_path, media_id)
            return media_id
        else:
            logger.error(
                "Media upload failed: status=%d, response=%s",
                response.status_code,
                response.text,
            )
            return None
    except Exception as e:
        logger.exception("Error uploading media %s: %s", file_path, e)
        return None


async def download_incoming_media(
    media_id: str,
) -> Optional[dict]:
    """Download media from an incoming WhatsApp message.

    The WhatsApp Cloud API requires two steps:
    1. GET /{media_id} to retrieve the download URL
    2. GET the download URL with auth header to get the actual file

    Args:
        media_id: The media ID from the incoming webhook message.

    Returns:
        dict with 'file_path', 'mime_type', 'filename' or None on failure.
    """
    try:
        token = getattr(settings, "WHATSAPP_API_TOKEN", None) or getattr(
            settings, "WHATSAPP_TOKEN", None
        )
        if not token:
            logger.error("WHATSAPP_API_TOKEN not configured for media download")
            return None

        api_version = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")
        auth_headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Get media URL
            meta_response = await client.get(
                f"https://graph.facebook.com/{api_version}/{media_id}",
                headers=auth_headers,
            )

            if meta_response.status_code != 200:
                logger.error(
                    "Failed to get media metadata: status=%d, response=%s",
                    meta_response.status_code,
                    meta_response.text,
                )
                return None

            meta = meta_response.json()
            download_url = meta.get("url")
            mime_type = meta.get("mime_type", "application/octet-stream")

            if not download_url:
                logger.error("No download URL in media metadata: %s", meta)
                return None

            # Step 2: Download the actual file
            file_response = await client.get(
                download_url,
                headers=auth_headers,
            )

            if file_response.status_code != 200:
                logger.error(
                    "Failed to download media: status=%d",
                    file_response.status_code,
                )
                return None

        # Determine file extension from mime type
        ext = mimetypes.guess_extension(mime_type) or ""
        filename = f"{media_id}{ext}"
        file_path = os.path.join(MEDIA_DOWNLOAD_DIR, filename)

        with open(file_path, "wb") as f:
            f.write(file_response.content)

        file_size = os.path.getsize(file_path)
        logger.info(
            "Downloaded media: id=%s, mime=%s, size=%d, path=%s",
            media_id,
            mime_type,
            file_size,
            file_path,
        )

        return {
            "file_path": file_path,
            "mime_type": mime_type,
            "filename": filename,
            "file_size": file_size,
            "media_id": media_id,
        }

    except Exception as e:
        logger.exception("Error downloading media %s: %s", media_id, e)
        return None


async def process_incoming_media(message: dict) -> Optional[dict]:
    """Process media from an incoming WhatsApp webhook message.

    Extracts the media ID from the message, downloads it, and returns
    metadata including the local file path for further processing.

    Args:
        message: The message object from the WhatsApp webhook payload.

    Returns:
        dict with media info including 'file_path', 'mime_type', 'media_type',
        'caption', or None if no media found.
    """
    # Check each media type
    for mt in MediaType:
        media_obj = message.get(mt.value)
        if media_obj:
            media_id = media_obj.get("id")
            if not media_id:
                logger.warning("Media object found but no ID: %s", media_obj)
                return None

            caption = media_obj.get("caption")
            original_filename = media_obj.get("filename")

            result = await download_incoming_media(media_id)
            if result:
                result["media_type"] = mt.value
                result["caption"] = caption
                if original_filename:
                    result["original_filename"] = original_filename
                return result
            return None

    return None


def get_send_media_tool_definition() -> dict:
    """Return the tool/function definition for AI function calling."""
    return {
        "type": "function",
        "function": {
            "name": "send_whatsapp_media",
            "description": (
                "Send a media file (document, image, audio, video) to a WhatsApp user. "
                "Use this when the user asks you to send a file, photo, document, or any media."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "Recipient phone number in international format (e.g. +1234567890)",
                    },
                    "media_type": {
                        "type": "string",
                        "enum": ["document", "image", "audio", "video"],
                        "description": "Type of media to send",
                    },
                    "media_url": {
                        "type": "string",
                        "description": "Public URL of the media file to send",
                    },
                    "media_path": {
                        "type": "string",
                        "description": "Local file path of the media to upload and send",
                    },
                    "caption": {
                        "type": "string",
                        "description": "Optional caption for the media (supported for document, image, video)",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional filename for documents",
                    },
                },
                "required": ["phone_number", "media_type"],
            },
        },
    }


async def handle_send_media_tool_call(arguments: dict) -> dict:
    """Handle the send_whatsapp_media tool call from the AI.

    Args:
        arguments: The parsed arguments from the function call.

    Returns:
        dict result to return to the AI.
    """
    phone_number = arguments.get("phone_number")
    media_type = arguments.get("media_type")
    media_url = arguments.get("media_url")
    media_path = arguments.get("media_path")
    caption = arguments.get("caption")
    filename = arguments.get("filename")

    if not phone_number:
        return {"success": False, "error": "phone_number is required"}
    if not media_type:
        return {"success": False, "error": "media_type is required"}

    return await send_media(
        phone_number=phone_number,
        media_type=media_type,
        media_url=media_url,
        media_path=media_path,
        caption=caption,
        filename=filename,
    )
