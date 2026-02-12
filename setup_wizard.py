#!/usr/bin/env python3
"""Koda2 — Interactive configuration wizard for first-time setup."""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

# Ensure we can find the package even when run standalone
sys.path.insert(0, str(Path(__file__).parent))


def print_header(text: str) -> None:
    """Print a styled section header."""
    print(f"\n{'═' * 55}")
    print(f"  {text}")
    print(f"{'═' * 55}\n")


def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    """Ask the user for input with an optional default."""
    suffix = f" [{default}]" if default and not secret else ""
    try:
        if secret:
            import getpass
            value = getpass.getpass(f"  {prompt}{suffix}: ")
        else:
            value = input(f"  {prompt}{suffix}: ")
        return value.strip() or default
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(0)


def ask_bool(prompt: str, default: bool = False) -> bool:
    """Ask a yes/no question."""
    default_str = "Y/n" if default else "y/N"
    answer = ask(f"{prompt} [{default_str}]")
    if not answer:
        return default
    return answer.lower() in ("y", "yes", "1", "true")


def main() -> None:
    """Run the interactive setup wizard."""
    env_path = Path(".env")

    print_header("Koda2 — Setup Wizard")
    print("  This wizard will help you configure Koda2.")
    print("  Press Enter to keep defaults. Press Ctrl+C to cancel.\n")

    config: dict[str, str] = {}

    # Load existing .env
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip()

    # ── General ──────────────────────────────────────────────────
    print_header("General Settings")
    config["KODA2_ENV"] = ask("Environment", config.get("KODA2_ENV", "development"))
    config["KODA2_LOG_LEVEL"] = ask("Log level", config.get("KODA2_LOG_LEVEL", "INFO"))
    config["API_PORT"] = ask("API port", config.get("API_PORT", "8000"))

    # Generate keys if missing
    if not config.get("KODA2_SECRET_KEY") or config["KODA2_SECRET_KEY"] == "change-me":
        import secrets
        config["KODA2_SECRET_KEY"] = secrets.token_urlsafe(32)
        print("  Secret key: auto-generated ✓")

    if not config.get("KODA2_ENCRYPTION_KEY"):
        config["KODA2_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
        print("  Encryption key: auto-generated ✓")

    # ── LLM Providers ────────────────────────────────────────────
    print_header("LLM Providers (at least one required)")

    if ask_bool("Configure OpenAI?", bool(config.get("OPENAI_API_KEY"))):
        config["OPENAI_API_KEY"] = ask("OpenAI API key", config.get("OPENAI_API_KEY", ""), secret=True)

    if ask_bool("Configure Anthropic?", bool(config.get("ANTHROPIC_API_KEY"))):
        config["ANTHROPIC_API_KEY"] = ask("Anthropic API key", config.get("ANTHROPIC_API_KEY", ""), secret=True)

    if ask_bool("Configure Google AI?", bool(config.get("GOOGLE_AI_API_KEY"))):
        config["GOOGLE_AI_API_KEY"] = ask("Google AI API key", config.get("GOOGLE_AI_API_KEY", ""), secret=True)

    if ask_bool("Configure OpenRouter?", bool(config.get("OPENROUTER_API_KEY"))):
        config["OPENROUTER_API_KEY"] = ask("OpenRouter API key", config.get("OPENROUTER_API_KEY", ""), secret=True)

    # Set default provider
    providers_available = []
    if config.get("OPENAI_API_KEY"):
        providers_available.append("openai")
    if config.get("ANTHROPIC_API_KEY"):
        providers_available.append("anthropic")
    if config.get("GOOGLE_AI_API_KEY"):
        providers_available.append("google")
    if config.get("OPENROUTER_API_KEY"):
        providers_available.append("openrouter")

    if providers_available:
        default_provider = config.get("LLM_DEFAULT_PROVIDER", providers_available[0])
        config["LLM_DEFAULT_PROVIDER"] = ask(
            f"Default LLM provider ({', '.join(providers_available)})", default_provider
        )
    else:
        print("  ⚠ No LLM providers configured. At least one is required for full functionality.")

    # ── Telegram ─────────────────────────────────────────────────
    print_header("Telegram Bot (optional)")
    if ask_bool("Configure Telegram bot?", bool(config.get("TELEGRAM_BOT_TOKEN"))):
        config["TELEGRAM_BOT_TOKEN"] = ask("Bot token", config.get("TELEGRAM_BOT_TOKEN", ""), secret=True)
        config["TELEGRAM_ALLOWED_USER_IDS"] = ask(
            "Allowed user IDs (comma-separated)", config.get("TELEGRAM_ALLOWED_USER_IDS", "")
        )

    # ── Email ────────────────────────────────────────────────────
    print_header("Email (optional)")
    if ask_bool("Configure IMAP/SMTP email?", bool(config.get("IMAP_SERVER"))):
        config["IMAP_SERVER"] = ask("IMAP server", config.get("IMAP_SERVER", ""))
        config["IMAP_PORT"] = ask("IMAP port", config.get("IMAP_PORT", "993"))
        config["IMAP_USERNAME"] = ask("IMAP username", config.get("IMAP_USERNAME", ""))
        config["IMAP_PASSWORD"] = ask("IMAP password", "", secret=True)
        config["SMTP_SERVER"] = ask("SMTP server", config.get("SMTP_SERVER", ""))
        config["SMTP_PORT"] = ask("SMTP port", config.get("SMTP_PORT", "587"))
        config["SMTP_USERNAME"] = ask("SMTP username", config.get("SMTP_USERNAME", config.get("IMAP_USERNAME", "")))
        config["SMTP_PASSWORD"] = ask("SMTP password", "", secret=True)

    # ── Calendar ─────────────────────────────────────────────────
    print_header("Calendar Integrations (optional)")

    if ask_bool("Configure Exchange (EWS)?", bool(config.get("EWS_SERVER"))):
        config["EWS_SERVER"] = ask("EWS server", config.get("EWS_SERVER", ""))
        config["EWS_USERNAME"] = ask("EWS username", config.get("EWS_USERNAME", ""))
        config["EWS_PASSWORD"] = ask("EWS password", "", secret=True)
        config["EWS_EMAIL"] = ask("EWS email", config.get("EWS_EMAIL", ""))

    if ask_bool("Configure Office 365 (MS Graph)?", bool(config.get("MSGRAPH_CLIENT_ID"))):
        config["MSGRAPH_CLIENT_ID"] = ask("Client ID", config.get("MSGRAPH_CLIENT_ID", ""))
        config["MSGRAPH_CLIENT_SECRET"] = ask("Client secret", "", secret=True)
        config["MSGRAPH_TENANT_ID"] = ask("Tenant ID", config.get("MSGRAPH_TENANT_ID", ""))

    if ask_bool("Configure CalDAV?", bool(config.get("CALDAV_URL"))):
        config["CALDAV_URL"] = ask("CalDAV URL", config.get("CALDAV_URL", ""))
        config["CALDAV_USERNAME"] = ask("CalDAV username", config.get("CALDAV_USERNAME", ""))
        config["CALDAV_PASSWORD"] = ask("CalDAV password", "", secret=True)

    # ── Write .env ───────────────────────────────────────────────
    print_header("Saving Configuration")

    lines = []
    # Read template for structure
    template_path = Path(".env.example")
    if template_path.exists():
        for line in template_path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(line)
            elif "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                value = config.get(key, "")
                lines.append(f"{key}={value}")
            else:
                lines.append(line)
    else:
        for key, value in config.items():
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")
    print(f"  Configuration saved to {env_path}")

    # ── Initialize database ──────────────────────────────────────
    print("\n  Initializing database...")
    try:
        import asyncio
        from koda2.database import init_db
        asyncio.run(init_db())
        print("  Database initialized ✓")
    except Exception as e:
        print(f"  Database init skipped: {e}")

    # ── Summary ──────────────────────────────────────────────────
    print_header("Setup Complete!")
    print("  Start Koda2:")
    print("    source .venv/bin/activate")
    print("    koda2")
    print("")
    print("  Or with Docker:")
    print("    docker compose up -d")
    print("")
    print("  API docs: http://localhost:" + config.get("API_PORT", "8000") + "/docs")
    print("")


if __name__ == "__main__":
    main()
