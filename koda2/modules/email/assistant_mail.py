"""Assistant email service — the AI's own full mailbox (IMAP + SMTP).

Allows the assistant to read AND send emails from its own dedicated address.
Configuration priority: DB (dashboard) → .env fallback.
Supports SSL / STARTTLS / None with automatic port defaults.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import email as email_lib
import email.encoders
import email.mime.base
import email.mime.multipart
import email.mime.text
import imaplib
import smtplib
from dataclasses import dataclass, field
from email.header import decode_header
from typing import Any, Optional

from sqlalchemy import select

from koda2.config import get_settings
from koda2.database import get_session
from koda2.logging_config import get_logger
from koda2.modules.account.models import Account, AccountType, ProviderType

logger = get_logger(__name__)

ASSISTANT_ACCOUNT_NAME = "__assistant_email__"

# ── Encryption helpers ────────────────────────────────────────────────

# "ssl" = implicit TLS (port 993/465), "starttls" = upgrade (port 143/587), "none" = plain
ENCRYPTION_OPTIONS = ("ssl", "starttls", "none")

DEFAULT_PORTS = {
    "imap": {"ssl": 993, "starttls": 143, "none": 143},
    "smtp": {"ssl": 465, "starttls": 587, "none": 25},
}


def auto_port(protocol: str, encryption: str) -> int:
    """Return the standard port for a protocol + encryption combo."""
    return DEFAULT_PORTS.get(protocol, {}).get(encryption, 0)


# ── Config dataclass ──────────────────────────────────────────────────

@dataclass
class AssistantEmailConfig:
    """Full assistant email configuration (IMAP + SMTP)."""

    # IMAP (incoming)
    imap_server: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_encryption: str = "ssl"  # ssl | starttls | none

    # SMTP (outgoing)
    smtp_server: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_encryption: str = "starttls"  # ssl | starttls | none

    # Identity
    email_address: str = ""
    display_name: str = ""

    # Check interval (minutes, 0 = disabled)
    check_interval: int = 10

    @property
    def imap_configured(self) -> bool:
        return bool(self.imap_server and self.imap_username and self.imap_password and self.email_address)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_server and self.smtp_username and self.smtp_password and self.email_address)

    @property
    def is_configured(self) -> bool:
        return self.smtp_configured

    @property
    def fully_configured(self) -> bool:
        return self.imap_configured and self.smtp_configured

    def to_dict(self, hide_password: bool = True) -> dict[str, Any]:
        mask = "••••••••"
        return {
            "imap_server": self.imap_server,
            "imap_port": self.imap_port,
            "imap_username": self.imap_username,
            "imap_password": mask if (hide_password and self.imap_password) else self.imap_password,
            "imap_encryption": self.imap_encryption,
            "smtp_server": self.smtp_server,
            "smtp_port": self.smtp_port,
            "smtp_username": self.smtp_username,
            "smtp_password": mask if (hide_password and self.smtp_password) else self.smtp_password,
            "smtp_encryption": self.smtp_encryption,
            "email_address": self.email_address,
            "display_name": self.display_name,
            "check_interval": self.check_interval,
            "imap_configured": self.imap_configured,
            "smtp_configured": self.smtp_configured,
            "is_configured": self.is_configured,
            "fully_configured": self.fully_configured,
        }


# ── Inbox message (lightweight) ──────────────────────────────────────

@dataclass
class AssistantInboxMessage:
    """A single email in the assistant's inbox."""
    uid: str = ""
    subject: str = ""
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    body_text: str = ""
    body_html: str = ""
    date: Optional[dt.datetime] = None
    is_read: bool = False
    in_reply_to: str = ""
    references: str = ""
    folder: str = "INBOX"

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "subject": self.subject,
            "sender": self.sender,
            "recipients": self.recipients,
            "cc": self.cc,
            "body_text": self.body_text[:500] if self.body_text else "",
            "date": self.date.isoformat() if self.date else None,
            "is_read": self.is_read,
            "folder": self.folder,
        }


