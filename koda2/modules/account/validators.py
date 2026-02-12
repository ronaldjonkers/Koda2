"""Credential validation functions for testing if account credentials actually work."""

from __future__ import annotations

import asyncio
import imaplib
import json
import smtplib
from pathlib import Path
from typing import Any

import httpx

from koda2.logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 30.0


def _is_success(result: tuple[bool, str]) -> bool:
    """Check if a validation result indicates success."""
    return result[0]


def _get_error(result: tuple[bool, str]) -> str:
    """Get the error message from a validation result."""
    return result[1]


def _normalize_ews_server(server: str) -> str:
    """Normalize an EWS server input to just the hostname.
    
    exchangelib expects a plain hostname (e.g. 'exchange.company.com'),
    not a full URL. This strips https://, paths like /EWS/Exchange.asmx, etc.
    """
    s = server.strip()
    # Remove protocol prefix
    for prefix in ("https://", "http://"):
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    # Remove path (e.g. /EWS/Exchange.asmx)
    s = s.split("/")[0]
    # Remove port if present
    s = s.split(":")[0]
    return s


async def validate_ews_credentials(
    server: str, username: str, password: str, email: str
) -> tuple[bool, str]:
    """Validate Exchange Web Services credentials.
    
    Args:
        server: EWS server hostname or URL (will be normalized to hostname)
        username: Username for authentication
        password: Password for authentication
        email: Email address for the account
        
    Returns:
        Tuple of (success, error_message_or_empty)
    """
    hostname = _normalize_ews_server(server)
    if not hostname:
        return (False, "Server hostname is required.")
    
    try:
        from exchangelib import Account, Configuration, Credentials

        def _test_connection() -> bool:
            creds = Credentials(username, password)
            config = Configuration(server=hostname, credentials=creds)
            account = Account(email, config=config, autodiscover=False)
            # Try to access the calendar to validate credentials
            _ = account.calendar
            return True

        # Run blocking EWS operations in thread
        result = await asyncio.wait_for(
            asyncio.to_thread(_test_connection),
            timeout=DEFAULT_TIMEOUT,
        )
        return (True, "")

    except asyncio.TimeoutError:
        return (False, "Connection timed out. Check server URL and network access.")
    except ImportError:
        return (False, "exchangelib library not installed.")
    except Exception as e:
        error_msg = str(e).lower()
        if "unauthorized" in error_msg or "401" in error_msg:
            return (False, "Invalid username or password.")
        elif "could not connect" in error_msg or "connection refused" in error_msg:
            return (False, f"Could not connect to server '{server}'. Check server URL.")
        elif "dns" in error_msg or "name resolution" in error_msg:
            return (False, f"Could not resolve server hostname '{server}'.")
        else:
            return (False, f"EWS connection failed: {e}")


async def validate_google_credentials(
    credentials_file: str, token_file: str
) -> tuple[bool, str]:
    """Validate Google API credentials.
    
    Args:
        credentials_file: Path to the credentials JSON file
        token_file: Path to the token JSON file (may not exist yet)
        
    Returns:
        Tuple of (success, error_message_or_empty)
    """
    creds_path = Path(credentials_file)
    token_path = Path(token_file)

    # Check if credentials file exists
    if not creds_path.exists():
        return (False, f"Credentials file not found: {credentials_file}")

    # Check if credentials file is valid JSON
    try:
        creds_data = json.loads(creds_path.read_text())
    except json.JSONDecodeError as e:
        return (False, f"Invalid JSON in credentials file: {e}")
    except Exception as e:
        return (False, f"Error reading credentials file: {e}")

    # Validate required fields in credentials
    if "installed" not in creds_data and "web" not in creds_data:
        return (False, "Credentials file missing 'installed' or 'web' section.")

    client_config = creds_data.get("installed") or creds_data.get("web")
    required_fields = ["client_id", "client_secret", "auth_uri", "token_uri"]
    missing = [f for f in required_fields if f not in client_config]
    if missing:
        return (False, f"Credentials file missing required fields: {', '.join(missing)}")

    # If token file exists, try to validate it
    if token_path.exists():
        try:
            from google.oauth2.credentials import Credentials

            def _validate_token() -> bool:
                creds = Credentials.from_authorized_user_file(str(token_path))
                return creds.valid or (creds.expired and creds.refresh_token is not None)

            valid = await asyncio.to_thread(_validate_token)
            if not valid:
                return (False, "Token file exists but credentials are invalid or expired.")
        except ImportError:
            return (False, "Google auth libraries not installed.")
        except Exception as e:
            return (False, f"Invalid token file: {e}")

    return (True, "")


