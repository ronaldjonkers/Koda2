"""WhatsApp media sending via Business Cloud API."""

import os
import mimetypes
import logging
from typing import Optional

import httpx

from koda2.config import settings

logger = logging.getLogger(__name__)

# Supported MIME types per media category
SUPPORTED_MEDIA_TYPES = {
    "image": [
        "image/jpeg",
        "image/png",
    ],
    "document": [
        "application/pdf",
        "text/plain",
    ],
    "video": [
        "video/mp4",
        "video/3gpp",
    ],
    "audio": [
        "audio/aac",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
    ],
}

# Reverse lookup: mime_type -> media category
MIME_TO_CATEGORY = {}
for category, mimes in SUPPORTED_MEDIA_TYPES.items():
    for mime in mimes:
        MIME_TO_CATEGORY[mime] = category


def _get_api_base() -> str:
    """Return the WhatsApp Cloud API base URL."""
    version = getattr(settings, "WHATSAPP_API_VERSION", "v21.0")
    phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
    return f"https://graph.facebook.com/{version}/{phone_number_id}"


def _get_headers(content_type: Optional[str] = None) -> dict:
    """Return authorization headers for the WhatsApp API."""
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _resolve_media_type(media_type: str, media_url_or_path: str) -> tuple[str, str]:
    """Resolve the media category and MIME type.

    Args:
        media_type: One of 'image', 'document', 'video', 'audio', or a MIME type string.
        media_url_or_path: The file path or URL (used for MIME guessing).

    Returns:
        Tuple of (category, mime_type).

    Raises:
        ValueError: If the media type is unsupported.
    """
    # If media_type is already a category name
    if media_type in SUPPORTED_MEDIA_TYPES:
        # Guess MIME from the file extension
        guessed_mime, _ = mimetypes.guess_type(media_url_or_path)
        if guessed_mime and guessed_mime in SUPPORTED_MEDIA_TYPES[media_type]:
            return media_type, guessed_mime
        # Default to first supported MIME for the category
        return media_type, SUPPORTED_MEDIA_TYPES[media_type][0]

    # If media_type is a MIME type string
    if media_type in MIME_TO_CATEGORY:
        return MIME_TO_CATEGORY[media_type], media_type

    raise ValueError(
        f"Unsupported media_type '{media_type}'. "
        f"Supported categories: {list(SUPPORTED_MEDIA_TYPES.keys())}. "
        f"Supported MIME types: {list(MIME_TO_CATEGORY.keys())}."
    )


def _is_url(path: str) -> bool:
    """Check if the string is a URL."""
    return path.startswith("http://") or path.startswith("https://")


async def _upload_media(file_path: str, mime_type: str) -> str:
    """Upload a local file to WhatsApp Media API and return the media ID.

    Args:
        file_path: Absolute or relative path to the local file.
        mime_type: The MIME type of the file.

    Returns:
        The media ID string from the WhatsApp API.

    Raises:
        FileNotFoundError: If the file does not exist.
        RuntimeError: If the upload fails.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Media file not found: {file_path}")

    url = f"{_get_api_base()}/media"
    filename = os.path.basename(file_path)

    logger.info("Uploading media file '%s' (type=%s) to WhatsApp API", filename, mime_type)

    async with httpx.AsyncClient(timeout=60.0) as client:
        with open(file_path, "rb") as f:
            files = {
                "file": (filename, f, mime_type),
            }
            data = {
                "messaging_product": "whatsapp",
                "type": mime_type,
            }
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"},
                files=files,
                data=data,
            )

    if resp.status_code != 200:
        logger.error("WhatsApp media upload failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"WhatsApp media upload failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    media_id = result.get("id")
    if not media_id:
        raise RuntimeError(f"WhatsApp media upload returned no ID: {result}")

    logger.info("Media uploaded successfully, media_id=%s", media_id)
    return media_id


async def send_media(
    to: str,
    media_type: str,
    media_url_or_path: str,
    caption: str = "",
) -> dict:
    """Send media (image, document, video, audio) to a WhatsApp recipient.

    For local file paths, the file is first uploaded to the WhatsApp Media API.
    For URLs, the URL is sent directly.

    Args:
        to: Recipient phone number in international format (e.g. '1234567890').
        media_type: Media category ('image', 'document', 'video', 'audio') or
                    a MIME type string (e.g. 'application/pdf').
        media_url_or_path: A URL (http/https) or local file path.
        caption: Optional caption text (supported for image and document).

    Returns:
        The WhatsApp API response as a dict.

    Raises:
        ValueError: If media_type is unsupported.
        FileNotFoundError: If a local file path doesn't exist.
        RuntimeError: If the API call fails.
    """
    category, mime_type = _resolve_media_type(media_type, media_url_or_path)

    logger.info(
        "Sending %s media to %s (mime=%s, source=%s, caption=%s)",
        category, to, mime_type,
        "url" if _is_url(media_url_or_path) else "file",
        repr(caption[:50]) if caption else "none",
    )

    # Build the media object
    media_object: dict = {}

    if _is_url(media_url_or_path):
        media_object["link"] = media_url_or_path
    else:
        # Upload local file first
        media_id = await _upload_media(media_url_or_path, mime_type)
        media_object["id"] = media_id

    # Add caption if supported and provided
    if caption and category in ("image", "document", "video"):
        media_object["caption"] = caption

    # For documents, include filename
    if category == "document":
        filename = os.path.basename(media_url_or_path) if not _is_url(media_url_or_path) else ""
        if filename:
            media_object["filename"] = filename

    # Build the message payload
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": category,
        category: media_object,
    }

    url = f"{_get_api_base()}/messages"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            headers=_get_headers(content_type="application/json"),
            json=payload,
        )

    if resp.status_code not in (200, 201):
        logger.error("WhatsApp send_media failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"WhatsApp send_media failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    logger.info("Media sent successfully to %s: %s", to, result.get("messages", []))
    return result
