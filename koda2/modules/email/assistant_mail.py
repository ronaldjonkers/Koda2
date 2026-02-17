"""Assistant email service — the AI's own outgoing mailbox.

Allows the assistant to send emails from its own dedicated address.
Configuration priority: DB (dashboard) → .env fallback.
"""

from __future__ import annotations

import asyncio
import email.encoders
import email.mime.base
import email.mime.multipart
import email.mime.text
import smtplib
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select

from koda2.config import get_settings
from koda2.database import get_session
from koda2.logging_config import get_logger
from koda2.modules.account.models import Account, AccountType, ProviderType

logger = get_logger(__name__)

# Sentinel account name used to identify the assistant's own SMTP account
ASSISTANT_ACCOUNT_NAME = "__assistant_email__"


@dataclass
class AssistantEmailConfig:
    """Current assistant email configuration."""

    smtp_server: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_address: str = ""
    display_name: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.smtp_server and self.smtp_username and self.smtp_password and self.email_address)

    def to_dict(self, hide_password: bool = True) -> dict[str, Any]:
        return {
            "smtp_server": self.smtp_server,
            "smtp_port": self.smtp_port,
            "smtp_username": self.smtp_username,
            "smtp_password": "••••••••" if (hide_password and self.smtp_password) else self.smtp_password,
            "smtp_use_tls": self.smtp_use_tls,
            "email_address": self.email_address,
            "display_name": self.display_name,
            "is_configured": self.is_configured,
        }


class AssistantMailService:
    """Manages the assistant's own email sending capability."""

    def __init__(self, account_service: Optional[Any] = None) -> None:
        self._account_service = account_service
        self._settings = get_settings()

    # ── Configuration ─────────────────────────────────────────────────

    async def get_config(self) -> AssistantEmailConfig:
        """Get the current assistant email config (DB first, env fallback)."""
        db_cfg = await self._load_db_config()
        if db_cfg and db_cfg.is_configured:
            return db_cfg
        return self._load_env_config()

    def _load_env_config(self) -> AssistantEmailConfig:
        """Load config from environment / .env."""
        s = self._settings
        return AssistantEmailConfig(
            smtp_server=s.assistant_smtp_server,
            smtp_port=s.assistant_smtp_port,
            smtp_username=s.assistant_smtp_username,
            smtp_password=s.assistant_smtp_password,
            smtp_use_tls=s.assistant_smtp_use_tls,
            email_address=s.assistant_email_address,
            display_name=s.assistant_email_display_name or s.assistant_name,
        )

    async def _load_db_config(self) -> Optional[AssistantEmailConfig]:
        """Load config from the accounts DB (dashboard-configured)."""
        if not self._account_service:
            return None
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Account).where(
                        Account.name == ASSISTANT_ACCOUNT_NAME,
                        Account.is_active == True,  # noqa: E712
                    )
                )
                account = result.scalar_one_or_none()
                if not account:
                    return None
                creds = self._account_service.decrypt_credentials(account)
                return AssistantEmailConfig(
                    smtp_server=creds.get("server", ""),
                    smtp_port=creds.get("port", 587),
                    smtp_username=creds.get("username", ""),
                    smtp_password=creds.get("password", ""),
                    smtp_use_tls=creds.get("use_tls", True),
                    email_address=creds.get("email_address", creds.get("username", "")),
                    display_name=creds.get("display_name", self._settings.assistant_name),
                )
        except Exception as exc:
            logger.error("assistant_email_db_load_failed", error=str(exc))
            return None

    async def save_config(self, cfg: AssistantEmailConfig) -> None:
        """Save assistant email config to the accounts DB."""
        if not self._account_service:
            raise RuntimeError("AccountService not available")

        credentials = {
            "server": cfg.smtp_server,
            "port": cfg.smtp_port,
            "username": cfg.smtp_username,
            "password": cfg.smtp_password,
            "use_tls": cfg.smtp_use_tls,
            "email_address": cfg.email_address,
            "display_name": cfg.display_name,
        }
        encrypted = self._account_service._encrypt_credentials(credentials)

        async with get_session() as session:
            result = await session.execute(
                select(Account).where(Account.name == ASSISTANT_ACCOUNT_NAME)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.credentials = encrypted
                existing.is_active = True
            else:
                account = Account(
                    name=ASSISTANT_ACCOUNT_NAME,
                    account_type=AccountType.EMAIL.value,
                    provider=ProviderType.SMTP.value,
                    is_active=True,
                    is_default=False,
                    credentials=encrypted,
                )
                session.add(account)
        logger.info("assistant_email_config_saved", address=cfg.email_address)

    # ── Connection test ───────────────────────────────────────────────

    async def test_connection(self, cfg: Optional[AssistantEmailConfig] = None) -> tuple[bool, str]:
        """Test the SMTP connection with the current or provided config."""
        if cfg is None:
            cfg = await self.get_config()
        if not cfg.is_configured:
            return False, "Assistant email not configured."

        try:
            def _test():
                with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=15) as server:
                    server.ehlo()
                    if cfg.smtp_use_tls:
                        server.starttls()
                        server.ehlo()
                    server.login(cfg.smtp_username, cfg.smtp_password)
                return True

            await asyncio.wait_for(asyncio.to_thread(_test), timeout=20)
            return True, "Connection successful."
        except asyncio.TimeoutError:
            return False, "Connection timed out."
        except smtplib.SMTPAuthenticationError:
            return False, "Authentication failed. Check username and password."
        except Exception as exc:
            return False, f"SMTP error: {exc}"

    # ── Sending ───────────────────────────────────────────────────────

    @property
    async def is_configured(self) -> bool:
        cfg = await self.get_config()
        return cfg.is_configured

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body_text: str,
        body_html: str = "",
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
    ) -> bool:
        """Send an email from the assistant's own address.

        Returns True on success.
        """
        cfg = await self.get_config()
        if not cfg.is_configured:
            logger.error("assistant_email_not_configured")
            return False

        try:
            def _send():
                msg = email.mime.multipart.MIMEMultipart("alternative")
                from_header = f"{cfg.display_name} <{cfg.email_address}>" if cfg.display_name else cfg.email_address
                msg["From"] = from_header
                msg["To"] = ", ".join(to)
                msg["Subject"] = subject
                if cc:
                    msg["Cc"] = ", ".join(cc)

                if body_text:
                    msg.attach(email.mime.text.MIMEText(body_text, "plain"))
                if body_html:
                    msg.attach(email.mime.text.MIMEText(body_html, "html"))

                all_recipients = list(to) + (cc or []) + (bcc or [])

                with smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=30) as server:
                    server.ehlo()
                    if cfg.smtp_use_tls:
                        server.starttls()
                        server.ehlo()
                    server.login(cfg.smtp_username, cfg.smtp_password)
                    server.sendmail(cfg.email_address, all_recipients, msg.as_string())
                return True

            result = await asyncio.to_thread(_send)
            logger.info("assistant_email_sent", to=to, subject=subject)
            return result
        except Exception as exc:
            logger.error("assistant_email_send_failed", to=to, subject=subject, error=str(exc))
            return False
