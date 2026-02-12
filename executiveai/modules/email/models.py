"""Data models for the email management module."""

from __future__ import annotations

import datetime as dt
from enum import IntEnum, StrEnum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class EmailPriority(IntEnum):
    """Email priority levels."""

    URGENT = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BULK = 5


class EmailProvider(StrEnum):
    """Supported email backends."""

    IMAP_SMTP = "imap_smtp"
    GMAIL = "gmail"


class EmailAttachment(BaseModel):
    """Email attachment metadata."""

    filename: str
    content_type: str = "application/octet-stream"
    size: int = 0
    data: Optional[bytes] = None
    path: Optional[str] = None


class EmailMessage(BaseModel):
    """Unified email message model."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    provider: Optional[EmailProvider] = None
    provider_id: str = ""
    subject: str = ""
    sender: str = ""
    sender_name: str = ""
    recipients: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    body_text: str = ""
    body_html: str = ""
    attachments: list[EmailAttachment] = Field(default_factory=list)
    priority: EmailPriority = EmailPriority.NORMAL
    is_read: bool = False
    is_draft: bool = False
    folder: str = "INBOX"
    labels: list[str] = Field(default_factory=list)
    in_reply_to: str = ""
    references: str = ""
    date: dt.datetime = Field(default_factory=dt.datetime.utcnow)

    @property
    def has_attachments(self) -> bool:
        return len(self.attachments) > 0

    @property
    def summary(self) -> str:
        """Short summary for display."""
        return f"[{self.priority.name}] {self.sender_name or self.sender}: {self.subject}"


class EmailFilter(BaseModel):
    """Filter criteria for email queries."""

    folder: str = "INBOX"
    unread_only: bool = False
    since: Optional[dt.datetime] = None
    before: Optional[dt.datetime] = None
    sender: Optional[str] = None
    subject_contains: Optional[str] = None
    has_attachments: Optional[bool] = None
    limit: int = 50


class EmailTemplate(BaseModel):
    """Reusable email template."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    subject: str
    body_html: str = ""
    body_text: str = ""
    variables: list[str] = Field(default_factory=list)
