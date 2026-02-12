"""Tests for account credential validators."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


class TestValidateTelegramCredentials:
    """Tests for validate_telegram_credentials."""

    @pytest.mark.asyncio
    async def test_empty_token(self) -> None:
        """Empty token returns error."""
        from koda2.modules.account.validators import validate_telegram_credentials

        result = await validate_telegram_credentials("")
        assert result == (False, "Bot token is required.")

    @pytest.mark.asyncio
    async def test_invalid_format(self) -> None:
        """Token without colon returns error."""
        from koda2.modules.account.validators import validate_telegram_credentials

        result = await validate_telegram_credentials("invalidtoken")
        assert result[0] is False
        assert "format" in result[1].lower()

    @pytest.mark.asyncio
    async def test_valid_token(self) -> None:
        """Valid token returns success."""
        from koda2.modules.account.validators import validate_telegram_credentials

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"id": 123456, "username": "test_bot"},
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("koda2.modules.account.validators.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await validate_telegram_credentials("123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11")
            assert result == (True, "")

    @pytest.mark.asyncio
    async def test_invalid_token_401(self) -> None:
        """401 response returns auth error."""
        from koda2.modules.account.validators import validate_telegram_credentials

        with patch("httpx.AsyncClient") as mock_client_class:

            class MockClient:
                async def get(self, *args, **kwargs):
                    response = MagicMock()
                    response.status_code = 401
                    return response

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return None

            mock_client_class.return_value = MockClient()

            result = await validate_telegram_credentials("123456:invalid_token")
            assert result[0] is False
            assert "Invalid bot token" in result[1]


class TestValidateOpenAICredentials:
    """Tests for validate_openai_credentials."""

    @pytest.mark.asyncio
    async def test_empty_key(self) -> None:
        """Empty API key returns error."""
        from koda2.modules.account.validators import validate_openai_credentials

        result = await validate_openai_credentials("")
        assert result == (False, "API key is required.")

    @pytest.mark.asyncio
    async def test_invalid_format(self) -> None:
        """Key not starting with 'sk-' returns error."""
        from koda2.modules.account.validators import validate_openai_credentials

        result = await validate_openai_credentials("invalid_key")
        assert result[0] is False
        assert "format" in result[1].lower()

    @pytest.mark.asyncio
    async def test_invalid_key_401(self) -> None:
        """401 response returns auth error."""
        from koda2.modules.account.validators import validate_openai_credentials

        with patch("httpx.AsyncClient") as mock_client_class:

            class MockClient:
                async def get(self, *args, **kwargs):
                    response = MagicMock()
                    response.status_code = 401
                    response.json.return_value = {"error": {"message": "Invalid API key"}}
                    return response

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    return None

            mock_client_class.return_value = MockClient()

            result = await validate_openai_credentials("sk-invalid_key")
            assert result[0] is False
            assert "Invalid API key" in result[1]


class TestValidateGoogleCredentials:
    """Tests for validate_google_credentials."""

    @pytest.mark.asyncio
    async def test_missing_file(self) -> None:
        """Missing credentials file returns error."""
        from koda2.modules.account.validators import validate_google_credentials

        result = await validate_google_credentials("/nonexistent/creds.json", "/tmp/token.json")
        assert result[0] is False
        assert "not found" in result[1].lower()

    @pytest.mark.asyncio
    async def test_invalid_json(self, tmp_path: Path) -> None:
        """Invalid JSON returns error."""
        from koda2.modules.account.validators import validate_google_credentials

        creds_file = tmp_path / "creds.json"
        creds_file.write_text("not valid json")

        result = await validate_google_credentials(str(creds_file), str(tmp_path / "token.json"))
        assert result[0] is False
        assert "Invalid JSON" in result[1]

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, tmp_path: Path) -> None:
        """Missing required fields returns error."""
        from koda2.modules.account.validators import validate_google_credentials

        creds_file = tmp_path / "creds.json"
        creds_file.write_text(json.dumps({"invalid": "structure"}))

        result = await validate_google_credentials(str(creds_file), str(tmp_path / "token.json"))
        assert result[0] is False
        assert "missing" in result[1].lower()

    @pytest.mark.asyncio
    async def test_valid_installed_credentials(self, tmp_path: Path) -> None:
        """Valid installed credentials returns success."""
        from koda2.modules.account.validators import validate_google_credentials

        creds_file = tmp_path / "creds.json"
        creds_data = {
            "installed": {
                "client_id": "test-client-id.apps.googleusercontent.com",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        creds_file.write_text(json.dumps(creds_data))

        result = await validate_google_credentials(str(creds_file), str(tmp_path / "token.json"))
        assert result == (True, "")

    @pytest.mark.asyncio
    async def test_valid_web_credentials(self, tmp_path: Path) -> None:
        """Valid web credentials returns success."""
        from koda2.modules.account.validators import validate_google_credentials

        creds_file = tmp_path / "creds.json"
        creds_data = {
            "web": {
                "client_id": "test-client-id.apps.googleusercontent.com",
                "client_secret": "test-secret",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        }
        creds_file.write_text(json.dumps(creds_data))

        result = await validate_google_credentials(str(creds_file), str(tmp_path / "token.json"))
        assert result == (True, "")


class TestValidateMSGraphCredentials:
    """Tests for validate_msgraph_credentials."""

    @pytest.mark.asyncio
    async def test_empty_client_id(self) -> None:
        """Empty client ID returns error."""
        from koda2.modules.account.validators import validate_msgraph_credentials

        result = await validate_msgraph_credentials("", "secret", "tenant")
        assert result == (False, "Client ID is required.")

    @pytest.mark.asyncio
    async def test_empty_client_secret(self) -> None:
        """Empty client secret returns error."""
        from koda2.modules.account.validators import validate_msgraph_credentials

        result = await validate_msgraph_credentials("client_id", "", "tenant")
        assert result == (False, "Client secret is required.")

    @pytest.mark.asyncio
    async def test_empty_tenant_id(self) -> None:
        """Empty tenant ID returns error."""
        from koda2.modules.account.validators import validate_msgraph_credentials

        result = await validate_msgraph_credentials("client_id", "secret", "")
        assert result == (False, "Tenant ID is required.")


class TestValidateCalDAVCredentials:
    """Tests for validate_caldav_credentials."""

    @pytest.mark.asyncio
    async def test_empty_url(self) -> None:
        """Empty URL returns error."""
        from koda2.modules.account.validators import validate_caldav_credentials

        result = await validate_caldav_credentials("", "user", "pass")
        assert result == (False, "CalDAV URL is required.")


class TestValidateIMAPCredentials:
    """Tests for validate_imap_credentials."""

    @pytest.mark.asyncio
    async def test_empty_server(self) -> None:
        """Empty server returns error."""
        from koda2.modules.account.validators import validate_imap_credentials

        result = await validate_imap_credentials("", 993, "user", "pass")
        assert result == (False, "IMAP server is required.")

    @pytest.mark.asyncio
    async def test_empty_username(self) -> None:
        """Empty username returns error."""
        from koda2.modules.account.validators import validate_imap_credentials

        result = await validate_imap_credentials("imap.test.com", 993, "", "pass")
        assert result == (False, "Username is required.")

    @pytest.mark.asyncio
    async def test_empty_password(self) -> None:
        """Empty password returns error."""
        from koda2.modules.account.validators import validate_imap_credentials

        result = await validate_imap_credentials("imap.test.com", 993, "user", "")
        assert result == (False, "Password is required.")


class TestValidateSMTPCredentials:
    """Tests for validate_smtp_credentials."""

    @pytest.mark.asyncio
    async def test_empty_server(self) -> None:
        """Empty server returns error."""
        from koda2.modules.account.validators import validate_smtp_credentials

        result = await validate_smtp_credentials("", 587, "user", "pass")
        assert result == (False, "SMTP server is required.")

    @pytest.mark.asyncio
    async def test_empty_username(self) -> None:
        """Empty username returns error."""
        from koda2.modules.account.validators import validate_smtp_credentials

        result = await validate_smtp_credentials("smtp.test.com", 587, "", "pass")
        assert result == (False, "Username is required.")

    @pytest.mark.asyncio
    async def test_empty_password(self) -> None:
        """Empty password returns error."""
        from koda2.modules.account.validators import validate_smtp_credentials

        result = await validate_smtp_credentials("smtp.test.com", 587, "user", "")
        assert result == (False, "Password is required.")


class TestValidateEWSCredentials:
    """Tests for validate_ews_credentials."""

    @pytest.mark.asyncio
    async def test_import_error(self) -> None:
        """Missing exchangelib returns appropriate error."""
        from koda2.modules.account.validators import validate_ews_credentials

        with patch.dict("sys.modules", {"exchangelib": None}):
            result = await validate_ews_credentials(
                "https://ews.test.com", "user", "pass", "user@test.com"
            )
            assert result[0] is False
            assert "exchangelib" in result[1].lower()
