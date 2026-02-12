"""Tests for the email management module."""

from __future__ import annotations

import pytest

from executiveai.modules.email.models import (
    EmailAttachment,
    EmailFilter,
    EmailMessage,
    EmailPriority,
    EmailTemplate,
)


class TestEmailModels:
    """Tests for email data models."""

    def test_email_priority_ordering(self) -> None:
        """Priority values are ordered correctly."""
        assert EmailPriority.URGENT < EmailPriority.HIGH
        assert EmailPriority.HIGH < EmailPriority.NORMAL
        assert EmailPriority.NORMAL < EmailPriority.LOW
        assert EmailPriority.LOW < EmailPriority.BULK

    def test_email_message_defaults(self) -> None:
        """EmailMessage has sensible defaults."""
        msg = EmailMessage(subject="Test")
        assert msg.priority == EmailPriority.NORMAL
        assert msg.is_read is False
        assert msg.is_draft is False
        assert msg.folder == "INBOX"

    def test_email_has_attachments(self) -> None:
        """has_attachments property works correctly."""
        msg1 = EmailMessage(subject="No attachment")
        assert msg1.has_attachments is False

        msg2 = EmailMessage(
            subject="With attachment",
            attachments=[EmailAttachment(filename="report.pdf")],
        )
        assert msg2.has_attachments is True

    def test_email_summary(self) -> None:
        """Summary property formats correctly."""
        msg = EmailMessage(
            subject="Quarterly Report",
            sender="boss@company.com",
            sender_name="The Boss",
            priority=EmailPriority.HIGH,
        )
        summary = msg.summary
        assert "HIGH" in summary
        assert "The Boss" in summary
        assert "Quarterly Report" in summary

    def test_email_filter_defaults(self) -> None:
        """EmailFilter has proper defaults."""
        f = EmailFilter()
        assert f.folder == "INBOX"
        assert f.unread_only is False
        assert f.limit == 50

    def test_email_template(self) -> None:
        """EmailTemplate model holds template data."""
        tmpl = EmailTemplate(
            name="welcome",
            subject="Welcome {{ name }}!",
            body_text="Hello {{ name }}, welcome aboard!",
            variables=["name"],
        )
        assert tmpl.name == "welcome"
        assert "{{ name }}" in tmpl.subject


class TestEmailService:
    """Tests for the email service."""

    def test_prioritize_inbox_sorting(self) -> None:
        """Emails are sorted by priority heuristics."""
        from unittest.mock import MagicMock, patch

        with patch("executiveai.modules.email.service.get_settings") as mock:
            mock.return_value = MagicMock(
                imap_server="", imap_username="",
                smtp_server="", smtp_username="",
                google_credentials_file="nonexistent.json",
            )
            from executiveai.modules.email.service import EmailService
            service = EmailService()

            emails = [
                EmailMessage(subject="Weekly Newsletter", priority=EmailPriority.LOW),
                EmailMessage(subject="URGENT: Server Down!", priority=EmailPriority.NORMAL),
                EmailMessage(subject="Meeting Notes", priority=EmailPriority.NORMAL),
            ]

            import asyncio
            sorted_emails = asyncio.get_event_loop().run_until_complete(
                service.prioritize_inbox(emails)
            )
            assert "URGENT" in sorted_emails[0].subject

    def test_template_rendering(self) -> None:
        """Email templates are rendered with Jinja2."""
        from unittest.mock import MagicMock, patch

        with patch("executiveai.modules.email.service.get_settings") as mock:
            mock.return_value = MagicMock(
                imap_server="", imap_username="",
                smtp_server="", smtp_username="",
                google_credentials_file="nonexistent.json",
            )
            from executiveai.modules.email.service import EmailService
            service = EmailService()

            tmpl = EmailTemplate(
                name="hello",
                subject="Hi {{ name }}",
                body_text="Welcome, {{ name }}!",
            )
            service.register_template(tmpl)
            rendered = service.render_template("hello", {"name": "Ronald"})
            assert rendered.subject == "Hi Ronald"
            assert "Ronald" in rendered.body_text

    def test_template_not_found_raises(self) -> None:
        """Rendering a missing template raises ValueError."""
        from unittest.mock import MagicMock, patch

        with patch("executiveai.modules.email.service.get_settings") as mock:
            mock.return_value = MagicMock(
                imap_server="", imap_username="",
                smtp_server="", smtp_username="",
                google_credentials_file="nonexistent.json",
            )
            from executiveai.modules.email.service import EmailService
            service = EmailService()

            with pytest.raises(ValueError, match="Template not found"):
                service.render_template("nonexistent", {})
