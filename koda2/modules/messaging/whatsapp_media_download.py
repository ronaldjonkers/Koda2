"""WhatsApp media download and text extraction."""
import io
import logging
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger(__name__)


async def download_whatsapp_media(
    media_id: str,
    access_token: str,
    api_version: str = "v17.0",
) -> Optional[Dict[str, Any]]:
    """Download media from WhatsApp Business API.

    Step 1: GET the media URL from /{api_version}/{media_id}
    Step 2: GET the actual binary from the returned URL.

    Returns dict with keys: content (bytes), mime_type (str), filename (str|None)
    or None on failure.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    base_url = f"https://graph.facebook.com/{api_version}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1 – resolve media URL
            meta_resp = await client.get(
                f"{base_url}/{media_id}", headers=headers
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()
            media_url = meta.get("url")
            mime_type = meta.get("mime_type", "application/octet-stream")

            if not media_url:
                logger.error("No URL in media metadata for %s", media_id)
                return None

            # Step 2 – download binary
            dl_resp = await client.get(media_url, headers=headers)
            dl_resp.raise_for_status()

            return {
                "content": dl_resp.content,
                "mime_type": mime_type,
                "filename": meta.get("filename"),
            }
    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP %s downloading media %s: %s",
            exc.response.status_code, media_id, exc,
        )
    except Exception as exc:
        logger.error("Failed to download media %s: %s", media_id, exc)
    return None


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not installed – falling back to PyPDF2")
        return _extract_text_pypdf2(pdf_bytes)

    text_parts = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
    except Exception as exc:
        logger.error("pdfplumber extraction failed: %s", exc)
        return _extract_text_pypdf2(pdf_bytes)

    return "\n".join(text_parts)


def _extract_text_pypdf2(pdf_bytes: bytes) -> str:
    """Fallback PDF text extraction using PyPDF2."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        logger.error("Neither pdfplumber nor PyPDF2 installed")
        return ""

    text_parts = []
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    except Exception as exc:
        logger.error("PyPDF2 extraction failed: %s", exc)
    return "\n".join(text_parts)


def extract_text_from_image(image_bytes: bytes, mime_type: str) -> str:
    """Placeholder for OCR on images. Returns empty string for now."""
    # Future: integrate pytesseract or an LLM vision endpoint
    logger.debug("Image text extraction not yet implemented for %s", mime_type)
    return ""


async def process_incoming_media(
    media_id: str,
    mime_type: str,
    access_token: str,
    api_version: str = "v17.0",
) -> Optional[Dict[str, Any]]:
    """Download media and extract text content where possible.

    Returns dict with:
      - content: raw bytes
      - mime_type: str
      - filename: str | None
      - extracted_text: str (may be empty)
    """
    media = await download_whatsapp_media(media_id, access_token, api_version)
    if media is None:
        return None

    extracted_text = ""
    mt = media["mime_type"].lower()

    if "pdf" in mt:
        extracted_text = extract_text_from_pdf(media["content"])
    elif mt.startswith("image/"):
        extracted_text = extract_text_from_image(media["content"], mt)

    media["extracted_text"] = extracted_text
    return media
