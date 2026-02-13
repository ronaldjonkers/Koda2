"""Command parser for messaging platforms (Telegram, WhatsApp).

Provides unified command handling across all messaging platforms.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

CommandHandler = Callable[..., Coroutine[Any, Any, str]]


@dataclass
class WizardState:
    """Tracks multi-step wizard conversation state per user."""
    wizard_type: str  # e.g. 'add_exchange', 'add_imap'
    step: int = 0
    data: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > 300  # 5 min timeout


@dataclass
class ParsedCommand:
    """Result of parsing a command from a message."""
    
    is_command: bool
    command: str = ""
    args: str = ""
    raw: str = ""
    platform: str = ""  # "telegram", "whatsapp", "api"


class CommandParser:
    """Parse and route commands from messaging platforms."""
    
    # Command patterns for different platforms
    COMMAND_PATTERNS = {
        "telegram": re.compile(r"^/([a-zA-Z_][a-zA-Z0-9_]*)(?:@\w+)?(?:\s+(.*))?$", re.DOTALL),
        "whatsapp": re.compile(r"^/(\w+)(?:\s+(.*))?$", re.DOTALL),
        "api": re.compile(r"^/(\w+)(?:\s+(.*))?$", re.DOTALL),
    }
    
    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}
        self._help_texts: dict[str, str] = {}
        self._wizards: dict[str, WizardState] = {}  # user_id -> active wizard
        self._wizard_handlers: dict[str, Callable] = {}  # wizard_type -> handler

    def register_wizard(self, wizard_type: str, handler: Callable) -> None:
        """Register a wizard step handler."""
        self._wizard_handlers[wizard_type] = handler

    def start_wizard(self, user_id: str, wizard_type: str, data: dict | None = None) -> None:
        """Start a multi-step wizard for a user."""
        self._wizards[user_id] = WizardState(wizard_type=wizard_type, data=data or {})

    def cancel_wizard(self, user_id: str) -> None:
        """Cancel an active wizard."""
        self._wizards.pop(user_id, None)

    def has_active_wizard(self, user_id: str) -> bool:
        """Check if user has an active (non-expired) wizard."""
        ws = self._wizards.get(user_id)
        if ws and ws.expired:
            self._wizards.pop(user_id, None)
            return False
        return ws is not None

    async def handle_wizard_input(self, user_id: str, text: str, **kwargs) -> tuple[bool, str]:
        """Process input for an active wizard. Returns (handled, response)."""
        ws = self._wizards.get(user_id)
        if not ws or ws.expired:
            self._wizards.pop(user_id, None)
            return False, ""

        # Allow cancellation
        if text.strip().lower() in ("/cancel", "cancel", "stop", "annuleer"):
            self._wizards.pop(user_id, None)
            return True, "Wizard cancelled."

        handler = self._wizard_handlers.get(ws.wizard_type)
        if not handler:
            self._wizards.pop(user_id, None)
            return False, ""

        response = await handler(user_id=user_id, text=text, state=ws, parser=self, **kwargs)
        return True, response
    
    def register(
        self, 
        command: str, 
        handler: CommandHandler,
        help_text: str = "",
    ) -> None:
        """Register a command handler.
        
        Args:
            command: Command name without leading slash
            handler: Async function to handle the command
            help_text: Description for help command
        """
        cmd = command.lstrip("/").lower()
        self._handlers[cmd] = handler
        if help_text:
            self._help_texts[cmd] = help_text
    
    def parse(self, message: str, platform: str = "api") -> ParsedCommand:
        """Parse a message to extract command and arguments.
        
        Args:
            message: The raw message text
            platform: Platform type (telegram, whatsapp, api)
            
        Returns:
            ParsedCommand with extracted components
        """
        message = message.strip()
        if not message:
            return ParsedCommand(is_command=False, raw=message, platform=platform)
        
        pattern = self.COMMAND_PATTERNS.get(platform, self.COMMAND_PATTERNS["api"])
        match = pattern.match(message)
        
        if match:
            return ParsedCommand(
                is_command=True,
                command=match.group(1).lower(),
                args=match.group(2) or "",
                raw=message,
                platform=platform,
            )
        
        return ParsedCommand(is_command=False, raw=message, platform=platform)
    
    async def execute(
        self, 
        parsed: ParsedCommand, 
        user_id: str,
        **kwargs: Any,
    ) -> tuple[bool, str]:
        """Execute a parsed command if a handler exists.
        
        Returns:
            Tuple of (was_command, response)
        """
        if not parsed.is_command:
            return False, ""
        
        handler = self._handlers.get(parsed.command)
        if not handler:
            available = ", ".join(f"/{cmd}" for cmd in sorted(self._handlers.keys()))
            return True, f"Unknown command: /{parsed.command}\n\nAvailable commands: {available}"
        
        try:
            # Remove keys we pass explicitly to avoid duplicates from **kwargs
            clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("user_id", "args", "command", "platform", "parser")}
            response = await handler(
                user_id=user_id,
                args=parsed.args,
                command=parsed.command,
                platform=parsed.platform,
                parser=self,
                **clean_kwargs,
            )
            return True, response
        except Exception as exc:
            return True, f"Error executing /{parsed.command}: {exc}"
    
    def get_help(self, command: Optional[str] = None) -> str:
        """Generate help text for commands."""
        if command:
            cmd = command.lstrip("/").lower()
            if cmd in self._help_texts:
                return f"/{cmd}: {self._help_texts[cmd]}"
            elif cmd in self._handlers:
                return f"/{cmd}: No description available"
            return f"Unknown command: /{cmd}"
        
        lines = ["*Available Commands:*"]
        for cmd in sorted(self._handlers.keys()):
            desc = self._help_texts.get(cmd, "No description")
            lines.append(f"  /{cmd} - {desc}")
        return "\n".join(lines)
    
    def list_commands(self) -> list[str]:
        """List all registered commands."""
        return list(self._handlers.keys())


# ── Common Command Handlers ─────────────────────────────────────────

class CommonCommands:
    """Standard commands available on all platforms."""
    
    def __init__(self, orchestrator: Any) -> None:
        self._orch = orchestrator
    
    async def handle_status(self, user_id: str, **kwargs: Any) -> str:
        """Show system status."""
        providers = await self._orch.calendar.active_providers()
        plugins = self._orch.self_improve.list_plugins()
        tasks = self._orch.scheduler.list_tasks()
        imap = await self._orch.email.imap_configured()
        smtp = await self._orch.email.smtp_configured()
        
        return (
            f"*Koda2 Status*\n"
            f"Version: {self._orch.__dict__.get('_version', 'unknown')}\n"
            f"Calendar providers: {', '.join(str(p) for p in providers) or 'none'}\n"
            f"Email: {'IMAP ✓' if imap else 'IMAP ✗'} / "
            f"{'SMTP ✓' if smtp else 'SMTP ✗'}\n"
            f"LLM providers: {', '.join(str(p) for p in self._orch.llm.available_providers) or 'none'}\n"
            f"Plugins loaded: {len(plugins)}\n"
            f"Scheduled tasks: {len(tasks)}"
        )
    
    async def handle_help(self, user_id: str, **kwargs: Any) -> str:
        """Show help information."""
        return (
            "*Koda2 — AI Executive Assistant*\n\n"
            "*Commands:*\n"
            "/help — This help overview\n"
            "/status — System status\n"
            "/calendar [today/week] — View upcoming events\n"
            "/schedule <details> — Create a calendar event\n"
            "/meet [title] — Create a Google Meet link\n"
            "/email <request> — Check inbox or send email\n"
            "/remind <what> at <when> — Set a reminder\n"
            "/contacts [name] — Search contacts\n"
            "/accounts — Manage accounts (list/add/test/delete)\n"
            "/config — View settings\n\n"
            "*Or just send a message:*\n"
            "• \"Schedule a meeting with John tomorrow at 2pm\"\n"
            "• \"Send an email to Ronald about the report\"\n"
            "• \"What's on my calendar this week?\"\n"
            "• \"Create a Meet link and send it to Jan via WhatsApp\""
        )
    
    async def handle_schedule(self, user_id: str, args: str = "", **kwargs: Any) -> str:
        """Handle schedule command."""
        if not args:
            return "Usage: /schedule <meeting details>\nExample: /schedule Meeting with John tomorrow at 2pm"
        
        result = await self._orch.process_message(user_id, f"Schedule: {args}", channel=kwargs.get("platform", "api"))
        return result.get("response", "Scheduled successfully")
    
    async def handle_email(self, user_id: str, args: str = "", **kwargs: Any) -> str:
        """Handle email command."""
        if not args:
            return "Usage: /email <request>\nExamples:\n/email check my inbox\n/email send to john@example.com: Hello"
        
        result = await self._orch.process_message(user_id, f"Email: {args}", channel=kwargs.get("platform", "api"))
        return result.get("response", "Email processed")
    
    async def handle_remind(self, user_id: str, args: str = "", **kwargs: Any) -> str:
        """Handle remind command."""
        if not args:
            return "Usage: /remind <what> at <when>\nExample: /remind Call dentist at 4pm today"
        
        result = await self._orch.process_message(user_id, f"Remind me: {args}", channel=kwargs.get("platform", "api"))
        return result.get("response", "Reminder set")
    
    async def handle_calendar(self, user_id: str, args: str = "", **kwargs: Any) -> str:
        """Handle calendar command."""
        if not args:
            args = "today"
        
        result = await self._orch.process_message(user_id, f"What's on my calendar {args}?", channel=kwargs.get("platform", "api"))
        return result.get("response", "Calendar checked")
    
    async def handle_config(self, user_id: str, args: str = "", **kwargs: Any) -> str:
        """Handle configuration commands."""
        if not args:
            return (
                "Configuration commands:\n"
                "/config show - Show current settings\n"
                "/config set <key> <value> - Set a configuration value"
            )
        
        parts = args.split(maxsplit=1)
        subcmd = parts[0].lower()
        
        if subcmd == "show":
            # Show non-sensitive config
            return (
                f"*Configuration*\n"
                f"Environment: {self._orch._settings.koda2_env}\n"
                f"Log level: {self._orch._settings.koda2_log_level}\n"
                f"Default LLM: {self._orch._settings.llm_default_provider}\n"
                f"Calendar providers: {len(await self._orch.calendar.active_providers())}\n"
                f"Git auto-commit: {'enabled' if self._orch._settings.git_auto_commit else 'disabled'}"
            )
        elif subcmd == "set" and len(parts) > 1:
            return "⚠️ Settings can only be changed via the .env file or setup wizard for security."
        
        return "Unknown config command. Use /config for help."
    
    async def handle_commands(self, user_id: str, **kwargs: Any) -> str:
        """List all available commands."""
        return await self.handle_help(user_id, **kwargs)

    async def handle_meet(self, user_id: str, args: str = "", **kwargs: Any) -> str:
        """Create a Google Meet link."""
        title = args.strip() or "Koda2 Meeting"
        try:
            from pathlib import Path
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            import datetime as _dt

            token_path = Path("config/google_token.json")
            if not token_path.exists():
                return "Google is not connected. Set up Google OAuth via the dashboard first."

            SCOPES = ["https://www.googleapis.com/auth/calendar"]
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    token_path.write_text(creds.to_json())
                else:
                    return "Google token expired. Re-authenticate via the dashboard."

            service = build("calendar", "v3", credentials=creds)
            now = _dt.datetime.now(_dt.UTC)
            event_body = {
                "summary": title,
                "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": (now + _dt.timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"koda2-meet-{now.strftime('%Y%m%d%H%M%S')}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
            }
            result = service.events().insert(
                calendarId="primary", body=event_body, conferenceDataVersion=1,
            ).execute()

            meet_url = result.get("hangoutLink", "")
            event_id = result.get("id", "")

            # Delete placeholder event — we only need the link
            if event_id:
                try:
                    service.events().delete(calendarId="primary", eventId=event_id).execute()
                except Exception:
                    pass

            if meet_url:
                return f"*Google Meet Link:*\n{meet_url}\n\nTitle: {title}"
            return "Could not generate a Meet link. Try again."
        except Exception as exc:
            return f"Error creating Meet link: {exc}"

    async def handle_contacts(self, user_id: str, args: str = "", **kwargs: Any) -> str:
        """Search or list contacts."""
        query = args.strip()
        contacts = await self._orch.contacts.search(query, limit=10)

        if not contacts:
            if query:
                return f"No contacts found for '{query}'."
            return "No contacts synced yet. Contacts sync from macOS Contacts, WhatsApp, and email accounts."

        lines = [f"*Contacts{' — ' + query if query else ''}:*\n"]
        for c in contacts:
            phone = c.get_primary_phone() or ""
            email = c.get_primary_email() or ""
            sources = ", ".join(s.value for s in c.sources)
            detail_parts = []
            if phone:
                detail_parts.append(phone)
            if email:
                detail_parts.append(email)
            if c.company:
                detail_parts.append(c.company)
            detail = " · ".join(detail_parts)
            wa = " 💬" if c.has_whatsapp() else ""
            lines.append(f"• *{c.name}*{wa}\n  {detail}\n  _{sources}_")

        return "\n".join(lines)
    
    async def handle_accounts(self, user_id: str, args: str = "", **kwargs: Any) -> str:
        """Handle account management commands."""
        from koda2.modules.account.service import AccountService
        from koda2.modules.account.models import AccountType, ProviderType
        
        service = AccountService()
        parts = args.split(maxsplit=1)
        subcmd = parts[0].lower() if parts else "list"
        
        if subcmd == "list" or subcmd == "":
            accounts = await service.get_accounts()
            if not accounts:
                return (
                    "*No accounts configured.*\n\n"
                    "Use /accounts add to add an account."
                )
            
            lines = ["*Configured Accounts:*\n"]
            for acc_type in AccountType:
                type_accounts = [a for a in accounts if a.account_type == acc_type.value]
                if type_accounts:
                    lines.append(f"\n*{acc_type.value.upper()}:*")
                    for acc in type_accounts:
                        status = "✓" if acc.is_active else "✗"
                        default = " ⭐" if acc.is_default else ""
                        lines.append(f"  {status} {acc.name} ({acc.provider}){default}")
            
            return "\n".join(lines)
        
        elif subcmd == "add":
            # Check for provider type argument
            add_arg = parts[1].strip().lower() if len(parts) > 1 else ""
            parser = kwargs.get("parser")
            
            wizard_map = {
                "exchange": ("add_exchange", "Exchange (EWS)"),
                "ews": ("add_exchange", "Exchange (EWS)"),
                "office365": ("add_office365", "Office 365"),
                "o365": ("add_office365", "Office 365"),
                "msgraph": ("add_office365", "Office 365"),
                "imap": ("add_imap", "IMAP/SMTP Email"),
                "email": ("add_imap", "IMAP/SMTP Email"),
                "caldav": ("add_caldav", "CalDAV"),
                "telegram": ("add_telegram", "Telegram Bot"),
            }
            
            if add_arg in wizard_map and parser:
                wiz_type, wiz_name = wizard_map[add_arg]
                parser.start_wizard(user_id, wiz_type)
                return f"*Setting up {wiz_name}*\n\nStep 1: What name do you want for this account?\n(e.g. 'Work Exchange', 'Personal Email')\n\n_Send /cancel to abort_"
            
            return (
                "*Add Account*\n\n"
                "Choose a provider:\n"
                "/accounts add exchange\n"
                "/accounts add office365\n"
                "/accounts add imap\n"
                "/accounts add caldav\n"
                "/accounts add telegram\n\n"
                "Google: Use the web dashboard for OAuth:\n"
                "http://localhost:8000/dashboard → Accounts"
            )
        
        elif subcmd == "default":
            if len(parts) < 2:
                # Show current defaults
                lines = ["*Default Accounts:*\n"]
                for acc_type in AccountType:
                    default = await service.get_default_account(acc_type)
                    if default:
                        lines.append(f"  {acc_type.value}: {default.name} ({default.provider})")
                    else:
                        lines.append(f"  {acc_type.value}: [none]")
                return "\n".join(lines)
            
            # Set default by account name/ID
            account_name = parts[1]
            all_accounts = await service.get_accounts()
            
            # Find by ID (prefix) or name
            account = None
            for acc in all_accounts:
                if acc.id.startswith(account_name) or acc.name.lower() == account_name.lower():
                    account = acc
                    break
            
            if not account:
                return f"Account not found: {account_name}\nUse /accounts list to see available accounts."
            
            await service.set_default(account.id)
            return f"✓ '{account.name}' is now the default {account.account_type} account."
        
        elif subcmd == "enable":
            if len(parts) < 2:
                return "Usage: /accounts enable <account_name_or_id>"
            
            account_name = parts[1]
            all_accounts = await service.get_accounts(active_only=False)
            
            account = None
            for acc in all_accounts:
                if acc.id.startswith(account_name) or acc.name.lower() == account_name.lower():
                    account = acc
                    break
            
            if not account:
                return f"Account not found: {account_name}"
            
            await service.update_account(account.id, is_active=True)
            return f"✓ Account '{account.name}' enabled."
        
        elif subcmd == "disable":
            if len(parts) < 2:
                return "Usage: /accounts disable <account_name_or_id>"
            
            account_name = parts[1]
            all_accounts = await service.get_accounts(active_only=False)
            
            account = None
            for acc in all_accounts:
                if acc.id.startswith(account_name) or acc.name.lower() == account_name.lower():
                    account = acc
                    break
            
            if not account:
                return f"Account not found: {account_name}"
            
            await service.update_account(account.id, is_active=False)
            return f"✓ Account '{account.name}' disabled."
        
        elif subcmd == "test":
            if len(parts) < 2:
                return "Usage: /accounts test <account_name_or_id>"
            
            account_name = parts[1]
            all_accounts = await service.get_accounts(active_only=False)
            
            account = None
            for acc in all_accounts:
                if acc.id.startswith(account_name) or acc.name.lower() == account_name.lower():
                    account = acc
                    break
            
            if not account:
                return f"Account not found: {account_name}"
            
            # Test credentials
            credentials = service.decrypt_credentials(account)
            success, message = await service.validate_account_credentials(
                AccountType(account.account_type),
                ProviderType(account.provider),
                credentials,
            )
            
            if success:
                return f"✓ Account '{account.name}' credentials are valid!"
            else:
                return f"✗ Account '{account.name}' validation failed: {message}"
        
        elif subcmd == "delete":
            if len(parts) < 2:
                return "Usage: /accounts delete <account_name_or_id>"
            
            account_name = parts[1]
            all_accounts = await service.get_accounts(active_only=False)
            
            account = None
            for acc in all_accounts:
                if acc.id.startswith(account_name) or acc.name.lower() == account_name.lower():
                    account = acc
                    break
            
            if not account:
                return f"Account not found: {account_name}"
            
            await service.delete_account(account.id)
            return f"✓ Account '{account.name}' deleted."
        
        elif subcmd == "help":
            return (
                "*Account Management Commands:*\n\n"
                "/accounts list - Show all accounts\n"
                "/accounts add - Add a new account (step-by-step)\n"
                "/accounts add exchange - Add Exchange account\n"
                "/accounts add office365 - Add Office 365 account\n"
                "/accounts add imap - Add IMAP email account\n"
                "/accounts add caldav - Add CalDAV calendar\n"
                "/accounts add telegram - Add Telegram bot\n"
                "/accounts default [name] - Show or set default\n"
                "/accounts enable <name> - Enable an account\n"
                "/accounts disable <name> - Disable an account\n"
                "/accounts test <name> - Test credentials\n"
                "/accounts delete <name> - Delete an account"
            )
        
        else:
            return f"Unknown subcommand: {subcmd}\nUse /accounts help for available commands."


# ── Wizard Step Handlers ─────────────────────────────────────────────


async def _wizard_add_exchange(user_id: str, text: str, state: WizardState, parser: CommandParser, **kw) -> str:
    """Step-by-step Exchange (EWS) account setup."""
    text = text.strip()
    step = state.step

    if step == 0:  # Got name
        state.data["name"] = text
        state.step = 1
        return "Step 2: Exchange server hostname?\n(e.g. exchange.company.com)"

    if step == 1:  # Got server
        state.data["server"] = text.replace("https://", "").replace("http://", "").strip("/")
        state.step = 2
        return "Step 3: Username?\n(e.g. DOMAIN\\username or just username)"

    if step == 2:  # Got username
        state.data["username"] = text
        state.step = 3
        return "Step 4: Password?"

    if step == 3:  # Got password
        state.data["password"] = text
        state.step = 4
        return "Step 5: Email address?\n(e.g. user@company.com)"

    if step == 4:  # Got email — validate and create
        state.data["email"] = text
        parser.cancel_wizard(user_id)

        # Validate
        from koda2.modules.account.validators import validate_ews_credentials
        success, error = await validate_ews_credentials(
            state.data["server"], state.data["username"],
            state.data["password"], state.data["email"],
        )
        if not success:
            return (
                f"❌ Connection failed: {error}\n\n"
                f"Use /accounts add exchange to try again."
            )

        # Create calendar + email accounts
        from koda2.modules.account.service import AccountService
        from koda2.modules.account.models import AccountType, ProviderType
        svc = AccountService()
        creds = {
            "server": state.data["server"],
            "username": state.data["username"],
            "password": state.data["password"],
            "email": state.data["email"],
        }
        cal = await svc.create_account(
            name=f"{state.data['name']} (Calendar)",
            account_type=AccountType.CALENDAR,
            provider=ProviderType.EWS,
            credentials=creds, is_default=True,
        )
        mail = await svc.create_account(
            name=f"{state.data['name']} (Email)",
            account_type=AccountType.EMAIL,
            provider=ProviderType.EWS,
            credentials=creds, is_default=True,
        )
        return (
            f"✅ *Exchange account '{state.data['name']}' created!*\n\n"
            f"• Calendar: {cal.name}\n"
            f"• Email: {mail.name}\n\n"
            f"Events and emails will appear on the next sync."
        )

    parser.cancel_wizard(user_id)
    return "Unexpected step. Use /accounts add exchange to start over."


async def _wizard_add_office365(user_id: str, text: str, state: WizardState, parser: CommandParser, **kw) -> str:
    """Step-by-step Office 365 (MS Graph) account setup."""
    text = text.strip()
    step = state.step

    if step == 0:
        state.data["name"] = text
        state.step = 1
        return (
            "Step 2: Client ID (Application ID)?\n\n"
            "_Get this from Azure Portal → App registrations_"
        )
    if step == 1:
        state.data["client_id"] = text
        state.step = 2
        return "Step 3: Client Secret?"
    if step == 2:
        state.data["client_secret"] = text
        state.step = 3
        return "Step 4: Tenant ID?\n(or 'common' for personal accounts)"
    if step == 3:
        state.data["tenant_id"] = text
        parser.cancel_wizard(user_id)

        from koda2.modules.account.validators import validate_msgraph_credentials
        success, error = await validate_msgraph_credentials(
            state.data["client_id"], state.data["client_secret"], state.data["tenant_id"],
        )
        if not success:
            return f"❌ Connection failed: {error}\n\nUse /accounts add office365 to try again."

        from koda2.modules.account.service import AccountService
        from koda2.modules.account.models import AccountType, ProviderType
        svc = AccountService()
        creds = {
            "client_id": state.data["client_id"],
            "client_secret": state.data["client_secret"],
            "tenant_id": state.data["tenant_id"],
        }
        cal = await svc.create_account(
            name=f"{state.data['name']} (Calendar)",
            account_type=AccountType.CALENDAR,
            provider=ProviderType.MSGRAPH,
            credentials=creds, is_default=True,
        )
        mail = await svc.create_account(
            name=f"{state.data['name']} (Email)",
            account_type=AccountType.EMAIL,
            provider=ProviderType.MSGRAPH,
            credentials=creds, is_default=True,
        )
        return (
            f"✅ *Office 365 account '{state.data['name']}' created!*\n\n"
            f"• Calendar: {cal.name}\n• Email: {mail.name}"
        )

    parser.cancel_wizard(user_id)
    return "Unexpected step. Use /accounts add office365 to start over."


async def _wizard_add_imap(user_id: str, text: str, state: WizardState, parser: CommandParser, **kw) -> str:
    """Step-by-step IMAP/SMTP email account setup."""
    text = text.strip()
    step = state.step

    if step == 0:
        state.data["name"] = text
        state.step = 1
        return "Step 2: IMAP server?\n(e.g. imap.gmail.com)"
    if step == 1:
        state.data["imap_server"] = text
        state.step = 2
        return "Step 3: IMAP port?\n(usually 993 for SSL)"
    if step == 2:
        try:
            state.data["imap_port"] = int(text)
        except ValueError:
            return "Please enter a valid port number (e.g. 993)."
        state.step = 3
        return "Step 4: Username/email?"
    if step == 3:
        state.data["username"] = text
        state.step = 4
        return "Step 5: Password?"
    if step == 4:
        state.data["password"] = text
        parser.cancel_wizard(user_id)

        from koda2.modules.account.validators import validate_imap_credentials
        success, error = await validate_imap_credentials(
            state.data["imap_server"], state.data["imap_port"],
            state.data["username"], state.data["password"], True,
        )
        if not success:
            return f"❌ IMAP connection failed: {error}\n\nUse /accounts add imap to try again."

        from koda2.modules.account.service import AccountService
        from koda2.modules.account.models import AccountType, ProviderType
        svc = AccountService()
        account = await svc.create_account(
            name=f"{state.data['name']} (IMAP)",
            account_type=AccountType.EMAIL,
            provider=ProviderType.IMAP,
            credentials={
                "server": state.data["imap_server"],
                "port": state.data["imap_port"],
                "username": state.data["username"],
                "password": state.data["password"],
                "use_ssl": True,
            },
            is_default=True,
        )
        return f"✅ *IMAP account '{state.data['name']}' created!*\n\n• {account.name}"

    parser.cancel_wizard(user_id)
    return "Unexpected step. Use /accounts add imap to start over."


async def _wizard_add_caldav(user_id: str, text: str, state: WizardState, parser: CommandParser, **kw) -> str:
    """Step-by-step CalDAV account setup."""
    text = text.strip()
    step = state.step

    if step == 0:
        state.data["name"] = text
        state.step = 1
        return "Step 2: CalDAV URL?\n(e.g. https://nextcloud.example.com/remote.php/dav)"
    if step == 1:
        state.data["url"] = text
        state.step = 2
        return "Step 3: Username?"
    if step == 2:
        state.data["username"] = text
        state.step = 3
        return "Step 4: Password?"
    if step == 3:
        state.data["password"] = text
        parser.cancel_wizard(user_id)

        from koda2.modules.account.validators import validate_caldav_credentials
        success, error = await validate_caldav_credentials(
            state.data["url"], state.data["username"], state.data["password"],
        )
        if not success:
            return f"❌ CalDAV connection failed: {error}\n\nUse /accounts add caldav to try again."

        from koda2.modules.account.service import AccountService
        from koda2.modules.account.models import AccountType, ProviderType
        svc = AccountService()
        account = await svc.create_account(
            name=state.data["name"],
            account_type=AccountType.CALENDAR,
            provider=ProviderType.CALDAV,
            credentials={
                "url": state.data["url"],
                "username": state.data["username"],
                "password": state.data["password"],
            },
            is_default=True,
        )
        return f"✅ *CalDAV account '{state.data['name']}' created!*\n\n• {account.name}"

    parser.cancel_wizard(user_id)
    return "Unexpected step. Use /accounts add caldav to start over."


async def _wizard_add_telegram(user_id: str, text: str, state: WizardState, parser: CommandParser, **kw) -> str:
    """Step-by-step Telegram bot setup."""
    text = text.strip()
    step = state.step

    if step == 0:
        state.data["name"] = text
        state.step = 1
        return "Step 2: Bot token?\n(Get it from @BotFather on Telegram)"
    if step == 1:
        state.data["bot_token"] = text
        parser.cancel_wizard(user_id)

        from koda2.modules.account.validators import validate_telegram_credentials
        success, error = await validate_telegram_credentials(state.data["bot_token"])
        if not success:
            return f"❌ Invalid bot token: {error}\n\nUse /accounts add telegram to try again."

        from koda2.modules.account.service import AccountService
        from koda2.modules.account.models import AccountType, ProviderType
        svc = AccountService()
        account = await svc.create_account(
            name=state.data["name"],
            account_type=AccountType.MESSAGING,
            provider=ProviderType.TELEGRAM,
            credentials={"bot_token": state.data["bot_token"], "allowed_user_ids": []},
            is_default=True,
        )
        return f"✅ *Telegram bot '{state.data['name']}' created!*\n\n• {account.name}\n\nRestart Koda2 to activate the bot."

    parser.cancel_wizard(user_id)
    return "Unexpected step. Use /accounts add telegram to start over."


def create_command_parser(orchestrator: Any) -> CommandParser:
    """Create a fully configured command parser with all common commands."""
    parser = CommandParser()
    common = CommonCommands(orchestrator)
    
    parser.register("help", common.handle_help, "Show help information")
    parser.register("commands", common.handle_commands, "List all commands")
    parser.register("status", common.handle_status, "Show system status")
    parser.register("schedule", common.handle_schedule, "Schedule a meeting")
    parser.register("email", common.handle_email, "Manage emails")
    parser.register("remind", common.handle_remind, "Set a reminder")
    parser.register("calendar", common.handle_calendar, "Check calendar")
    parser.register("config", common.handle_config, "View/change settings")
    parser.register("accounts", common.handle_accounts, "Manage accounts (list/add/enable/disable/test)")
    parser.register("meet", common.handle_meet, "Create a Google Meet link")
    parser.register("contacts", common.handle_contacts, "Search contacts")

    # Register wizard handlers for step-by-step account setup
    parser.register_wizard("add_exchange", _wizard_add_exchange)
    parser.register_wizard("add_office365", _wizard_add_office365)
    parser.register_wizard("add_imap", _wizard_add_imap)
    parser.register_wizard("add_caldav", _wizard_add_caldav)
    parser.register_wizard("add_telegram", _wizard_add_telegram)
    
    return parser
