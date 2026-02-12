"""Module 3 — Email Management."""

from koda2.modules.email.service import EmailService
from koda2.modules.email.models import EmailMessage, EmailPriority

__all__ = ["EmailService", "EmailMessage", "EmailPriority"]