async def validate_msgraph_credentials(
    client_id: str, client_secret: str, tenant_id: str
) -> tuple[bool, str]:
    """Validate Microsoft Graph API credentials.
    
    Args:
        client_id: Azure AD application client ID
        client_secret: Azure AD application client secret
        tenant_id: Azure AD tenant ID
        
    Returns:
        Tuple of (success, error_message_or_empty)
    """
    if not client_id:
        return (False, "Client ID is required.")
    if not client_secret:
        return (False, "Client secret is required.")
    if not tenant_id:
        return (False, "Tenant ID is required.")

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                token_url,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
            )

        if response.status_code == 200:
            return (True, "")
        elif response.status_code == 401:
            error_data = response.json() if response.text else {}
            error_desc = error_data.get("error_description", "")
            if "invalid_client" in error_desc.lower():
                return (False, "Invalid client ID or client secret.")
            return (False, f"Authentication failed: {error_desc or 'Invalid credentials'}")
        elif response.status_code == 400:
            error_data = response.json() if response.text else {}
            return (False, f"Bad request: {error_data.get('error_description', 'Unknown error')}")
        else:
            return (False, f"Token request failed: HTTP {response.status_code}")

    except httpx.TimeoutException:
        return (False, "Connection timed out. Check network access to Microsoft login servers.")
    except Exception as e:
        return (False, f"Failed to connect to Microsoft login: {e}")


async def validate_caldav_credentials(
    url: str, username: str, password: str
) -> tuple[bool, str]:
    """Validate CalDAV server credentials.
    
    Args:
        url: CalDAV server URL
        username: Username for authentication
        password: Password for authentication
        
    Returns:
        Tuple of (success, error_message_or_empty)
    """
    if not url:
        return (False, "CalDAV URL is required.")

    try:
        import caldav

        def _test_caldav() -> bool:
            client = caldav.DAVClient(url=url, username=username, password=password)
            # Try to get principal to validate connection
            principal = client.principal()
            # Try to list calendars
            calendars = principal.calendars()
            return True

        result = await asyncio.wait_for(
            asyncio.to_thread(_test_caldav),
            timeout=DEFAULT_TIMEOUT,
        )
        return (True, "")

    except ImportError:
        return (False, "caldav library not installed.")
    except asyncio.TimeoutError:
        return (False, "Connection timed out. Check server URL and network access.")
    except Exception as e:
        error_msg = str(e).lower()
        if "unauthorized" in error_msg or "401" in error_msg:
            return (False, "Invalid username or password.")
        elif "not found" in error_msg or "404" in error_msg:
            return (False, f"CalDAV endpoint not found at '{url}'. Check the URL.")
        elif "could not connect" in error_msg or "connection refused" in error_msg:
            return (False, f"Could not connect to server at '{url}'.")
        elif "ssl" in error_msg or "certificate" in error_msg:
            return (False, f"SSL/TLS error: {e}")
        else:
            return (False, f"CalDAV connection failed: {e}")


async def validate_imap_credentials(
    server: str, port: int, username: str, password: str, use_ssl: bool = True
) -> tuple[bool, str]:
    """Validate IMAP server credentials.
    
    Args:
        server: IMAP server hostname
        port: IMAP server port
        username: Username for authentication
        password: Password for authentication
        use_ssl: Whether to use SSL connection
        
    Returns:
        Tuple of (success, error_message_or_empty)
    """
    if not server:
        return (False, "IMAP server is required.")
    if not username:
        return (False, "Username is required.")
    if not password:
        return (False, "Password is required.")

    try:

        def _test_imap() -> bool:
            if use_ssl:
                conn = imaplib.IMAP4_SSL(server, port)
            else:
                conn = imaplib.IMAP4(server, port)
            try:
                conn.login(username, password)
                return True
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass

        result = await asyncio.wait_for(
            asyncio.to_thread(_test_imap),
            timeout=DEFAULT_TIMEOUT,
        )
        return (True, "")

    except asyncio.TimeoutError:
        return (False, "Connection timed out. Check server address and port.")
    except Exception as e:
        error_msg = str(e).lower()
        if "authentication failed" in error_msg or "invalid credentials" in error_msg:
            return (False, "Invalid username or password.")
        elif "ssl" in error_msg or "certificate" in error_msg:
            return (False, f"SSL error: {e}")
        elif "connection refused" in error_msg or "name or service not known" in error_msg:
            return (False, f"Could not connect to {server}:{port}. Check server address.")
        elif "socket error" in error_msg or "network" in error_msg:
            return (False, f"Network error connecting to {server}:{port}")
        else:
            return (False, f"IMAP connection failed: {e}")


