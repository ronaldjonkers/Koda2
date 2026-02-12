"""Command parser for messaging platforms (Telegram, WhatsApp).

Provides unified command handling across all messaging platforms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Optional

CommandHandler = Callable[..., Coroutine[Any, Any, str]]


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
            response = await handler(
                user_id=user_id,
                args=parsed.args,
                command=parsed.command,
                platform=parsed.platform,
                **kwargs,
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
        providers = self._orch.calendar.active_providers
        plugins = self._orch.self_improve.list_plugins()
        tasks = self._orch.scheduler.list_tasks()
        
        return (
            f"*Koda2 Status*\n"
            f"Version: {self._orch.__dict__.get('_version', 'unknown')}\n"
            f"Calendar providers: {', '.join(str(p) for p in providers) or 'none'}\n"
            f"Email: {'IMAP ✓' if self._orch.email.imap_configured else 'IMAP ✗'} / "
            f"{'SMTP ✓' if self._orch.email.smtp_configured else 'SMTP ✗'}\n"
            f"LLM providers: {', '.join(str(p) for p in self._orch.llm.available_providers) or 'none'}\n"
            f"Plugins loaded: {len(plugins)}\n"
            f"Scheduled tasks: {len(tasks)}"
        )
    
    async def handle_help(self, user_id: str, **kwargs: Any) -> str:
        """Show help information."""
        platform = kwargs.get("platform", "api")
        return (
            f"*Koda2 Help*\n\n"
            f"Send me natural language requests like:\n"
            f"• \"Schedule a meeting with John tomorrow at 2pm\"\n"
            f"• \"Check my email\"\n"
            f"• \"Create a reminder to call mom\"\n\n"
            f"Or use commands (see /commands)"
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
                f"Calendar providers: {len(self._orch.calendar.active_providers)}\n"
                f"Git auto-commit: {'enabled' if self._orch._settings.git_auto_commit else 'disabled'}"
            )
        elif subcmd == "set" and len(parts) > 1:
            return "⚠️ Settings can only be changed via the .env file or setup wizard for security."
        
        return "Unknown config command. Use /config for help."
    
    async def handle_commands(self, user_id: str, **kwargs: Any) -> str:
        """List all available commands."""
        parser = kwargs.get("parser")
        if parser:
            return parser.get_help()
        return "Commands available: /help, /status, /schedule, /email, /remind, /calendar, /config, /accounts"
    
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
            return (
                "*Add Account*\n\n"
                "Account setup is done through the web dashboard or CLI:\n"
                "• Dashboard: http://localhost:8000/dashboard\n"
                "• CLI: koda2 account add\n\n"
                "Available account types:\n"
                "• Exchange (EWS)\n"
                "• Office 365 (Microsoft Graph)\n"
                "• Google (Calendar + Gmail)\n"
                "• CalDAV (Apple, Nextcloud)\n"
                "• IMAP/SMTP\n"
                "• Telegram Bot"
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
                "/accounts default [name] - Show or set default account\n"
                "/accounts enable <name> - Enable an account\n"
                "/accounts disable <name> - Disable an account\n"
                "/accounts test <name> - Test account credentials\n"
                "/accounts delete <name> - Delete an account\n"
                "/accounts add - Show how to add accounts"
            )
        
        else:
            return f"Unknown subcommand: {subcmd}\nUse /accounts help for available commands."


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
    
    return parser
