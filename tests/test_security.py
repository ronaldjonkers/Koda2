"""Tests for the security module — encryption, RBAC, and audit."""

from __future__ import annotations

import base64
import os
from unittest.mock import patch, MagicMock

import pytest

from koda2.security.encryption import encrypt, decrypt, _get_cipher
from koda2.security.rbac import Permission, Role, ROLE_PERMISSIONS, UserIdentity


class TestEncryption:
    """Tests for AES-256 encryption/decryption."""

    @pytest.fixture(autouse=True)
    def reset_cipher(self):
        """Reset the global cipher before each test."""
        import koda2.security.encryption as enc
        enc._cipher = None
        yield
        enc._cipher = None

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Encrypting then decrypting returns original text."""
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        with patch("koda2.security.encryption.get_settings") as mock:
            mock.return_value = MagicMock(koda2_encryption_key=key)
            plaintext = "Hello, Koda2!"
            encrypted = encrypt(plaintext)
            assert encrypted != plaintext
            decrypted = decrypt(encrypted)
            assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertexts(self) -> None:
        """Same plaintext produces different ciphertexts due to random nonce."""
        key = base64.urlsafe_b64encode(os.urandom(32)).decode()
        with patch("koda2.security.encryption.get_settings") as mock:
            mock.return_value = MagicMock(koda2_encryption_key=key)
            plaintext = "Test data"
            ct1 = encrypt(plaintext)
            import koda2.security.encryption as enc
            enc._cipher = None
            ct2 = encrypt(plaintext)
            assert ct1 != ct2

    def test_decrypt_wrong_key_fails(self) -> None:
        """Decryption with wrong key raises an error."""
        key1 = base64.urlsafe_b64encode(os.urandom(32)).decode()
        key2 = base64.urlsafe_b64encode(os.urandom(32)).decode()
        import koda2.security.encryption as enc

        with patch("koda2.security.encryption.get_settings") as mock:
            mock.return_value = MagicMock(koda2_encryption_key=key1)
            encrypted = encrypt("secret data")

        enc._cipher = None
        with patch("koda2.security.encryption.get_settings") as mock:
            mock.return_value = MagicMock(koda2_encryption_key=key2)
            with pytest.raises(Exception):
                decrypt(encrypted)

    def test_ephemeral_key_generated_when_empty(self) -> None:
        """When no key is configured, an ephemeral key is generated."""
        with patch("koda2.security.encryption.get_settings") as mock:
            mock.return_value = MagicMock(koda2_encryption_key="")
            cipher = _get_cipher()
            assert cipher is not None


class TestRBAC:
    """Tests for role-based access control."""

    def test_admin_has_all_permissions(self) -> None:
        """Admin role has every permission."""
        user = UserIdentity(user_id="admin1", role=Role.ADMIN)
        for perm in Permission:
            assert user.has_permission(perm) is True

    def test_user_role_permissions(self) -> None:
        """User role has standard permissions but not system access."""
        user = UserIdentity(user_id="user1", role=Role.USER)
        assert user.has_permission(Permission.READ_CALENDAR) is True
        assert user.has_permission(Permission.SEND_EMAIL) is True
        assert user.has_permission(Permission.SYSTEM_ACCESS) is False
        assert user.has_permission(Permission.SELF_IMPROVE) is False

    def test_viewer_limited_permissions(self) -> None:
        """Viewer role can only read."""
        user = UserIdentity(user_id="viewer1", role=Role.VIEWER)
        assert user.has_permission(Permission.READ_CALENDAR) is True
        assert user.has_permission(Permission.READ_EMAIL) is True
        assert user.has_permission(Permission.WRITE_CALENDAR) is False
        assert user.has_permission(Permission.SEND_EMAIL) is False

    def test_require_permission_raises(self) -> None:
        """require_permission raises PermissionError for missing perms."""
        user = UserIdentity(user_id="viewer1", role=Role.VIEWER)
        with pytest.raises(PermissionError, match="lacks permission"):
            user.require_permission(Permission.SEND_EMAIL)

    def test_require_permission_passes(self) -> None:
        """require_permission does not raise for valid perms."""
        user = UserIdentity(user_id="admin1", role=Role.ADMIN)
        user.require_permission(Permission.SYSTEM_ACCESS)
