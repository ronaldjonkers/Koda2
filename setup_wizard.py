#!/usr/bin/env python3
"""Koda2 — Interactive configuration wizard with credential validation."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure we can find the package even when run standalone
sys.path.insert(0, str(Path(__file__).parent))


def print_header(text: str) -> None:
    """Print a styled section header."""
    print(f"\n{'═' * 60}")
    print(f"  {text}")
    print(f"{'═' * 60}\n")


def ask(prompt: str, default: str = "", secret: bool = False, required: bool = False) -> str:
    """Ask the user for input with an optional default."""
    suffix = f" [{default}]" if default and not secret else ""
    req_mark = " *" if required else ""
    try:
        if secret:
            import getpass
            value = getpass.getpass(f"  {prompt}{req_mark}{suffix}: ")
        else:
            value = input(f"  {prompt}{req_mark}{suffix}: ")
        value = value.strip()
        if required and not value and not default:
            print("  ⚠ This field is required.")
            return ask(prompt, default, secret, required)
        return value or default
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


def print_success(msg: str) -> None:
    """Print a success message."""
    print(f"  ✓ {msg}")


def print_error(msg: str) -> None:
    """Print an error message."""
    print(f"  ✗ {msg}")


def print_warning(msg: str) -> None:
    """Print a warning message."""
    print(f"  ⚠ {msg}")


def print_info(msg: str) -> None:
    """Print an info message."""
    print(f"  ℹ {msg}")


async def validate_and_retry(
    validator_func,
    *args,
    prompt_name: str = "value",
    **kwargs
) -> tuple[bool, Optional[dict]]:
    """Validate credentials and retry if they fail.
    
    Returns:
        Tuple of (success, credentials_dict or None)
    """
    max_retries = 3
    for attempt in range(max_retries):
        success, error = await validator_func(*args, **kwargs)
        if success:
            return True, None
        
        print_error(f"{prompt_name} validation failed: {error}")
        if attempt < max_retries - 1:
            print_info("Please try again...")
        else:
            print_error(f"Failed after {max_retries} attempts.")
            if ask_bool("Continue anyway? (not recommended)", default=False):
                return True, None
            return False, None
    return False, None


class AccountSetupWizard:
    """Wizard for setting up multiple accounts with validation."""
    
    def __init__(self) -> None:
        self.account_service = None
        self.settings = None
        
    async def init(self) -> bool:
        """Initialize the wizard."""
        try:
            from koda2.modules.account.service import AccountService
            from koda2.config import get_settings
            self.account_service = AccountService()
            self.settings = get_settings()
            return True
        except Exception as e:
            print_error(f"Failed to initialize: {e}")
            return False
    
    async def setup_llm_provider(self, name: str, env_key: str, validator) -> bool:
        """Set up an LLM provider with validation."""
        print_header(f"🤖 {name}")
        
        api_key = ask(f"{name} API key", secret=True)
        if not api_key:
            print_info(f"Skipping {name}")
            return False
        
        # Validate
        print(f"  Validating {name} API key...")
        success, error = await validator(api_key)
        if not success:
            print_error(f"Invalid API key: {error}")
            if not ask_bool("Continue anyway?"):
                return await self.setup_llm_provider(name, env_key, validator)
        else:
            print_success(f"{name} API key is valid!")
        
        # Store in .env
        self._update_env({env_key: api_key})
        return True
    
    async def setup_telegram_account(self) -> Optional[dict]:
        """Set up a Telegram bot account."""
        print_header("💬 Telegram Bot")
        print("  Get a bot token from @BotFather on Telegram")
        
        name = ask("Account name (e.g., 'My Bot', 'Work Notifications')", "Telegram Bot", required=True)
        bot_token = ask("Bot token", secret=True, required=True)
        
        if not bot_token:
            return None
        
        # Validate
        print("  Validating bot token...")
        from koda2.modules.account.validators import validate_telegram_credentials
        success, error = await validate_telegram_credentials(bot_token)
        
        if not success:
            print_error(f"Invalid token: {error}")
            if ask_bool("Try again?"):
                return await self.setup_telegram_account()
            return None
        
        print_success("Bot token is valid!")
        
        allowed_ids = ask("Allowed user IDs (comma-separated, optional)")
        allowed_ids_list = [int(x.strip()) for x in allowed_ids.split(",") if x.strip().isdigit()]
        
        # Create account
        from koda2.modules.account.models import AccountType, ProviderType
        account = await self.account_service.create_account(
            name=name,
            account_type=AccountType.MESSAGING,
            provider=ProviderType.TELEGRAM,
            credentials={
                "bot_token": bot_token,
                "allowed_user_ids": allowed_ids_list,
            },
            is_default=True,
        )
        print_success(f"Telegram account '{name}' created!")
        print_info(f"Find your user ID at: https://t.me/userinfobot")
        return {"id": account.id, "name": name}
    
    async def setup_whatsapp_account(self) -> Optional[dict]:
        """Set up WhatsApp."""
        print_header("💬 WhatsApp")
        print("  WhatsApp connects via QR code scan (like WhatsApp Web).")
        print()
        
        import shutil
        has_node = shutil.which("node") is not None
        
        if not has_node:
            print_warning("Node.js not found - WhatsApp requires Node.js 18+")
            print_info("Install from: https://nodejs.org/")
            if not ask_bool("Continue anyway?"):
                return None
        else:
            print_success("Node.js found")
        
        if not ask_bool("Enable WhatsApp?"):
            return None
        
        # Store in .env for WhatsApp bridge
        self._update_env({
            "WHATSAPP_ENABLED": "true",
            "WHATSAPP_BRIDGE_PORT": ask("Bridge port", "3001"),
        })
        
        print_success("WhatsApp enabled")
        print_info("After starting Koda2, scan QR at: http://localhost:8000/api/whatsapp/qr")
        return {"enabled": True}
    
    async def setup_exchange_account(self) -> Optional[dict]:
        """Set up an Exchange (EWS) account with validation."""
        print_header("📧 Microsoft Exchange (On-Premises)")
        print("  Connects to your company's Exchange server via EWS.")
        print()
        print("  Required from your IT department:")
        print("  • EWS Server URL (e.g., https://mail.company.com/EWS/Exchange.asmx)")
        print("  • Username (often DOMAIN\\username)")
        print("  • Password")
        print("  • Email address")
        print()
        
        name = ask("Account name (e.g., 'Work Exchange', 'Company Email')", "Exchange", required=True)
        server = ask("EWS Server URL", "https://mail.company.com/EWS/Exchange.asmx", required=True)
        username = ask("Username (e.g., DOMAIN\\user)", required=True)
        password = ask("Password", secret=True, required=True)
        email = ask("Email address", required=True)
        
        # Validate
        print("  Testing Exchange connection...")
        from koda2.modules.account.validators import validate_ews_credentials
        
        success, error = await validate_ews_credentials(server, username, password, email)
        if not success:
            print_error(f"Connection failed: {error}")
            if ask_bool("Try different credentials?"):
                return await self.setup_exchange_account()
            return None
        
        print_success("Exchange connection successful!")
        
        # Ask account type
        print()
        print("  What will you use this account for?")
        is_calendar = ask_bool("Calendar?", True)
        is_email = ask_bool("Email?", True)
        
        created = []
        from koda2.modules.account.models import AccountType, ProviderType
        
        if is_calendar:
            account = await self.account_service.create_account(
                name=f"{name} (Calendar)",
                account_type=AccountType.CALENDAR,
                provider=ProviderType.EWS,
                credentials={"server": server, "username": username, "password": password, "email": email},
                is_default=True,
            )
            created.append(("Calendar", account.id))
        
        if is_email:
            account = await self.account_service.create_account(
                name=f"{name} (Email)",
                account_type=AccountType.EMAIL,
                provider=ProviderType.EWS,
                credentials={"server": server, "username": username, "password": password, "email": email},
                is_default=True,
            )
            created.append(("Email", account.id))
        
        for acc_type, acc_id in created:
            print_success(f"Exchange {acc_type} account '{name}' created!")
        
        return {"name": name, "created": created}
    
    async def setup_office365_account(self) -> Optional[dict]:
        """Set up an Office 365 (MS Graph) account with validation."""
        print_header("📧 Office 365 / Microsoft 365")
        print("  Connects to Microsoft's cloud services.")
        print()
        print("  Required:")
        print("  • Client ID (Application ID)")
        print("  • Client Secret")
        print("  • Tenant ID")
        print()
        print("  To get these:")
        print("  1. Go to https://portal.azure.com/")
        print("  2. Azure Active Directory → App registrations")
        print("  3. New registration")
        print("  4. Add permissions: Calendars.ReadWrite, Mail.ReadWrite")
        print("  5. Create client secret")
        print()
        
        name = ask("Account name (e.g., 'Office 365', 'Microsoft Work')", "Office 365", required=True)
        client_id = ask("Client ID", required=True)
        client_secret = ask("Client Secret", secret=True, required=True)
        tenant_id = ask("Tenant ID (or 'common' for personal)", "common", required=True)
        
        # Validate
        print("  Testing Microsoft Graph connection...")
        from koda2.modules.account.validators import validate_msgraph_credentials
        
        success, error = await validate_msgraph_credentials(client_id, client_secret, tenant_id)
        if not success:
            print_error(f"Connection failed: {error}")
            if ask_bool("Try different credentials?"):
                return await self.setup_office365_account()
            return None
        
        print_success("Microsoft Graph connection successful!")
        
        # Ask account type
        print()
        print("  What will you use this account for?")
        is_calendar = ask_bool("Calendar?", True)
        is_email = ask_bool("Email?", True)
        
        created = []
        from koda2.modules.account.models import AccountType, ProviderType
        
        if is_calendar:
            account = await self.account_service.create_account(
                name=f"{name} (Calendar)",
                account_type=AccountType.CALENDAR,
                provider=ProviderType.MSGRAPH,
                credentials={"client_id": client_id, "client_secret": client_secret, "tenant_id": tenant_id},
                is_default=True,
            )
            created.append(("Calendar", account.id))
        
        if is_email:
            account = await self.account_service.create_account(
                name=f"{name} (Email)",
                account_type=AccountType.EMAIL,
                provider=ProviderType.MSGRAPH,
                credentials={"client_id": client_id, "client_secret": client_secret, "tenant_id": tenant_id},
                is_default=True,
            )
            created.append(("Email", account.id))
        
        for acc_type, acc_id in created:
            print_success(f"Office 365 {acc_type} account '{name}' created!")
        
        return {"name": name, "created": created}
    
    async def setup_google_account(self) -> Optional[dict]:
        """Set up a Google account (Calendar + Gmail)."""
        print_header("📧 Google (Calendar + Gmail)")
        print("  Connects to Google Calendar and Gmail via OAuth2.")
        print()
        print("  Setup steps:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create/select a project")
        print("  3. Enable Google Calendar API and Gmail API")
        print("  4. Credentials → Create → OAuth client ID → Desktop app")
        print("  5. Download JSON credentials file")
        print()
        
        config_dir = Path("config")
        config_dir.mkdir(exist_ok=True)
        creds_path = config_dir / "google_credentials.json"
        token_path = config_dir / "google_token.json"
        
        if creds_path.exists():
            print_success(f"Found credentials file: {creds_path}")
        else:
            print_warning(f"Credentials file not found at {creds_path}")
            print_info("Please download and place the file, then continue")
            input("\n  Press Enter when ready...")
            if not creds_path.exists():
                print_error("Still not found. Skipping Google setup.")
                return None
        
        name = ask("Account name (e.g., 'Personal Gmail', 'Work Google')", "Google", required=True)
        
        # Validate credentials file
        print("  Validating Google credentials...")
        from koda2.modules.account.validators import validate_google_credentials
        
        success, error = await validate_google_credentials(str(creds_path), str(token_path))
        if not success:
            print_error(f"Invalid credentials: {error}")
            return None
        
        print_success("Google credentials are valid!")
        
        # Ask account type
        print()
        print("  What will you use this account for?")
        is_calendar = ask_bool("Calendar?", True)
        is_email = ask_bool("Email (Gmail)?", True)
        
        created = []
        from koda2.modules.account.models import AccountType, ProviderType
        
        if is_calendar:
            account = await self.account_service.create_account(
                name=f"{name} (Calendar)",
                account_type=AccountType.CALENDAR,
                provider=ProviderType.GOOGLE,
                credentials={"credentials_file": str(creds_path), "token_file": str(token_path)},
                is_default=True,
            )
            created.append(("Calendar", account.id))
        
        if is_email:
            account = await self.account_service.create_account(
                name=f"{name} (Email)",
                account_type=AccountType.EMAIL,
                provider=ProviderType.GOOGLE,
                credentials={"credentials_file": str(creds_path), "token_file": str(token_path)},
                is_default=True,
            )
            created.append(("Email", account.id))
        
        for acc_type, acc_id in created:
            print_success(f"Google {acc_type} account '{name}' created!")
        
        print_info("Note: First use will open a browser for OAuth authorization")
        
        return {"name": name, "created": created}
    
    async def setup_caldav_account(self) -> Optional[dict]:
        """Set up a CalDAV account with validation."""
        print_header("📅 CalDAV (Apple Calendar, Nextcloud, etc.)")
        print("  Connects to CalDAV-compatible calendar servers.")
        print()
        
        name = ask("Account name (e.g., 'Nextcloud', 'iCloud')", "CalDAV", required=True)
        url = ask("CalDAV URL", "https://", required=True)
        username = ask("Username", required=True)
        password = ask("Password", secret=True, required=True)
        
        # Validate
        print("  Testing CalDAV connection...")
        from koda2.modules.account.validators import validate_caldav_credentials
        
        success, error = await validate_caldav_credentials(url, username, password)
        if not success:
            print_error(f"Connection failed: {error}")
            if ask_bool("Try different credentials?"):
                return await self.setup_caldav_account()
            return None
        
        print_success("CalDAV connection successful!")
        
        from koda2.modules.account.models import AccountType, ProviderType
        account = await self.account_service.create_account(
            name=name,
            account_type=AccountType.CALENDAR,
            provider=ProviderType.CALDAV,
            credentials={"url": url, "username": username, "password": password},
            is_default=True,
        )
        
        print_success(f"CalDAV account '{name}' created!")
        return {"id": account.id, "name": name}
    
    async def setup_imap_account(self) -> Optional[dict]:
        """Set up an IMAP/SMTP email account with validation."""
        print_header("📧 IMAP/SMTP Email")
        print("  Generic email setup for any provider supporting IMAP.")
        print()
        
        name = ask("Account name (e.g., 'Personal Email', 'Work Mail')", "IMAP Email", required=True)
        
        # IMAP
        print("  IMAP Settings (incoming mail):")
        imap_server = ask("IMAP server", "imap.gmail.com", required=True)
        imap_port = int(ask("IMAP port", "993"))
        imap_username = ask("IMAP username", required=True)
        imap_password = ask("IMAP password", secret=True, required=True)
        imap_ssl = ask_bool("Use SSL?", True)
        
        # Validate IMAP
        print("  Testing IMAP connection...")
        from koda2.modules.account.validators import validate_imap_credentials
        
        success, error = await validate_imap_credentials(
            imap_server, imap_port, imap_username, imap_password, imap_ssl
        )
        if not success:
            print_error(f"IMAP connection failed: {error}")
            if ask_bool("Try different settings?"):
                return await self.setup_imap_account()
            return None
        
        print_success("IMAP connection successful!")
        
        # SMTP
        print()
        print("  SMTP Settings (outgoing mail):")
        smtp_server = ask("SMTP server", imap_server.replace("imap", "smtp"), required=True)
        smtp_port = int(ask("SMTP port", "587"))
        smtp_username = ask("SMTP username", imap_username, required=True)
        smtp_password = ask("SMTP password", secret=True, required=True)
        smtp_tls = ask_bool("Use TLS?", True)
        
        # Validate SMTP
        print("  Testing SMTP connection...")
        from koda2.modules.account.validators import validate_smtp_credentials
        
        success, error = await validate_smtp_credentials(
            smtp_server, smtp_port, smtp_username, smtp_password, smtp_tls
        )
        if not success:
            print_error(f"SMTP connection failed: {error}")
            print_warning("Continuing with IMAP only. You can add SMTP later.")
            smtp_config = None
        else:
            print_success("SMTP connection successful!")
            smtp_config = {
                "server": smtp_server,
                "port": smtp_port,
                "username": smtp_username,
                "password": smtp_password,
                "use_tls": smtp_tls,
            }
        
        from koda2.modules.account.models import AccountType, ProviderType
        
        # Create IMAP account
        imap_account = await self.account_service.create_account(
            name=f"{name} (IMAP)",
            account_type=AccountType.EMAIL,
            provider=ProviderType.IMAP,
            credentials={
                "server": imap_server,
                "port": imap_port,
                "username": imap_username,
                "password": imap_password,
                "use_ssl": imap_ssl,
            },
            is_default=True,
        )
        
        created = [("IMAP", imap_account.id)]
        
        # Create SMTP account if configured
        if smtp_config:
            smtp_account = await self.account_service.create_account(
                name=f"{name} (SMTP)",
                account_type=AccountType.EMAIL,
                provider=ProviderType.SMTP,
                credentials=smtp_config,
                is_default=True,
            )
            created.append(("SMTP", smtp_account.id))
        
        for acc_type, acc_id in created:
            print_success(f"Email {acc_type} account '{name}' created!")
        
        return {"name": name, "created": created}
    
    def _update_env(self, updates: dict[str, str]) -> None:
        """Update environment variables in .env file."""
        env_path = Path(".env")
        config = {}
        
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    config[key.strip()] = value.strip()
        
        config.update(updates)
        
        # Write back
        lines = []
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
            for key, value in sorted(config.items()):
                lines.append(f"{key}={value}")
        
        env_path.write_text("\n".join(lines) + "\n")


async def list_existing_accounts(wizard: AccountSetupWizard) -> None:
    """List all existing accounts."""
    from koda2.modules.account.models import AccountType
    
    print_header("📋 Existing Accounts")
    
    for acc_type in AccountType:
        accounts = await wizard.account_service.get_accounts(account_type=acc_type)
        if accounts:
            print(f"\n  {acc_type.value.upper()}:")
            for acc in accounts:
                status = "✓" if acc.is_active else "✗"
                default = " [default]" if acc.is_default else ""
                print(f"    {status} {acc.name} ({acc.provider}){default}")
    
    input("\n  Press Enter to continue...")


async def delete_account_menu(wizard: AccountSetupWizard) -> None:
    """Menu for deleting accounts."""
    from koda2.modules.account.models import AccountType
    
    print_header("🗑️  Delete Account")
    
    accounts = await wizard.account_service.get_accounts(active_only=False)
    if not accounts:
        print_warning("No accounts found.")
        input("\n  Press Enter to continue...")
        return
    
    print("  Select account to delete:")
    for i, acc in enumerate(accounts, 1):
        status = "✓" if acc.is_active else "✗"
        print(f"    {i}. {status} {acc.name} ({acc.account_type}/{acc.provider})")
    
    choice = ask("Account number (or 0 to cancel)", "0")
    try:
        idx = int(choice) - 1
        if idx < 0:
            return
        account = accounts[idx]
    except (ValueError, IndexError):
        print_error("Invalid selection")
        return
    
    if ask_bool(f"Delete '{account.name}'? This cannot be undone.", False):
        await wizard.account_service.delete_account(account.id)
        print_success(f"Account '{account.name}' deleted")
    
    input("\n  Press Enter to continue...")


async def set_default_account_menu(wizard: AccountSetupWizard) -> None:
    """Menu for setting default accounts."""
    from koda2.modules.account.models import AccountType
    
    print_header("⭐ Set Default Account")
    
    # Show account types
    print("  Select account type:")
    types = list(AccountType)
    for i, t in enumerate(types, 1):
        print(f"    {i}. {t.value}")
    
    choice = ask("Type number", "1")
    try:
        acc_type = types[int(choice) - 1]
    except (ValueError, IndexError):
        print_error("Invalid selection")
        return
    
    accounts = await wizard.account_service.get_accounts(account_type=acc_type)
    if not accounts:
        print_warning(f"No {acc_type.value} accounts found.")
        input("\n  Press Enter to continue...")
        return
    
    print(f"\n  Select default {acc_type.value} account:")
    for i, acc in enumerate(accounts, 1):
        current = " ⭐" if acc.is_default else ""
        print(f"    {i}. {acc.name} ({acc.provider}){current}")
    
    choice = ask("Account number", "1")
    try:
        account = accounts[int(choice) - 1]
    except (ValueError, IndexError):
        print_error("Invalid selection")
        return
    
    await wizard.account_service.set_default(account.id)
    print_success(f"'{account.name}' is now the default {acc_type.value} account")
    input("\n  Press Enter to continue...")


async def account_management_menu(wizard: AccountSetupWizard) -> bool:
    """Account management menu. Returns True if user wants to exit."""
    print_header("⚙️  Account Management")
    print("  1. List existing accounts")
    print("  2. Add new account")
    print("  3. Delete account")
    print("  4. Set default account")
    print("  5. Back to main menu")
    print()
    
    choice = ask("Select option", "1")
    
    if choice == "1":
        await list_existing_accounts(wizard)
    elif choice == "2":
        await add_account_submenu(wizard)
    elif choice == "3":
        await delete_account_menu(wizard)
    elif choice == "4":
        await set_default_account_menu(wizard)
    elif choice == "5":
        return True
    
    return False


async def add_account_submenu(wizard: AccountSetupWizard) -> None:
    """Submenu for adding different account types."""
    print_header("➕ Add New Account")
    print("  1. Telegram Bot")
    print("  2. WhatsApp")
    print("  3. Microsoft Exchange (EWS)")
    print("  4. Office 365 (Microsoft Graph)")
    print("  5. Google (Calendar + Gmail)")
    print("  6. CalDAV (Apple, Nextcloud)")
    print("  7. IMAP/SMTP Email")
    print("  8. Cancel")
    print()
    
    choice = ask("Select option", "8")
    
    if choice == "1":
        await wizard.setup_telegram_account()
    elif choice == "2":
        await wizard.setup_whatsapp_account()
    elif choice == "3":
        await wizard.setup_exchange_account()
    elif choice == "4":
        await wizard.setup_office365_account()
    elif choice == "5":
        await wizard.setup_google_account()
    elif choice == "6":
        await wizard.setup_caldav_account()
    elif choice == "7":
        await wizard.setup_imap_account()
    
    if choice in "1234567":
        input("\n  Press Enter to continue...")


async def setup_general_settings(wizard: AccountSetupWizard, is_first_run: bool) -> None:
    """Set up general application settings."""
    env_path = Path(".env")
    config = {}
    
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip()
    
    # Personalization (ask first on first run)
    if is_first_run:
        print_header("👋 Let's personalize your assistant")
        print("  Give your AI assistant a name and tell it who you are.")
        print()
    else:
        print_header("👋 Personalization")
    
    config["ASSISTANT_NAME"] = ask("What should your AI assistant be called?", config.get("ASSISTANT_NAME", "Koda2"), required=True)
    config["USER_NAME"] = ask("What is your name?", config.get("USER_NAME", ""), required=True)
    
    assistant = config["ASSISTANT_NAME"]
    user = config["USER_NAME"]
    print_success(f"{assistant} will address you as {user}")
    
    # General settings
    print_header("⚙️  General Settings")
    config["KODA2_ENV"] = ask("Environment", config.get("KODA2_ENV", "production"))
    config["KODA2_LOG_LEVEL"] = ask("Log level", config.get("KODA2_LOG_LEVEL", "INFO"))
    config["API_PORT"] = ask("API port", config.get("API_PORT", "8000"))
    
    # Generate keys if missing
    if not config.get("KODA2_SECRET_KEY") or config["KODA2_SECRET_KEY"] == "change-me":
        import secrets
        config["KODA2_SECRET_KEY"] = secrets.token_urlsafe(32)
        print_success("Secret key auto-generated")
    
    if not config.get("KODA2_ENCRYPTION_KEY"):
        config["KODA2_ENCRYPTION_KEY"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
        print_success("Encryption key auto-generated")
    
    # LLM Providers
    print_header("🤖 LLM Providers")
    print("  At least one LLM provider is required for AI functionality.")
    print()
    
    from koda2.modules.account.validators import validate_openai_credentials
    
    providers_configured = []
    
    if ask_bool("Configure OpenAI?", bool(config.get("OPENAI_API_KEY"))):
        api_key = ask("OpenAI API key", config.get("OPENAI_API_KEY", ""), secret=True)
        if api_key:
            print("  Validating...")
            success, error = await validate_openai_credentials(api_key)
            if success:
                print_success("API key is valid!")
                config["OPENAI_API_KEY"] = api_key
                providers_configured.append("openai")
            else:
                print_error(f"Invalid key: {error}")
                if ask_bool("Save anyway?"):
                    config["OPENAI_API_KEY"] = api_key
    
    if ask_bool("Configure Anthropic (Claude)?", bool(config.get("ANTHROPIC_API_KEY"))):
        config["ANTHROPIC_API_KEY"] = ask("Anthropic API key", config.get("ANTHROPIC_API_KEY", ""), secret=True)
        if config["ANTHROPIC_API_KEY"]:
            providers_configured.append("anthropic")
    
    if ask_bool("Configure Google AI (Gemini)?", bool(config.get("GOOGLE_AI_API_KEY"))):
        config["GOOGLE_AI_API_KEY"] = ask("Google AI API key", config.get("GOOGLE_AI_API_KEY", ""), secret=True)
        if config["GOOGLE_AI_API_KEY"]:
            providers_configured.append("google")
    
    if ask_bool("Configure OpenRouter?", bool(config.get("OPENROUTER_API_KEY"))):
        config["OPENROUTER_API_KEY"] = ask("OpenRouter API key", config.get("OPENROUTER_API_KEY", ""), secret=True)
        if config["OPENROUTER_API_KEY"]:
            providers_configured.append("openrouter")
            
            # Ask for model (fetching from API can be unreliable)
            print("\n  Common OpenRouter models:")
            print("    - openai/gpt-4o")
            print("    - anthropic/claude-3.5-sonnet")
            print("    - anthropic/claude-3-opus")
            print("    - google/gemini-pro")
            print("    - meta-llama/llama-3.1-70b-instruct")
            print()
            config["OPENROUTER_MODEL"] = ask("OpenRouter model", config.get("OPENROUTER_MODEL", "openai/gpt-4o"))
    
    # Set default provider
    if providers_configured:
        default = config.get("LLM_DEFAULT_PROVIDER", providers_configured[0])
        config["LLM_DEFAULT_PROVIDER"] = ask("Default LLM provider", default)
        config["LLM_DEFAULT_MODEL"] = ask("Default model", config.get("LLM_DEFAULT_MODEL", "gpt-4o"))
    else:
        print_warning("No LLM providers configured! AI features will be limited.")
    
    # Travel & Expenses (optional)
    print_header("✈️  Travel & Expenses (Optional)")
    
    if ask_bool("Configure Amadeus (Flight search)?", bool(config.get("AMADEUS_API_KEY"))):
        config["AMADEUS_API_KEY"] = ask("API Key", config.get("AMADEUS_API_KEY", ""))
        config["AMADEUS_API_SECRET"] = ask("API Secret", config.get("AMADEUS_API_SECRET", ""), secret=True)
        config["AMADEUS_TEST_MODE"] = "true" if ask_bool("Test mode?", True) else "false"
    
    if ask_bool("Configure RapidAPI (Booking.com)?", bool(config.get("RAPIDAPI_KEY"))):
        config["RAPIDAPI_KEY"] = ask("RapidAPI Key", config.get("RAPIDAPI_KEY", ""))
    
    # Save to .env
    wizard._update_env(config)
    print_success("Settings saved to .env")


async def main_async() -> None:
    """Main async entry point."""
    env_path = Path(".env")
    is_first_run = not env_path.exists()
    
    if is_first_run:
        print_header("🚀 Welcome to Koda2!")
        print("  This wizard will help you configure your AI assistant.")
        print("  You'll be able to add multiple accounts for each service.")
    else:
        print_header("⚙️  Koda2 Configuration")
        print("  Manage your accounts and settings.")
    
    # Initialize wizard
    wizard = AccountSetupWizard()
    if not await wizard.init():
        print_error("Failed to initialize wizard. Is the database configured?")
        sys.exit(1)
    
    # Initialize database
    print("  Initializing database...")
    try:
        from koda2.database import init_db
        await init_db()
        print_success("Database ready")
    except Exception as e:
        print_error(f"Database initialization failed: {e}")
        sys.exit(1)
    
    # First run: general settings first
    if is_first_run:
        await setup_general_settings(wizard, is_first_run)
    
    # Main menu loop
    while True:
        print_header("📋 Main Menu")
        print("  1. Manage Accounts (add/delete/list)")
        print("  2. General Settings")
        print("  3. Done")
        print()
        
        if is_first_run:
            choice = ask("Select option", "1")
        else:
            choice = ask("Select option", "3")
        
        if choice == "1":
            exit_menu = False
            while not exit_menu:
                exit_menu = await account_management_menu(wizard)
        elif choice == "2":
            await setup_general_settings(wizard, is_first_run)
        elif choice == "3":
            break
    
    # Summary
    print_header("🎉 Configuration Complete!")
    
    # Show configured accounts
    from koda2.modules.account.models import AccountType
    
    print("\n  Configured Accounts:")
    has_accounts = False
    for acc_type in AccountType:
        accounts = await wizard.account_service.get_accounts(account_type=acc_type)
        if accounts:
            has_accounts = True
            print(f"\n    {acc_type.value.upper()}:")
            for acc in accounts:
                default = " ⭐" if acc.is_default else ""
                print(f"      • {acc.name} ({acc.provider}){default}")
    
    if not has_accounts:
        print_warning("No accounts configured yet. Run setup again to add accounts.")
    
    print()
    print("  Start Koda2:")
    print("    koda2")
    print()
    print(f"  Dashboard: http://localhost:{wizard.settings.api_port}/dashboard")
    print(f"  API Docs:  http://localhost:{wizard.settings.api_port}/docs")
    print()
    print("  To reconfigure:")
    print("    koda2 --setup")
    print()


def main() -> None:
    """Run the interactive setup wizard."""
    asyncio.run(main_async())


def check_and_run_setup() -> bool:
    """Check if setup is needed and run if so."""
    env_path = Path(".env")
    if not env_path.exists():
        print("""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║  🤖 Welcome to Koda2!                                        ║
║                                                              ║
║  It looks like this is your first time running Koda2.        ║
║  Let's get you set up!                                       ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")
        response = input("  Start setup wizard now? [Y/n]: ").strip().lower()
        if response in ("", "y", "yes"):
            main()
            return True
    return False


if __name__ == "__main__":
    main()
