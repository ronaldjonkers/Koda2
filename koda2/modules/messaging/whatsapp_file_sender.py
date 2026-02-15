import os
import logging
import mimetypes
from typing import Optional
from urllib.parse import urlparse
import requests

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    'image': ['.jpg', '.jpeg', '.png', '.gif'],
    'video': ['.mp4', '.3gp'],
    'document': ['.pdf', '.doc', '.docx', '.txt'],
    'audio': ['.mp3', '.ogg', '.wav']
}

def validate_file_type(file_path: str) -> tuple[bool, Optional[str]]:
    """Validate if the file type is supported by WhatsApp."""
    ext = os.path.splitext(file_path)[1].lower()
    for media_type, extensions in SUPPORTED_MIME_TYPES.items():
        if ext in extensions:
            return True, media_type
    return False, None

def send_whatsapp_file(
    file_path: str,
    recipient_id: str,
    whatsapp_client: any,
    caption: str = ""
) -> dict:
    """Send a file via WhatsApp with validation and error handling.
    
    Args:
        file_path: Local file path or URL
        recipient_id: WhatsApp recipient ID
        whatsapp_client: Initialized WhatsApp client
        caption: Optional caption for the media
    
    Returns:
        dict: Response containing status and message
    """
    try:
        # Check if input is URL or local path
        parsed = urlparse(file_path)
        is_url = bool(parsed.scheme and parsed.netloc)
        
        # Get file content
        if is_url:
            response = requests.get(file_path, stream=True)
            response.raise_for_status()
            file_content = response.content
            file_name = os.path.basename(parsed.path)
        else:
            if not os.path.exists(file_path):
                return {"status": "error", "message": "File not found"}
            with open(file_path, 'rb') as f:
                file_content = f.read()
            file_name = os.path.basename(file_path)

        # Validate file type
        is_valid, media_type = validate_file_type(file_name)
        if not is_valid:
            return {"status": "error", "message": "Unsupported file type"}

        # Send media based on type
        response = whatsapp_client.send_media(
            media_type=media_type,
            file_content=file_content,
            recipient_id=recipient_id,
            caption=caption
        )

        return {"status": "success", "message": "File sent successfully"}

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while sending file: {str(e)}")
        return {"status": "error", "message": "Network error occurred"}
    except Exception as e:
        logger.error(f"Error sending file: {str(e)}")
        return {"status": "error", "message": "Failed to send file"}