# ── Service ───────────────────────────────────────────────────────────

class AssistantMailService:
    """Manages the assistant's own email: reading (IMAP) + sending (SMTP)."""

    def __init__(self, account_service: Optional[Any] = None) -> None:
        self._account_service = account_service
        self._settings = get_settings()

    # ── Configuration ─────────────────────────────────────────────────

    async def get_config(self) -> AssistantEmailConfig:
        """Get the current config (DB first, env fallback)."""
        db_cfg = await self._load_db_config()
        if db_cfg and (db_cfg.imap_configured or db_cfg.smtp_configured):
            logger.info("assistant_email_config_source", source="db",
                        imap_server=db_cfg.imap_server, imap_port=db_cfg.imap_port,
                        imap_enc=db_cfg.imap_encryption, imap_user=db_cfg.imap_username,
                        imap_configured=db_cfg.imap_configured,
                        smtp_server=db_cfg.smtp_server, smtp_port=db_cfg.smtp_port,
                        smtp_enc=db_cfg.smtp_encryption, smtp_user=db_cfg.smtp_username,
                        smtp_configured=db_cfg.smtp_configured,
                        email=db_cfg.email_address)
            return db_cfg
        env_cfg = self._load_env_config()
        logger.info("assistant_email_config_source", source="env",
                    imap_server=env_cfg.imap_server, smtp_server=env_cfg.smtp_server,
                    imap_configured=env_cfg.imap_configured, smtp_configured=env_cfg.smtp_configured)
        return env_cfg

    def _load_env_config(self) -> AssistantEmailConfig:
        s = self._settings
        # Map legacy bool smtp_use_tls to encryption string
        smtp_enc = "starttls" if getattr(s, "assistant_smtp_use_tls", True) else "none"
        imap_enc = "ssl" if getattr(s, "assistant_imap_use_ssl", True) else "none"
        return AssistantEmailConfig(
            imap_server=getattr(s, "assistant_imap_server", ""),
            imap_port=getattr(s, "assistant_imap_port", 993),
            imap_username=getattr(s, "assistant_imap_username", ""),
            imap_password=getattr(s, "assistant_imap_password", ""),
            imap_encryption=imap_enc,
            smtp_server=getattr(s, "assistant_smtp_server", ""),
            smtp_port=getattr(s, "assistant_smtp_port", 587),
            smtp_username=getattr(s, "assistant_smtp_username", ""),
            smtp_password=getattr(s, "assistant_smtp_password", ""),
            smtp_encryption=smtp_enc,
            email_address=getattr(s, "assistant_email_address", ""),
            display_name=getattr(s, "assistant_email_display_name", "") or s.assistant_name,
            check_interval=getattr(s, "assistant_email_check_interval", 10),
        )

    async def _load_db_config(self) -> Optional[AssistantEmailConfig]:
        if not self._account_service:
            logger.debug("assistant_email_db_skip", reason="no_account_service")
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
                    logger.debug("assistant_email_db_skip", reason="no_account_in_db")
                    return None
                c = self._account_service.decrypt_credentials(account)
                logger.debug("assistant_email_db_loaded", keys=list(c.keys()),
                             imap_server=c.get("imap_server", ""),
                             smtp_server=c.get("smtp_server", ""))
                return AssistantEmailConfig(
                    imap_server=c.get("imap_server", ""),
                    imap_port=c.get("imap_port", 993),
                    imap_username=c.get("imap_username", ""),
                    imap_password=c.get("imap_password", ""),
                    imap_encryption=c.get("imap_encryption", "ssl"),
                    smtp_server=c.get("smtp_server", c.get("server", "")),
                    smtp_port=c.get("smtp_port", c.get("port", 587)),
                    smtp_username=c.get("smtp_username", c.get("username", "")),
                    smtp_password=c.get("smtp_password", c.get("password", "")),
                    smtp_encryption=c.get("smtp_encryption", "starttls" if c.get("use_tls", True) else "none"),
                    email_address=c.get("email_address", c.get("username", "")),
                    display_name=c.get("display_name", self._settings.assistant_name),
                    check_interval=c.get("check_interval", 10),
                )
        except Exception as exc:
            logger.error("assistant_email_db_load_failed", error=str(exc))
            return None

    async def save_config(self, cfg: AssistantEmailConfig) -> None:
        if not self._account_service:
            raise RuntimeError("AccountService not available")

        credentials = {
            "imap_server": cfg.imap_server,
            "imap_port": cfg.imap_port,
            "imap_username": cfg.imap_username,
            "imap_password": cfg.imap_password,
            "imap_encryption": cfg.imap_encryption,
            "smtp_server": cfg.smtp_server,
            "smtp_port": cfg.smtp_port,
            "smtp_username": cfg.smtp_username,
            "smtp_password": cfg.smtp_password,
            "smtp_encryption": cfg.smtp_encryption,
            "email_address": cfg.email_address,
            "display_name": cfg.display_name,
            "check_interval": cfg.check_interval,
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

    # ── IMAP helpers ──────────────────────────────────────────────────

    def _connect_imap(self, cfg: AssistantEmailConfig) -> imaplib.IMAP4:
        """Create an IMAP connection respecting the encryption setting."""
        logger.info("imap_connecting", server=cfg.imap_server, port=cfg.imap_port,
                    encryption=cfg.imap_encryption, username=cfg.imap_username)
        if cfg.imap_encryption == "ssl":
            conn = imaplib.IMAP4_SSL(cfg.imap_server, cfg.imap_port, timeout=20)
        else:
            conn = imaplib.IMAP4(cfg.imap_server, cfg.imap_port, timeout=20)
            if cfg.imap_encryption == "starttls":
                conn.starttls()
        conn.login(cfg.imap_username, cfg.imap_password)
        logger.info("imap_connected", server=cfg.imap_server)
        return conn

    # ── SMTP helpers ──────────────────────────────────────────────────

    def _connect_smtp(self, cfg: AssistantEmailConfig) -> smtplib.SMTP:
        """Create an SMTP connection respecting the encryption setting."""
        logger.info("smtp_connecting", server=cfg.smtp_server, port=cfg.smtp_port,
                    encryption=cfg.smtp_encryption, username=cfg.smtp_username)
        if cfg.smtp_encryption == "ssl":
            server = smtplib.SMTP_SSL(cfg.smtp_server, cfg.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(cfg.smtp_server, cfg.smtp_port, timeout=20)
            server.ehlo()
            if cfg.smtp_encryption == "starttls":
                server.starttls()
                server.ehlo()
        server.login(cfg.smtp_username, cfg.smtp_password)
        logger.info("smtp_connected", server=cfg.smtp_server)
        return server

    # ── Connection tests ──────────────────────────────────────────────

    async def test_imap(self, cfg: Optional[AssistantEmailConfig] = None) -> tuple[bool, str]:
        """Test the IMAP connection."""
        logger.info("test_imap_start", cfg_provided=cfg is not None)
        if cfg is None:
            cfg = await self.get_config()
        logger.info("test_imap_config", server=cfg.imap_server, port=cfg.imap_port,
                    encryption=cfg.imap_encryption, user=cfg.imap_username,
                    has_password=bool(cfg.imap_password), configured=cfg.imap_configured)
        if not cfg.imap_configured:
            return False, "IMAP not configured."
        try:
            def _test():
                conn = self._connect_imap(cfg)
                conn.select("INBOX")
                conn.logout()
            await asyncio.wait_for(asyncio.to_thread(_test), timeout=20)
            logger.info("test_imap_success", server=cfg.imap_server)
            return True, "IMAP connection successful."
        except asyncio.TimeoutError:
            logger.error("test_imap_timeout", server=cfg.imap_server, port=cfg.imap_port)
            return False, "IMAP connection timed out."
        except imaplib.IMAP4.error as exc:
            logger.error("test_imap_auth_failed", server=cfg.imap_server, error=str(exc))
            return False, f"IMAP auth failed: {exc}"
        except Exception as exc:
            logger.error("test_imap_error", server=cfg.imap_server, port=cfg.imap_port,
                         encryption=cfg.imap_encryption, error=str(exc), error_type=type(exc).__name__)
            return False, f"IMAP error: {exc}"

    async def test_smtp(self, cfg: Optional[AssistantEmailConfig] = None) -> tuple[bool, str]:
        """Test the SMTP connection."""
        logger.info("test_smtp_start", cfg_provided=cfg is not None)
        if cfg is None:
            cfg = await self.get_config()
        logger.info("test_smtp_config", server=cfg.smtp_server, port=cfg.smtp_port,
                    encryption=cfg.smtp_encryption, user=cfg.smtp_username,
                    has_password=bool(cfg.smtp_password), configured=cfg.smtp_configured)
        if not cfg.smtp_configured:
            return False, "SMTP not configured."
        try:
            def _test():
                server = self._connect_smtp(cfg)
                server.quit()
            await asyncio.wait_for(asyncio.to_thread(_test), timeout=20)
            logger.info("test_smtp_success", server=cfg.smtp_server)
            return True, "SMTP connection successful."
        except asyncio.TimeoutError:
            logger.error("test_smtp_timeout", server=cfg.smtp_server, port=cfg.smtp_port)
            return False, "SMTP connection timed out."
        except smtplib.SMTPAuthenticationError as exc:
            logger.error("test_smtp_auth_failed", server=cfg.smtp_server, error=str(exc))
            return False, "SMTP auth failed. Check username and password."
        except Exception as exc:
            logger.error("test_smtp_error", server=cfg.smtp_server, port=cfg.smtp_port,
                         encryption=cfg.smtp_encryption, error=str(exc), error_type=type(exc).__name__)
            return False, f"SMTP error: {exc}"

    async def test_connection(self, cfg: Optional[AssistantEmailConfig] = None) -> tuple[bool, str]:
        """Test both IMAP and SMTP, return combined result."""
        if cfg is None:
            cfg = await self.get_config()
        results = []
        if cfg.imap_configured:
            ok, msg = await self.test_imap(cfg)
            results.append(("IMAP", ok, msg))
        if cfg.smtp_configured:
            ok, msg = await self.test_smtp(cfg)
            results.append(("SMTP", ok, msg))
        if not results:
            return False, "Nothing configured to test."
        all_ok = all(r[1] for r in results)
        summary = "; ".join(f"{r[0]}: {r[2]}" for r in results)
        return all_ok, summary

    # ── Reading (IMAP) ────────────────────────────────────────────────

    async def fetch_emails(
        self,
        folder: str = "INBOX",
        unread_only: bool = False,
        limit: int = 20,
    ) -> list[AssistantInboxMessage]:
        """Fetch emails from the assistant's IMAP inbox."""
        cfg = await self.get_config()
        if not cfg.imap_configured:
            return []

        try:
            def _fetch():
                conn = self._connect_imap(cfg)
                try:
                    conn.select(folder)
                    criteria = "UNSEEN" if unread_only else "ALL"
                    _, msg_nums = conn.search(None, criteria)
                    msg_ids = msg_nums[0].split()
                    if limit:
                        msg_ids = msg_ids[-limit:]

                    messages: list[AssistantInboxMessage] = []
                    for msg_id in reversed(msg_ids):
                        _, data = conn.fetch(msg_id, "(RFC822 FLAGS)")
                        if not data or not data[0]:
                            continue
                        raw = data[0][1]
                        msg = email_lib.message_from_bytes(raw)

                        subject = ""
                        raw_subject = msg.get("Subject", "")
                        if raw_subject:
                            decoded = decode_header(raw_subject)
                            subject = (
                                str(decoded[0][0], decoded[0][1] or "utf-8")
                                if isinstance(decoded[0][0], bytes)
                                else str(decoded[0][0])
                            )

                        body_text = ""
                        body_html = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                ct = part.get_content_type()
                                cd = str(part.get("Content-Disposition", ""))
                                if ct == "text/plain" and "attachment" not in cd:
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body_text = payload.decode("utf-8", errors="replace")
                                elif ct == "text/html" and "attachment" not in cd:
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        body_html = payload.decode("utf-8", errors="replace")
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode("utf-8", errors="replace")

                        flags_raw = data[0][0].decode() if isinstance(data[0][0], bytes) else ""
                        is_read = "\\Seen" in flags_raw

                        date = None
                        try:
                            date = email_lib.utils.parsedate_to_datetime(msg.get("Date", ""))
                        except Exception:
                            pass

                        messages.append(AssistantInboxMessage(
                            uid=msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id),
                            subject=subject,
                            sender=msg.get("From", ""),
                            recipients=[r.strip() for r in msg.get("To", "").split(",") if r.strip()],
                            cc=[r.strip() for r in (msg.get("Cc") or "").split(",") if r.strip()],
                            body_text=body_text,
                            body_html=body_html,
                            date=date,
                            is_read=is_read,
                            in_reply_to=msg.get("In-Reply-To", ""),
                            references=msg.get("References", ""),
                            folder=folder,
                        ))
                    return messages
                finally:
                    conn.logout()

            return await asyncio.to_thread(_fetch)
        except Exception as exc:
            logger.error("assistant_email_fetch_failed", error=str(exc))
            return []

    async def check_inbox(self) -> list[AssistantInboxMessage]:
        """Check for unread emails — used by the scheduled task."""
        emails = await self.fetch_emails(unread_only=True, limit=10)
        if emails:
            logger.info("assistant_inbox_check", unread=len(emails),
                        subjects=[e.subject[:50] for e in emails[:3]])
        return emails

    # ── Sending (SMTP) ────────────────────────────────────────────────

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body_text: str,
        body_html: str = "",
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        in_reply_to: str = "",
        references: str = "",
    ) -> bool:
        """Send an email from the assistant's own address."""
        cfg = await self.get_config()
        if not cfg.smtp_configured:
            logger.error("assistant_smtp_not_configured")
            return False

        try:
            def _send():
                msg = email.mime.multipart.MIMEMultipart("alternative")
                from_header = (
                    f"{cfg.display_name} <{cfg.email_address}>"
                    if cfg.display_name else cfg.email_address
                )
                msg["From"] = from_header
                msg["To"] = ", ".join(to)
                msg["Subject"] = subject
                if cc:
                    msg["Cc"] = ", ".join(cc)
                if in_reply_to:
                    msg["In-Reply-To"] = in_reply_to
                    msg["References"] = references or in_reply_to

                if body_text:
                    msg.attach(email.mime.text.MIMEText(body_text, "plain"))
                if body_html:
                    msg.attach(email.mime.text.MIMEText(body_html, "html"))

                all_recipients = list(to) + (cc or []) + (bcc or [])

                server = self._connect_smtp(cfg)
                try:
                    server.sendmail(cfg.email_address, all_recipients, msg.as_string())
                finally:
                    server.quit()

            await asyncio.to_thread(_send)
            logger.info("assistant_email_sent", to=to, subject=subject)
            return True
        except Exception as exc:
            logger.error("assistant_email_send_failed", to=to, subject=subject, error=str(exc))
            return False

    async def reply_email(
        self,
        original: AssistantInboxMessage,
        body_text: str,
        body_html: str = "",
        reply_all: bool = False,
    ) -> bool:
        """Reply to an email in the assistant's inbox."""
        recipients = [original.sender]
        if reply_all:
            recipients.extend(original.recipients)
            recipients.extend(original.cc)
            # Remove our own address
            cfg = await self.get_config()
            recipients = list(set(r for r in recipients if cfg.email_address.lower() not in r.lower()))

        subject = original.subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        return await self.send_email(
            to=recipients,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            in_reply_to=original.uid,
            references=original.references or original.uid,
        )
