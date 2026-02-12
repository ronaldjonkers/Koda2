"""AES-256 encryption for sensitive user data."""

from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from executiveai.config import get_settings
from executiveai.logging_config import get_logger

logger = get_logger(__name__)

_cipher: Optional[AESGCM] = None


def _get_cipher() -> AESGCM:
    """Return or create the AES-GCM cipher from the configured key."""
    global _cipher
    if _cipher is not None:
        return _cipher

    settings = get_settings()
    key_b64 = settings.executiveai_encryption_key
    if not key_b64:
        logger.warning("encryption_key_missing", msg="Generating ephemeral key — data will not persist across restarts")
        key = AESGCM.generate_key(bit_length=256)
        logger.info("ephemeral_key_generated", key_b64=base64.urlsafe_b64encode(key).decode())
    else:
        key = base64.urlsafe_b64decode(key_b64)
        if len(key) != 32:
            raise ValueError("EXECUTIVEAI_ENCRYPTION_KEY must be a 32-byte base64-encoded value")

    _cipher = AESGCM(key)
    return _cipher


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string, returning base64-encoded ciphertext with nonce."""
    cipher = _get_cipher()
    nonce = os.urandom(12)
    ciphertext = cipher.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a base64-encoded token back to plaintext."""
    cipher = _get_cipher()
    raw = base64.urlsafe_b64decode(token)
    nonce, ciphertext = raw[:12], raw[12:]
    return cipher.decrypt(nonce, ciphertext, None).decode("utf-8")