async def validate_smtp_credentials(
    server: str, port: int, username: str, password: str, use_tls: bool = True
) -> tuple[bool, str]:
    """Validate SMTP server credentials.
    
    Args:
        server: SMTP server hostname
        port: SMTP server port
        username: Username for authentication
        password: Password for authentication
        use_tls: Whether to use TLS (STARTTLS)
        
    Returns:
        Tuple of (success, error_message_or_empty)
    """
    if not server:
        return (False, "SMTP server is required.")
    if not username:
        return (False, "Username is required.")
    if not password:
        return (False, "Password is required.")

    try:

        def _test_smtp() -> bool:
            with smtplib.SMTP(server, port, timeout=DEFAULT_TIMEOUT) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(username, password)
                return True

        result = await asyncio.wait_for(
            asyncio.to_thread(_test_smtp),
            timeout=DEFAULT_TIMEOUT + 5,  # Extra time for TLS handshake
        )
        return (True, "")

    except asyncio.TimeoutError:
        return (False, "Connection timed out. Check server address and port.")
    except Exception as e:
        error_msg = str(e).lower()
        if "authentication" in error_msg or "535" in error_msg:
            return (False, "Invalid username or password.")
        elif "ssl" in error_msg or "tls" in error_msg:
            return (False, f"TLS/SSL error: {e}")
        elif "connection refused" in error_msg or "name or service not known" in error_msg:
            return (False, f"Could not connect to {server}:{port}. Check server address.")
        elif "smtpserverdisconnect" in error_msg:
            return (False, "Server disconnected unexpectedly. Check port and TLS settings.")
        else:
            return (False, f"SMTP connection failed: {e}")


async def validate_telegram_credentials(bot_token: str) -> tuple[bool, str]:
    """Validate Telegram bot token.
    
    Args:
        bot_token: Telegram bot token from BotFather
        
    Returns:
        Tuple of (success, error_message_or_empty)
    """
    if not bot_token:
        return (False, "Bot token is required.")

    if ":" not in bot_token:
        return (False, "Invalid bot token format. Should be in format '123456:ABC-DEF...'")

    api_url = f"https://api.telegram.org/bot{bot_token}/getMe"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(api_url)

        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                bot_info = data.get("result", {})
                bot_name = bot_info.get("username", "Unknown")
                return (True, "")
            else:
                return (False, f"API error: {data.get('description', 'Unknown error')}")
        elif response.status_code == 401:
            return (False, "Invalid bot token. Check the token from BotFather.")
        elif response.status_code == 404:
            return (False, "Invalid bot token format.")
        else:
            return (False, f"Telegram API returned HTTP {response.status_code}")

    except httpx.TimeoutException:
        return (False, "Connection timed out. Check network access to Telegram API.")
    except Exception as e:
        return (False, f"Failed to connect to Telegram API: {e}")


async def validate_openai_credentials(api_key: str) -> tuple[bool, str]:
    """Validate OpenAI API key.
    
    Args:
        api_key: OpenAI API key
        
    Returns:
        Tuple of (success, error_message_or_empty)
    """
    if not api_key:
        return (False, "API key is required.")

    if not api_key.startswith("sk-"):
        return (False, "Invalid API key format. OpenAI keys should start with 'sk-'.")

    api_url = "https://api.openai.com/v1/models"

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.get(
                api_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )

        if response.status_code == 200:
            return (True, "")
        elif response.status_code == 401:
            return (False, "Invalid API key. Check your OpenAI API key.")
        elif response.status_code == 429:
            return (False, "Rate limit exceeded or quota exhausted.")
        else:
            error_data = response.json() if response.text else {}
            error_msg = error_data.get("error", {}).get("message", f"HTTP {response.status_code}")
            return (False, f"OpenAI API error: {error_msg}")

    except httpx.TimeoutException:
        return (False, "Connection timed out. Check network access to OpenAI API.")
    except Exception as e:
        return (False, f"Failed to connect to OpenAI API: {e}")
