"""LLM tool for sending WhatsApp media messages."""
import logging
from typing import Any, Dict

from koda2.modules.messaging.whatsapp_media_send import send_media

logger = logging.getLogger(__name__)

# OpenAI-style function/tool schema
SEND_WHATSAPP_MEDIA_TOOL = {
    "type": "function",
    "function": {
        "name": "send_whatsapp_media",
        "description": (
            "Send a media file (image, document, PDF, audio, video) to a "
            "WhatsApp user. Provide either a public media_url or a "
            "previously uploaded media_id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Recipient phone number in international format, e.g. +1234567890",
                },
                "media_type": {
                    "type": "string",
                    "enum": ["document", "image", "audio", "video"],
                    "description": "Type of media to send",
                },
                "media_url": {
                    "type": "string",
                    "description": "Public URL of the media file",
                },
                "media_id": {
                    "type": "string",
                    "description": "WhatsApp media ID (if previously uploaded)",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption for the media",
                },
                "filename": {
                    "type": "string",
                    "description": "Filename shown to recipient (for documents)",
                },
            },
            "required": ["recipient", "media_type"],
        },
    },
}


async def handle_send_whatsapp_media(
    args: Dict[str, Any],
    phone_number_id: str,
    access_token: str,
) -> Dict[str, Any]:
    """Execute the send_whatsapp_media tool call.

    Args:
        args: Parsed arguments from the LLM tool call.
        phone_number_id: WhatsApp Business phone number ID.
        access_token: WhatsApp Business API token.

    Returns:
        Result dict from the WhatsApp API.
    """
    recipient = args.get("recipient", "")
    media_type = args.get("media_type", "document")
    media_url = args.get("media_url")
    media_id = args.get("media_id")
    caption = args.get("caption")
    filename = args.get("filename")

    if not recipient:
        return {"error": "recipient is required"}

    logger.info(
        "LLM tool: sending %s to %s (url=%s, id=%s)",
        media_type, recipient, media_url, media_id,
    )

    result = await send_media(
        phone_number_id=phone_number_id,
        recipient=recipient,
        media_type=media_type,
        access_token=access_token,
        media_url=media_url,
        media_id=media_id,
        caption=caption,
        filename=filename,
    )
    return result
