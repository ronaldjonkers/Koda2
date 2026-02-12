"""Email service — unified email management with multi-account support."""

from __future__ import annotations

import asyncio
import base64
import email as email_lib
import email.mime.multipart
import email.mime.text
import email.mime.base
import email.encoders
import imaplib
import os
import smtplib
from email.header import decode_header
from pathlib import Path
from typing import Optional, Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.account.models import AccountType, ProviderType
from koda2.modules.email.models import (
    EmailAttachment,
    EmailFilter,
    EmailMessage,
    EmailPriority,
    EmailProvider,
    EmailTemplate,
)

logger = get_logger(__name__)


class EmailService:
    """Unified email management service with multi-account support."""

    def __init__(self, account_service: Optional[Any] = None) -> None:
        self._settings = get_settings()
        self._account_service = account_service
        self._templates: dict[str, EmailTemplate] = {}

    async def _get_email_accounts(self) -> list:
        """Get all active email accounts."""
        if not self._account_service:
            return []
        return await self._account_service.get_accounts(
            account_type=AccountType.EMAIL,
            active_only=True,
        )

    async def _get_default_account(self) -> Optional[Any]:
        """Get the default email account."""
        if not self._account_service:
            return None
        return await self._account_service.get_default_account(AccountType.EMAIL)

    async def imap_configured(self) -> bool:
        """Check if any IMAP account is configured."""
        accounts = await self._get_email_accounts()
        return any(acc.provider == ProviderType.IMAP.value for acc in accounts)

    async def smtp_configured(self) -> bool:
        """Check if any SMTP account is configured."""
        accounts = await self._get_email_accounts()
        return any(acc.provider == ProviderType.SMTP.value for acc in accounts)

    async def msgraph_configured(self) -> bool:
        """Check if any MS Graph account is configured."""
        accounts = await self._get_email_accounts()
        return any(acc.provider == ProviderType.MSGRAPH.value for acc in accounts)

    async def gmail_configured(self) -> bool:
        """Check if any Gmail account is configured."""
        accounts = await self._get_email_accounts()
        return any(acc.provider == ProviderType.GOOGLE.value for acc in accounts)

    # ── IMAP Operations ──────────────────────────────────────────────

    def _connect_imap(self, server: str, port: int, username: str, password: str, use_ssl: bool = True) -> imaplib.IMAP4_SSL:
        """Create an IMAP connection."""
        if use_ssl:
            conn = imaplib.IMAP4_SSL(server, port)
        else:
            conn = imaplib.IMAP4(server, port)
        conn.login(username, password)
        return conn

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def fetch_emails(
        self,
        filter_: Optional[EmailFilter] = None,
        account_id: Optional[str] = None,
    ) -> list[EmailMessage]:
        """Fetch emails from IMAP server."""
        if not self._account_service:
            return []

        # Get specific account or all IMAP accounts
        if account_id:
            account = await self._account_service.get_account(account_id)
            accounts = [account] if account else []
        else:
            all_accounts = await self._get_email_accounts()
            accounts = [a for a in all_accounts if a.provider == ProviderType.IMAP.value]

        if not accounts:
            logger.warning("no_imap_accounts_configured")
            return []

        f = filter_ or EmailFilter()
        all_messages = []

        for account in accounts:
            try:
                credentials = self._account_service.decrypt_credentials(account)
                
                def _fetch():
                    conn = self._connect_imap(
                        credentials["server"],
                        credentials.get("port", 993),
                        credentials["username"],
                        credentials["password"],
                        credentials.get("use_ssl", True),
                    )
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
                                account_name=account.name,
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

                messages = await asyncio.to_thread(_fetch)
                all_messages.extend(messages)
                
            except Exception as exc:
                logger.error("fetch_emails_failed", account=account.name, error=str(exc))

        return all_messages

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def send_email(
        self,
        message: EmailMessage,
        account_id: Optional[str] = None,
    ) -> bool:
        """Send an email via SMTP."""
        if not self._account_service:
            logger.error("account_service_not_available")
            return False

        # Get specific account or default SMTP account
        if account_id:
            account = await self._account_service.get_account(account_id)
        else:
            accounts = await self._get_email_accounts()
            account = next((a for a in accounts if a.provider == ProviderType.SMTP.value), None)
            if not account:
                account = next((a for a in accounts if a.provider == ProviderType.IMAP.value), None)

        if not account:
            logger.error("no_smtp_account_configured")
            return False

        try:
            credentials = self._account_service.decrypt_credentials(account)
            
            def _send():
                msg = email.mime.multipart.MIMEMultipart("mixed")
                msg["Subject"] = message.subject
                msg["From"] = message.sender or credentials["username"]
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
                with smtplib.SMTP(credentials["server"], credentials.get("port", 587)) as server:
                    if credentials.get("use_tls", True):
                        server.starttls()
                    server.login(credentials["username"], credentials["password"])
                    server.sendmail(msg["From"], all_recipients, msg.as_string())
                return True

            result = await asyncio.to_thread(_send)
            logger.info("email_sent", subject=message.subject, to=message.recipients, account=account.name)
            return result
            
        except Exception as exc:
            logger.error("send_email_failed", account=account.name, error=str(exc))
            return False

    async def reply(
        self,
        original: EmailMessage,
        body_text: str,
        body_html: str = "",
    ) -> bool:
        """Reply to an existing email."""
        # Find the account that received this email
        if not self._account_service:
            return False
            
        accounts = await self._get_email_accounts()
        account = None
        for acc in accounts:
            if acc.name == original.account_name:
                account = acc
                break
        
        if not account:
            account = await self._get_default_account()
        
        if not account:
            logger.error("no_account_for_reply")
            return False

        reply_msg = EmailMessage(
            subject=f"Re: {original.subject}" if not original.subject.startswith("Re:") else original.subject,
            recipients=[original.sender],
            body_text=body_text,
            body_html=body_html,
            in_reply_to=original.provider_id,
            references=f"{original.references} {original.provider_id}".strip(),
        )
        return await self.send_email(reply_msg, account.id if account else None)

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

    # ── Microsoft Graph API (Office 365) ─────────────────────────────

    async def fetch_emails_msgraph(
        self,
        folder: str = "inbox",
        unread_only: bool = False,
        limit: int = 50,
        account_id: Optional[str] = None,
    ) -> list[EmailMessage]:
        """Fetch emails using Microsoft Graph API."""
        if not self._account_service:
            return []

        # Get specific account or all MS Graph accounts
        if account_id:
            account = await self._account_service.get_account(account_id)
            accounts = [account] if account else []
        else:
            all_accounts = await self._get_email_accounts()
            accounts = [a for a in all_accounts if a.provider == ProviderType.MSGRAPH.value]

        if not accounts:
            logger.warning("no_msgraph_accounts_configured")
            return []

        all_emails = []

        for account in accounts:
            try:
                credentials = self._account_service.decrypt_credentials(account)
                
                import httpx

                # Get token
                token_url = f"https://login.microsoftonline.com/{credentials['tenant_id']}/oauth2/v2.0/token"
                async with httpx.AsyncClient() as client:
                    token_resp = await client.post(token_url, data={
                        "client_id": credentials["client_id"],
                        "client_secret": credentials["client_secret"],
                        "scope": "https://graph.microsoft.com/.default",
                        "grant_type": "client_credentials",
                    })
                    token_resp.raise_for_status()
                    token = token_resp.json()["access_token"]

                    # Fetch emails
                    url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder}/messages"
                    params = {
                        "$top": limit,
                        "$orderby": "receivedDateTime desc",
                        "$select": "id,subject,from,toRecipients,receivedDateTime,body,isRead,hasAttachments",
                    }
                    if unread_only:
                        params["$filter"] = "isRead eq false"

                    resp = await client.get(url, params=params, headers={"Authorization": f"Bearer {token}"})
                    resp.raise_for_status()
                    data = resp.json()

                    for msg in data.get("value", []):
                        all_emails.append(EmailMessage(
                            provider=EmailProvider.OFFICE365,
                            provider_id=msg["id"],
                            account_name=account.name,
                            subject=msg.get("subject", ""),
                            sender=msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                            recipients=[
                                r.get("emailAddress", {}).get("address", "")
                                for r in msg.get("toRecipients", [])
                            ],
                            body_text=msg.get("body", {}).get("content", "") if msg.get("body", {}).get("contentType") == "text" else "",
                            body_html=msg.get("body", {}).get("content", "") if msg.get("body", {}).get("contentType") == "html" else "",
                            is_read=msg.get("isRead", True),
                            has_attachments=msg.get("hasAttachments", False),
                            date=dt.datetime.fromisoformat(msg["receivedDateTime"].replace("Z", "+00:00")),
                        ))

            except Exception as e:
                logger.error("msgraph_fetch_failed", account=account.name, error=str(e))

        return all_emails

    async def send_email_msgraph(
        self,
        message: EmailMessage,
        account_id: Optional[str] = None,
    ) -> bool:
        """Send email using Microsoft Graph API."""
        if not self._account_service:
            return False

        # Get specific account or default
        if account_id:
            account = await self._account_service.get_account(account_id)
        else:
            accounts = await self._get_email_accounts()
            account = next((a for a in accounts if a.provider == ProviderType.MSGRAPH.value), None)

        if not account:
            logger.error("no_msgraph_account_configured")
            return False

        try:
            credentials = self._account_service.decrypt_credentials(account)
            
            import httpx

            # Get token
            token_url = f"https://login.microsoftonline.com/{credentials['tenant_id']}/oauth2/v2.0/token"
            async with httpx.AsyncClient() as client:
                token_resp = await client.post(token_url, data={
                    "client_id": credentials["client_id"],
                    "client_secret": credentials["client_secret"],
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                })
                token_resp.raise_for_status()
                token = token_resp.json()["access_token"]

                # Send email
                email_data = {
                    "message": {
                        "subject": message.subject,
                        "body": {
                            "contentType": "HTML" if message.body_html else "Text",
                            "content": message.body_html or message.body_text,
                        },
                        "toRecipients": [
                            {"emailAddress": {"address": addr}}
                            for addr in message.recipients
                        ],
                    },
                    "saveToSentItems": True,
                }

                if message.cc:
                    email_data["message"]["ccRecipients"] = [
                        {"emailAddress": {"address": addr}}
                        for addr in message.cc
                    ]

                resp = await client.post(
                    "https://graph.microsoft.com/v1.0/me/sendMail",
                    json=email_data,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                resp.raise_for_status()

                logger.info("msgraph_email_sent", subject=message.subject, account=account.name)
                return True

        except Exception as e:
            logger.error("msgraph_send_failed", account=account.name, error=str(e))
            return False

    # ── Gmail API ────────────────────────────────────────────────────

    async def fetch_emails_gmail(
        self,
        query: str = "",
        max_results: int = 50,
        account_id: Optional[str] = None,
    ) -> list[EmailMessage]:
        """Fetch emails using Gmail API."""
        if not self._account_service:
            return []

        # Get specific account or all Gmail accounts
        if account_id:
            account = await self._account_service.get_account(account_id)
            accounts = [account] if account else []
        else:
            all_accounts = await self._get_email_accounts()
            accounts = [a for a in all_accounts if a.provider == ProviderType.GOOGLE.value]

        if not accounts:
            logger.warning("no_gmail_accounts_configured")
            return []

        all_emails = []

        for account in accounts:
            try:
                credentials = self._account_service.decrypt_credentials(account)
                
                from google.oauth2.credentials import Credentials
                from googleapiclient.discovery import build

                def _fetch():
                    # Use token_file (has OAuth token), not credentials_file (has client secrets)
                    token_path = credentials.get("token_file", credentials.get("credentials_file"))
                    creds = Credentials.from_authorized_user_file(token_path)
                    # Refresh if expired
                    if creds and creds.expired and creds.refresh_token:
                        from google.auth.transport.requests import Request
                        creds.refresh(Request())
                        from pathlib import Path
                        Path(token_path).write_text(creds.to_json())
                    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

                    result = service.users().messages().list(
                        userId="me",
                        q=query,
                        maxResults=max_results,
                    ).execute()

                    messages = result.get("messages", [])
                    emails = []

                    for msg_meta in messages:
                        msg = service.users().messages().get(
                            userId="me",
                            id=msg_meta["id"],
                            format="full",
                        ).execute()

                        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}

                        # Get body
                        body_text = ""
                        body_html = ""

                        def get_body(parts):
                            nonlocal body_text, body_html
                            for part in parts:
                                if part.get("mimeType") == "text/plain" and "data" in part.get("body", {}):
                                    import base64
                                    body_text = base64.urlsafe_b64decode(
                                        part["body"]["data"]
                                    ).decode("utf-8")
                                elif part.get("mimeType") == "text/html" and "data" in part.get("body", {}):
                                    import base64
                                    body_html = base64.urlsafe_b64decode(
                                        part["body"]["data"]
                                    ).decode("utf-8")
                                if "parts" in part:
                                    get_body(part["parts"])

                        if "parts" in msg["payload"]:
                            get_body(msg["payload"]["parts"])
                        elif "body" in msg["payload"] and "data" in msg["payload"]["body"]:
                            import base64
                            body_text = base64.urlsafe_b64decode(
                                msg["payload"]["body"]["data"]
                            ).decode("utf-8")

                        emails.append(EmailMessage(
                            provider=EmailProvider.GMAIL,
                            provider_id=msg["id"],
                            account_name=account.name,
                            subject=headers.get("Subject", ""),
                            sender=headers.get("From", ""),
                            recipients=headers.get("To", "").split(","),
                            body_text=body_text,
                            body_html=body_html,
                            is_read="UNREAD" not in msg.get("labelIds", []),
                            has_attachments="has:attachment" in str(msg.get("payload", {})),
                            date=dt.datetime.fromtimestamp(int(msg["internalDate"]) / 1000, dt.UTC),
                        ))

                    return emails

                emails = await asyncio.to_thread(_fetch)
                all_emails.extend(emails)

            except Exception as e:
                logger.error("gmail_fetch_failed", account=account.name, error=str(e))

        return all_emails

    # ── Unified Email Operations ─────────────────────────────────────

    async def fetch_all_emails(
        self,
        unread_only: bool = False,
        limit: int = 50,
    ) -> list[EmailMessage]:
        """Fetch emails from all configured providers."""
        all_emails = []

        # IMAP accounts
        emails = await self.fetch_emails(EmailFilter(unread_only=unread_only, limit=limit))
        all_emails.extend(emails)

        # MS Graph accounts
        emails = await self.fetch_emails_msgraph(unread_only=unread_only, limit=limit)
        all_emails.extend(emails)

        # Gmail accounts
        gmail_query = "is:unread" if unread_only else ""
        emails = await self.fetch_emails_gmail(query=gmail_query, max_results=limit)
        all_emails.extend(emails)

        # Sort by date (newest first), handle mixed tz-aware/naive
        def _sort_key(e):
            d = e.date
            if d and d.tzinfo is not None:
                d = d.replace(tzinfo=None)
            return d or dt.datetime.min
        all_emails.sort(key=_sort_key, reverse=True)
        return all_emails[:limit]

    # ── Attachment Operations ────────────────────────────────────────

    async def download_attachment(
        self,
        message_id: str,
        attachment_filename: str,
        account_id: Optional[str] = None,
        output_dir: str = "data/attachments",
    ) -> Optional[str]:
        """Download an email attachment to disk.
        
        Returns:
            Path to downloaded file, or None if failed.
        """
        if not self._account_service:
            return None

        account = await self._account_service.get_account(account_id) if account_id else None
        if not account:
            accounts = await self._get_email_accounts()
            account = next((a for a in accounts if a.provider == ProviderType.IMAP.value), None)

        if not account:
            logger.error("no_account_for_attachment_download")
            return None

        try:
            credentials = self._account_service.decrypt_credentials(account)
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            def _download():
                conn = self._connect_imap(
                    credentials["server"],
                    credentials.get("port", 993),
                    credentials["username"],
                    credentials["password"],
                    credentials.get("use_ssl", True),
                )
                try:
                    conn.select("INBOX")
                    _, data = conn.fetch(message_id, "(RFC822)")
                    if not data or not data[0]:
                        return None

                    raw = data[0][1]
                    msg = email_lib.message_from_bytes(raw)

                    for part in msg.walk():
                        cd = str(part.get("Content-Disposition", ""))
                        if "attachment" in cd:
                            filename = part.get_filename()
                            if filename == attachment_filename:
                                file_path = output_path / filename
                                payload = part.get_payload(decode=True)
                                if payload:
                                    file_path.write_bytes(payload)
                                    return str(file_path)
                    return None
                finally:
                    conn.logout()

            result = await asyncio.to_thread(_download)
            if result:
                logger.info("attachment_downloaded", path=result, filename=attachment_filename)
            return result

        except Exception as exc:
            logger.error("download_attachment_failed", error=str(exc))
            return None

    async def download_attachment_msgraph(
        self,
        message_id: str,
        attachment_id: str,
        filename: str,
        account_id: Optional[str] = None,
        output_dir: str = "data/attachments",
    ) -> Optional[str]:
        """Download an attachment using Microsoft Graph API."""
        if not self._account_service:
            return None

        account = await self._account_service.get_account(account_id) if account_id else None
        if not account:
            accounts = await self._get_email_accounts()
            account = next((a for a in accounts if a.provider == ProviderType.MSGRAPH.value), None)

        if not account:
            logger.error("no_msgraph_account_for_attachment")
            return None

        try:
            credentials = self._account_service.decrypt_credentials(account)
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Get token
            token_url = f"https://login.microsoftonline.com/{credentials['tenant_id']}/oauth2/v2.0/token"
            async with httpx.AsyncClient() as client:
                token_resp = await client.post(token_url, data={
                    "client_id": credentials["client_id"],
                    "client_secret": credentials["client_secret"],
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                })
                token_resp.raise_for_status()
                token = token_resp.json()["access_token"]

                # Download attachment
                url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/attachments/{attachment_id}"
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                resp.raise_for_status()
                data = resp.json()

                content = base64.b64decode(data.get("contentBytes", ""))
                file_path = output_path / filename
                file_path.write_bytes(content)
                logger.info("msgraph_attachment_downloaded", path=str(file_path))
                return str(file_path)

        except Exception as exc:
            logger.error("msgraph_download_attachment_failed", error=str(exc))
            return None

    async def download_attachment_gmail(
        self,
        message_id: str,
        attachment_id: str,
        filename: str,
        account_id: Optional[str] = None,
        output_dir: str = "data/attachments",
    ) -> Optional[str]:
        """Download an attachment using Gmail API."""
        if not self._account_service:
            return None

        account = await self._account_service.get_account(account_id) if account_id else None
        if not account:
            accounts = await self._get_email_accounts()
            account = next((a for a in accounts if a.provider == ProviderType.GOOGLE.value), None)

        if not account:
            logger.error("no_gmail_account_for_attachment")
            return None

        try:
            credentials = self._account_service.decrypt_credentials(account)
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            def _download():
                creds = Credentials.from_authorized_user_file(credentials["credentials_file"])
                service = build("gmail", "v1", credentials=creds, cache_discovery=False)

                attachment = service.users().messages().attachments().get(
                    userId="me",
                    messageId=message_id,
                    id=attachment_id,
                ).execute()

                data = base64.urlsafe_b64decode(attachment["data"])
                file_path = output_path / filename
                file_path.write_bytes(data)
                return str(file_path)

            result = await asyncio.to_thread(_download)
            logger.info("gmail_attachment_downloaded", path=result)
            return result

        except Exception as exc:
            logger.error("gmail_download_attachment_failed", error=str(exc))
            return None

    async def send_email_with_attachments(
        self,
        to: list[str],
        subject: str,
        body_text: str = "",
        body_html: str = "",
        attachment_paths: Optional[list[str]] = None,
        cc: Optional[list[str]] = None,
        bcc: Optional[list[str]] = None,
        account_id: Optional[str] = None,
    ) -> bool:
        """Send an email with file attachments (convenience method).
        
        Args:
            to: List of recipient email addresses
            subject: Email subject
            body_text: Plain text body
            body_html: HTML body (optional)
            attachment_paths: List of file paths to attach
            cc: CC recipients
            bcc: BCC recipients
            account_id: Specific account to use (or default)
            
        Returns:
            True if sent successfully
        """
        attachments = []
        if attachment_paths:
            for path_str in attachment_paths:
                path = Path(path_str)
                if path.exists():
                    attachments.append(EmailAttachment(
                        filename=path.name,
                        content_type=self._guess_mime_type(path.name),
                        size=path.stat().st_size,
                        data=path.read_bytes(),
                    ))
                else:
                    logger.warning("attachment_not_found", path=path_str)

        account = None
        if account_id:
            account = await self._account_service.get_account(account_id) if self._account_service else None
        else:
            accounts = await self._get_email_accounts()
            account = next((a for a in accounts), None)

        if not account:
            logger.error("no_account_for_send")
            return False

        message = EmailMessage(
            subject=subject,
            recipients=to,
            body_text=body_text,
            body_html=body_html,
            cc=cc or [],
            bcc=bcc or [],
            attachments=attachments,
        )

        # Route to correct sender based on provider
        if account.provider == ProviderType.MSGRAPH.value:
            return await self._send_email_msgraph_with_attachments(message, account)
        elif account.provider == ProviderType.GOOGLE.value:
            return await self._send_email_gmail_with_attachments(message, account)
        else:
            # IMAP/SMTP
            return await self.send_email(message, account.id)

    def _guess_mime_type(self, filename: str) -> str:
        """Guess MIME type from filename."""
        ext = Path(filename).suffix.lower()
        mime_types = {
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".txt": "text/plain",
            ".zip": "application/zip",
        }
        return mime_types.get(ext, "application/octet-stream")

    async def _send_email_msgraph_with_attachments(
        self,
        message: EmailMessage,
        account,
    ) -> bool:
        """Send email with attachments via MS Graph."""
        try:
            credentials = self._account_service.decrypt_credentials(account)

            # Get token
            token_url = f"https://login.microsoftonline.com/{credentials['tenant_id']}/oauth2/v2.0/token"
            async with httpx.AsyncClient() as client:
                token_resp = await client.post(token_url, data={
                    "client_id": credentials["client_id"],
                    "client_secret": credentials["client_secret"],
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                })
                token_resp.raise_for_status()
                token = token_resp.json()["access_token"]

                # Build email with attachments
                email_data = {
                    "message": {
                        "subject": message.subject,
                        "body": {
                            "contentType": "HTML" if message.body_html else "Text",
                            "content": message.body_html or message.body_text,
                        },
                        "toRecipients": [
                            {"emailAddress": {"address": addr}}
                            for addr in message.recipients
                        ],
                    },
                    "saveToSentItems": True,
                }

                if message.cc:
                    email_data["message"]["ccRecipients"] = [
                        {"emailAddress": {"address": addr}}
                        for addr in message.cc
                    ]

                if message.attachments:
                    email_data["message"]["attachments"] = [
                        {
                            "@odata.type": "#microsoft.graph.fileAttachment",
                            "name": att.filename,
                            "contentType": att.content_type,
                            "contentBytes": base64.b64encode(att.data).decode(),
                        }
                        for att in message.attachments
                    ]

                resp = await client.post(
                    "https://graph.microsoft.com/v1.0/me/sendMail",
                    json=email_data,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                logger.info("msgraph_email_with_attachments_sent", subject=message.subject)
                return True

        except Exception as exc:
            logger.error("msgraph_send_with_attachments_failed", error=str(exc))
            return False

    async def _send_email_gmail_with_attachments(
        self,
        message: EmailMessage,
        account,
    ) -> bool:
        """Send email with attachments via Gmail API."""
        try:
            credentials = self._account_service.decrypt_credentials(account)

            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            def _send():
                creds = Credentials.from_authorized_user_file(credentials["credentials_file"])
                service = build("gmail", "v1", credentials=creds, cache_discovery=False)

                # Build MIME message
                mime_msg = email.mime.multipart.MIMEMultipart("mixed")
                mime_msg["Subject"] = message.subject
                mime_msg["To"] = ", ".join(message.recipients)
                if message.cc:
                    mime_msg["Cc"] = ", ".join(message.cc)

                # Body
                body_part = email.mime.multipart.MIMEMultipart("alternative")
                if message.body_text:
                    body_part.attach(email.mime.text.MIMEText(message.body_text, "plain"))
                if message.body_html:
                    body_part.attach(email.mime.text.MIMEText(message.body_html, "html"))
                mime_msg.attach(body_part)

                # Attachments
                for att in message.attachments:
                    part = email.mime.base.MIMEBase(*att.content_type.split("/", 1))
                    part.set_payload(att.data)
                    email.encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f'attachment; filename="{att.filename}"')
                    mime_msg.attach(part)

                # Encode and send
                raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
                service.users().messages().send(userId="me", body={"raw": raw}).execute()
                return True

            result = await asyncio.to_thread(_send)
            logger.info("gmail_email_with_attachments_sent", subject=message.subject)
            return result

        except Exception as exc:
            logger.error("gmail_send_with_attachments_failed", error=str(exc))
            return False
