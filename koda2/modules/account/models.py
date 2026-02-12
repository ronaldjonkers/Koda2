"""Database models and Pydantic schemas for account management."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import Boolean, Column, DateTime, Index, String, Text
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON

from koda2.database import Base


class AccountType(StrEnum):
    """Supported account types."""

    CALENDAR = "calendar"
    EMAIL = "email"
    MESSAGING = "messaging"


class ProviderType(StrEnum):
    """Supported provider backends."""

    EWS = "ews"
    GOOGLE = "google"
    MSGRAPH = "msgraph"
    CALDAV = "caldav"
    IMAP = "imap"
    SMTP = "smtp"
    TELEGRAM = "telegram"


class Account(Base):
    """SQLAlchemy model for storing account configurations."""

    __tablename__ = "accounts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(256), nullable=False)
    account_type = Column(String(32), nullable=False, index=True)
    provider = Column(String(32), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    credentials = Column(Text, nullable=False)  # Encrypted JSON string
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_accounts_type_provider_active", "account_type", "provider", "is_active"),
        Index("ix_accounts_type_provider_default", "account_type", "provider", "is_default"),
    )

    def __repr__(self) -> str:
        return (
            f"<Account(id={self.id}, name={self.name}, "
            f"type={self.account_type}, provider={self.provider}, "
            f"is_default={self.is_default}, is_active={self.is_active})>"
        )


# =============================================================================
# Pydantic Models for Type-Safe Credentials
# =============================================================================


class EWSCredentials(BaseModel):
    """Credentials for Exchange Web Services (EWS)."""

    server: str = Field(..., description="Exchange server URL")
    username: str = Field(..., description="Username for authentication")
    password: str = Field(..., description="Password for authentication")
    email: str = Field(..., description="Email address associated with the account")


class GoogleCredentials(BaseModel):
    """Credentials for Google APIs (OAuth2)."""

    credentials_file: str = Field(..., description="Path to OAuth2 credentials JSON file")
    token_file: str = Field(..., description="Path to stored token file")


class MSGraphCredentials(BaseModel):
    """Credentials for Microsoft Graph API."""

    client_id: str = Field(..., description="Azure AD application client ID")
    client_secret: str = Field(..., description="Azure AD application client secret")
    tenant_id: str = Field(..., description="Azure AD tenant ID")


class CalDAVCredentials(BaseModel):
    """Credentials for CalDAV servers."""

    url: str = Field(..., description="CalDAV server URL")
    username: str = Field(..., description="Username for authentication")
    password: str = Field(..., description="Password for authentication")


class IMAPCredentials(BaseModel):
    """Credentials for IMAP email servers."""

    server: str = Field(..., description="IMAP server hostname")
    port: int = Field(default=993, description="IMAP server port")
    username: str = Field(..., description="Username for authentication")
    password: str = Field(..., description="Password for authentication")
    use_ssl: bool = Field(default=True, description="Whether to use SSL/TLS connection")


class SMTPCredentials(BaseModel):
    """Credentials for SMTP email servers."""

    server: str = Field(..., description="SMTP server hostname")
    port: int = Field(default=587, description="SMTP server port")
    username: str = Field(..., description="Username for authentication")
    password: str = Field(..., description="Password for authentication")
    use_tls: bool = Field(default=True, description="Whether to use STARTTLS")


class TelegramCredentials(BaseModel):
    """Credentials for Telegram Bot API."""

    bot_token: str = Field(..., description="Telegram bot token from @BotFather")
    allowed_user_ids: list[int] = Field(
        default_factory=list,
        description="List of allowed Telegram user IDs",
    )


# Union type for all credential types
AccountCredentials = (
    EWSCredentials
    | GoogleCredentials
    | MSGraphCredentials
    | CalDAVCredentials
    | IMAPCredentials
    | SMTPCredentials
    | TelegramCredentials
)


# Mapping of provider types to their credential schemas
CREDENTIAL_SCHEMAS: dict[ProviderType, type[BaseModel]] = {
    ProviderType.EWS: EWSCredentials,
    ProviderType.GOOGLE: GoogleCredentials,
    ProviderType.MSGRAPH: MSGraphCredentials,
    ProviderType.CALDAV: CalDAVCredentials,
    ProviderType.IMAP: IMAPCredentials,
    ProviderType.SMTP: SMTPCredentials,
    ProviderType.TELEGRAM: TelegramCredentials,
}


def get_credential_schema(provider: ProviderType) -> type[BaseModel]:
    """Get the Pydantic credential schema for a provider type.
    
    Args:
        provider: The provider type.
        
    Returns:
        The Pydantic model class for the provider's credentials.
        
    Raises:
        ValueError: If the provider type is not supported.
    """
    if provider not in CREDENTIAL_SCHEMAS:
        raise ValueError(f"Unsupported provider type: {provider}")
    return CREDENTIAL_SCHEMAS[provider]


def validate_credentials(provider: ProviderType, credentials: dict) -> BaseModel:
    """Validate credentials against the provider's schema.
    
    Args:
        provider: The provider type.
        credentials: The credentials dictionary to validate.
        
    Returns:
        Validated Pydantic model instance.
        
    Raises:
        ValueError: If validation fails.
    """
    schema = get_credential_schema(provider)
    try:
        return schema(**credentials)
    except Exception as exc:
        raise ValueError(f"Invalid credentials for {provider}: {exc}") from exc
