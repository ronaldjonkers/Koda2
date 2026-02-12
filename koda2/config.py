"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings sourced from .env / environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── General ──────────────────────────────────────────────────────
    koda2_env: str = "development"
    koda2_log_level: str = "INFO"
    koda2_secret_key: str = "change-me"
    koda2_encryption_key: str = ""

    # ── API Server ───────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # ── Database ─────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///data/koda2.db"
    chroma_persist_dir: str = "data/chroma"
    redis_url: str = "redis://localhost:6379/0"

    # ── LLM Providers ───────────────────────────────────────────────
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_ai_api_key: str = ""
    openrouter_api_key: str = ""
    llm_default_provider: str = "openai"
    llm_default_model: str = "gpt-4o"

    # ── Exchange (EWS) ───────────────────────────────────────────────
    ews_server: str = ""
    ews_username: str = ""
    ews_password: str = ""
    ews_email: str = ""

    # ── Google Workspace ─────────────────────────────────────────────
    google_credentials_file: str = "config/google_credentials.json"
    google_token_file: str = "config/google_token.json"

    # ── Microsoft Graph ──────────────────────────────────────────────
    msgraph_client_id: str = ""
    msgraph_client_secret: str = ""
    msgraph_tenant_id: str = ""

    # ── CalDAV ───────────────────────────────────────────────────────
    caldav_url: str = ""
    caldav_username: str = ""
    caldav_password: str = ""

    # ── Email (IMAP / SMTP) ──────────────────────────────────────────
    imap_server: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True

    smtp_server: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    # ── Messaging ────────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: str = ""

    whatsapp_enabled: bool = False
    whatsapp_bridge_port: int = 3001

    # ── Image Generation ─────────────────────────────────────────────
    image_provider: str = "openai"
    stability_api_key: str = ""

    # ── Derived ──────────────────────────────────────────────────────
    @property
    def data_dir(self) -> Path:
        """Return the data directory, creating it if needed."""
        path = Path("data")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def logs_dir(self) -> Path:
        """Return the logs directory, creating it if needed."""
        path = Path("logs")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def allowed_telegram_ids(self) -> list[int]:
        """Parse comma-separated Telegram user IDs."""
        if not self.telegram_allowed_user_ids:
            return []
        return [int(uid.strip()) for uid in self.telegram_allowed_user_ids.split(",") if uid.strip()]

    def has_provider(self, provider: str) -> bool:
        """Check if a given LLM provider has credentials configured."""
        key_map = {
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "google": self.google_ai_api_key,
            "openrouter": self.openrouter_api_key,
        }
        return bool(key_map.get(provider, ""))


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
