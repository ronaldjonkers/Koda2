"""Email service — unified email management across IMAP/SMTP and Gmail."""

from __future__ import annotations

import asyncio
import email as email_lib
import email.mime.multipart
import email.mime.text
import email.mime.base
import email.encoders
import imaplib
import smtplib
from email.header import decode_header
from pathlib import Path
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from executiveai.config import get_settings
from executiveai.logging_config import get_logger
from executiveai.modules.email.models import (
    EmailAttachment,
    EmailFilter,
    EmailMessage,
    EmailPriority,
    EmailProvider,
    EmailTemplate,
)

logger = get_logger(__name__)


class EmailService:
    """Unified email management service."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._templates: dict[str, EmailTemplate] = {}

    @property
    def imap_configured(self) -> bool:
        return bool(self._settings.imap_server and self._settings.imap_username)

    @property
    def smtp_configured(self) -> bool:
        return bool(self._settings.smtp_server and self._settings.smtp_username)

    @property
    def gmail_configured(self) -> bool:
        return Path(self._settings.google_credentials_file).exists()

    # ── IMAP Operations ──────────────────────────────────────────────

    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        """Create an IMAP connection."""
        conn = imaplib.IMAP4_SSL(self._settings.imap_server, self._settings.imap_port)
        conn.login(self._settings.imap_username, self._settings.imap_password)
        return conn

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def fetch_emails(self, filter_: Optional[EmailFilter] = None) -> list[EmailMessage]:
        """Fetch emails from IMAP server."""
        if not self.imap_configured:
            logger.warning("imap_not_configured")
            return []

        f = filter_ or EmailFilter()

        def _fetch():
            conn = self._connect_imap()
            try:
                conn.select(f.folder)
                criteria = []
                if f.unread_only:
                    criteria.append("UNSEEN")
                if f.since:
                    criteria.append(f'SINCE {f.since.strftime("%d-%b-%Y")}')
                if f.before:
                    criteria.append(f'BEFORE {f.before.strftime("%d-%b-%Y")}')
                if f.sender:
                    criteria.append(f'FROM "{f.sender}"')
                if f.subject_contains:
                    criteria.append(f'SUBJECT "{f.subject_contains}"')

                search_str = " ".join(criteria) if criteria else "ALL"
                _, msg_nums = conn.search(None, search_str)
                msg_ids = msg_nums[0].split()

                if f.limit:
                    msg_ids = msg_ids[-f.limit:]

                messages = []
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
                        subject = str(decoded[0][0], decoded[0][1] or "utf-8") if isinstance(decoded[0][0], bytes) else str(decoded[0][0])

                    sender = msg.get("From", "")
                    body_text = ""
                    body_html = ""
                    attachments = []

                    if msg.is_multipart():
                        for part in msg.walk():
                            ct = part.get_content_type()
                            cd = str(part.get("Content-Disposition", ""))
                            if ct == "text/plain" and "attachment" not in cd:
                                body_text = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            elif ct == "text/html" and "attachment" not in cd:
                                body_html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            elif "attachment" in cd:
                                filename = part.get_filename() or "attachment"
                                attachments.append(EmailAttachment(
                                    filename=filename,
                                    content_type=ct,
                                    size=len(part.get_payload(decode=True) or b""),
                                ))
                    else:
                        body_text = msg.get_payload(decode=True).decode("utf-8", errors="replace")

                    flags = data[0][0].decode() if isinstance(data[0][0], bytes) else ""
                    is_read = "\\Seen" in flags

                    messages.append(EmailMessage(
                        provider=EmailProvider.IMAP_SMTP,
                        provider_id=msg_id.decode(),
                        subject=subject,
                        sender=sender,
                        recipients=msg.get("To", "").split(","),
                        cc=msg.get("Cc", "").split(",") if msg.get("Cc") else [],
                        body_text=body_text,
                        body_html=body_html,
                        attachments=attachments,
                        is_read=is_read,
                        folder=f.folder,
                        in_reply_to=msg.get("In-Reply-To", ""),
                        references=msg.get("References", ""),
                        date=email_lib.utils.parsedate_to_datetime(msg.get("Date", "")),
                    ))
                return messages
            finally:
                conn.logout()

        return await asyncio.to_thread(_fetch)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send_email(self, message: EmailMessage) -> bool:
        """Send an email via SMTP."""
        if not self.smtp_configured:
            logger.error("smtp_not_configured")
            return False

        def _send():
            msg = email.mime.multipart.MIMEMultipart("mixed")
            msg["Subject"] = message.subject
            msg["From"] = message.sender or self._settings.smtp_username
            msg["To"] = ", ".join(message.recipients)
            if message.cc:
                msg["Cc"] = ", ".join(message.cc)
            if message.in_reply_to:
                msg["In-Reply-To"] = message.in_reply_to
                msg["References"] = message.references

            body_part = email.mime.multipart.MIMEMultipart("alternative")
            if message.body_text:
                body_part.attach(email.mime.text.MIMEText(message.body_text, "plain"))
            if message.body_html:
                body_part.attach(email.mime.text.MIMEText(message.body_html, "html"))
            msg.attach(body_part)

            for att in message.attachments:
                if att.data:
                    part = email.mime.base.MIMEBase(*att.content_type.split("/", 1))
                    part.set_payload(att.data)
                    email.encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{att.filename}"')
                    msg.attach(part)

            all_recipients = message.recipients + message.cc + message.bcc
            with smtplib.SMTP(self._settings.smtp_server, self._settings.smtp_port) as server:
                if self._settings.smtp_use_tls:
                    server.starttls()
                server.login(self._settings.smtp_username, self._settings.smtp_password)
                server.sendmail(msg["From"], all_recipients, msg.as_string())
            return True

        result = await asyncio.to_thread(_send)
        logger.info("email_sent", subject=message.subject, to=message.recipients)
        return result

    async def reply(self, original: EmailMessage, body_text: str, body_html: str = "") -> bool:
        """Reply to an existing email."""
        reply_msg = EmailMessage(
            subject=f"Re: {original.subject}" if not original.subject.startswith("Re:") else original.subject,
            sender=self._settings.smtp_username,
            recipients=[original.sender],
            body_text=body_text,
            body_html=body_html,
            in_reply_to=original.provider_id,
            references=f"{original.references} {original.provider_id}".strip(),
        )
        return await self.send_email(reply_msg)

    async def prioritize_inbox(self, emails: Optional[list[EmailMessage]] = None) -> list[EmailMessage]:
        """Sort emails by priority using heuristics."""
        if emails is None:
            emails = await self.fetch_emails(EmailFilter(unread_only=True))

        def _priority_score(msg: EmailMessage) -> int:
            score = msg.priority.value * 10
            subject_lower = msg.subject.lower()
            if any(w in subject_lower for w in ["urgent", "asap", "critical", "important"]):
                score -= 20
            if msg.has_attachments:
                score -= 5
            if any(w in subject_lower for w in ["newsletter", "digest", "weekly", "notification"]):
                score += 20
            return score

        return sorted(emails, key=_priority_score)

    # ── Templates ────────────────────────────────────────────────────

    def register_template(self, template: EmailTemplate) -> None:
        """Register a reusable email template."""
        self._templates[template.name] = template
        logger.debug("template_registered", name=template.name)

    def render_template(self, template_name: str, variables: dict[str, str]) -> EmailMessage:
        """Render an email template with variables."""
        tmpl = self._templates.get(template_name)
        if not tmpl:
            raise ValueError(f"Template not found: {template_name}")

        from jinja2 import Template

        subject = Template(tmpl.subject).render(**variables)
        body_text = Template(tmpl.body_text).render(**variables) if tmpl.body_text else ""
        body_html = Template(tmpl.body_html).render(**variables) if tmpl.body_html else ""

        return EmailMessage(subject=subject, body_text=body_text, body_html=body_html)
