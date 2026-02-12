"""Account management module for Koda2.

This module provides multi-account support per provider type,
with encrypted credential storage and validation.
"""

from koda2.modules.account.models import (
    Account,
    AccountType,
    CalDAVCredentials,
    EWSCredentials,
    GoogleCredentials,
    IMAPCredentials,
    MSGraphCredentials,
    ProviderType,
    SMTPCredentials,
    TelegramCredentials,
    get_credential_schema,
    validate_credentials,
)
from koda2.modules.account.service import AccountService

__all__ = [
    # Models
    "Account",
    "AccountType",
    "ProviderType",
    # Credential schemas
    "EWSCredentials",
    "GoogleCredentials",
    "MSGraphCredentials",
    "CalDAVCredentials",
    "IMAPCredentials",
    "SMTPCredentials",
    "TelegramCredentials",
    # Utilities
    "get_credential_schema",
    "validate_credentials",
    # Service
    "AccountService",
]
