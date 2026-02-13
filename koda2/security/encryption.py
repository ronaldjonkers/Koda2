"""AES-256 encryption for sensitive user data."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from koda2.config import get_settings
from koda2.logging_config import get_logger

logger = get_logger(__name__)

_cipher: Optional[AESGCM] = None


def _persist_key_to_env(key_b64: str) -> bool:
    """Write the encryption key to .env so it survives restarts.

    If .env exists, update/add the KODA2_ENCRYPTION_KEY line.
    If .env doesn't exist, create it with just the key.
    Returns True if the key was persisted successfully.
    """
    env_path = Path(".env")
    try:
        if env_path.exists():
            lines = env_path.read_text().splitlines()
            found = False
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("KODA2_ENCRYPTION_KEY=") or stripped.startswith("KODA2_ENCRYPTION_KEY ="):
                    lines[i] = f"KODA2_ENCRYPTION_KEY={key_b64}"
                    found = True
                    break
            if not found:
                lines.append(f"KODA2_ENCRYPTION_KEY={key_b64}")
            env_path.write_text("\n".join(lines) + "\n")
        else:
            env_path.write_text(f"KODA2_ENCRYPTION_KEY={key_b64}\n")
        logger.info("encryption_key_persisted", path=str(env_path.resolve()))
        return True
    except Exception as exc:
        logger.warning("encryption_key_persist_failed", error=str(exc))
        return False


def _get_cipher() -> AESGCM:
    """Return or create the AES-GCM cipher from the configured key."""
    global _cipher
    if _cipher is not None:
        return _cipher

    settings = get_settings()
    key_b64 = settings.koda2_encryption_key
    if not key_b64:
        key = AESGCM.generate_key(bit_length=256)
        new_key_b64 = base64.urlsafe_b64encode(key).decode()
        if _persist_key_to_env(new_key_b64):
            logger.info("encryption_key_generated_and_saved")
        else:
            logger.warning("encryption_key_missing", msg="Generated ephemeral key — could not save to .env")
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
                msg="Generating new key and saving to .env",
            )
            key = AESGCM.generate_key(bit_length=256)
            new_key_b64 = base64.urlsafe_b64encode(key).decode()
            if _persist_key_to_env(new_key_b64):
                logger.info("new_encryption_key_saved")
            else:
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
