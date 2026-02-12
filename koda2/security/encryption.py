"""AES-256 encryption for sensitive user data."""

from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from koda2.config import get_settings
from koda2.logging_config import get_logger

logger = get_logger(__name__)

_cipher: Optional[AESGCM] = None


def _get_cipher() -> AESGCM:
    """Return or create the AES-GCM cipher from the configured key."""
    global _cipher
    if _cipher is not None:
        return _cipher

    settings = get_settings()
    key_b64 = settings.koda2_encryption_key
    if not key_b64:
        logger.warning("encryption_key_missing", msg="Generating ephemeral key — data will not persist across restarts")
        key = AESGCM.generate_key(bit_length=256)
        logger.info("ephemeral_key_generated", key_b64=base64.urlsafe_b64encode(key).decode())
    else:
        # Try to decode the key from base64. If it fails, the key might be
        # a raw string or invalid — generate a proper key and warn.
        try:
            padded = key_b64 + "=" * (-len(key_b64) % 4)
            key = base64.urlsafe_b64decode(padded)
            if len(key) != 32:
                raise ValueError(f"Key is {len(key)} bytes, need 32")
        except Exception as e:
            logger.warning(
                "encryption_key_invalid",
                error=str(e),
                msg="Generating new key. Update KODA2_ENCRYPTION_KEY in .env",
            )
            key = AESGCM.generate_key(bit_length=256)
            new_key_b64 = base64.urlsafe_b64encode(key).decode()
            logger.warning("new_encryption_key", key=new_key_b64)
            print(f"\n⚠️  KODA2_ENCRYPTION_KEY is invalid. A new key was generated.")
            print(f"   Update your .env file with:\n   KODA2_ENCRYPTION_KEY={new_key_b64}\n")

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
    # Fix padding if missing
    padded = token + "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode(padded)
    nonce, ciphertext = raw[:12], raw[12:]
    return cipher.decrypt(nonce, ciphertext, None).decode("utf-8")
