"""Koda2 CLI commands for account management and control."""

from __future__ import annotations

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

# Create Typer app
app = typer.Typer(help="Koda2 AI Executive Assistant CLI", no_args_is_help=True)
console = Console()

# Account subcommand
account_app = typer.Typer(help="Manage accounts", no_args_is_help=True)
app.add_typer(account_app, name="account")

# Service subcommand
service_app = typer.Typer(help="Manage services", no_args_is_help=True)
app.add_typer(service_app, name="service")

# Commands subcommand
cmd_app = typer.Typer(help="Browse available commands", no_args_is_help=True)
app.add_typer(cmd_app, name="commands")


def _async_run(coro):
    """Run an async coroutine."""
    return asyncio.run(coro)


@app.command()
def setup(
    reconfigure: bool = typer.Option(False, "--reconfigure", "-r", help="Force reconfiguration"),
) -> None:
    """Run the setup wizard."""
    import subprocess
    import sys
    from pathlib import Path
    
    # Run setup_wizard.py from project root
    setup_script = Path(__file__).parent.parent.parent / "setup_wizard.py"
    subprocess.run([sys.executable, str(setup_script)])


@app.command()
def doctor() -> None:
    """Run health checks on the Koda2 installation."""
    import shutil
    from pathlib import Path

    console.print("\n[bold cyan]🩺 Koda2 Doctor[/bold cyan]\n")
    issues = 0
    warnings = 0

    def ok(msg: str) -> None:
        console.print(f"  [green]✓[/green] {msg}")

    def warn(msg: str) -> None:
        nonlocal warnings
        warnings += 1
        console.print(f"  [yellow]⚠[/yellow] {msg}")

    def fail(msg: str) -> None:
        nonlocal issues
        issues += 1
        console.print(f"  [red]✗[/red] {msg}")

    # ── Environment ──
    console.print("[bold]Environment[/bold]")
    try:
        from koda2.config import get_settings
        settings = get_settings()
        ok(f"Config loaded (env={settings.koda2_env})")
    except Exception as exc:
        fail(f"Config failed: {exc}")
        settings = None

    env_file = Path(".env")
    if env_file.exists():
        ok(".env file found")
    else:
        warn(".env file missing — using defaults")

    # ── Python deps ──
    console.print("\n[bold]Dependencies[/bold]")
    for pkg in ["fastapi", "sqlalchemy", "chromadb", "httpx", "apscheduler", "pydantic"]:
        try:
            __import__(pkg)
            ok(f"{pkg} installed")
        except ImportError:
            fail(f"{pkg} NOT installed")

    # Optional deps
    for pkg, label in [("playwright", "Browser control"), ("google.oauth2", "Google APIs"), ("anthropic", "Anthropic LLM")]:
        try:
            __import__(pkg)
            ok(f"{label} ({pkg}) available")
        except ImportError:
            warn(f"{label} ({pkg}) not installed — optional")

    # ── Database ──
    console.print("\n[bold]Database[/bold]")
    if settings:
        db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
        if Path(db_path).exists():
            size_mb = Path(db_path).stat().st_size / 1024 / 1024
            ok(f"SQLite DB exists ({size_mb:.1f} MB): {db_path}")
        else:
            warn(f"SQLite DB not found: {db_path} (will be created on first run)")

        chroma_dir = Path(settings.chroma_persist_dir)
        if chroma_dir.exists():
            ok(f"ChromaDB dir exists: {settings.chroma_persist_dir}")
        else:
            warn(f"ChromaDB dir missing: {settings.chroma_persist_dir} (will be created)")

    # ── LLM Providers ──
    console.print("\n[bold]LLM Providers[/bold]")
    if settings:
        if settings.openai_api_key:
            ok("OpenAI API key configured")
        else:
            warn("OpenAI API key not set")
        if settings.anthropic_api_key:
            ok("Anthropic API key configured")
        else:
            warn("Anthropic API key not set")
        if settings.google_ai_api_key:
            ok("Google AI API key configured")
        else:
            warn("Google AI API key not set")
        if settings.openrouter_api_key:
            ok("OpenRouter API key configured")
        else:
            warn("OpenRouter API key not set")

        has_any = any([settings.openai_api_key, settings.anthropic_api_key, settings.google_ai_api_key, settings.openrouter_api_key])
        if not has_any:
            fail("No LLM provider configured — assistant cannot function")

    # ── Messaging ──
    console.print("\n[bold]Messaging[/bold]")
    if settings:
        if getattr(settings, "telegram_bot_token", ""):
            ok("Telegram bot token configured")
        else:
            warn("Telegram not configured")
        if getattr(settings, "whatsapp_enabled", False):
            ok("WhatsApp enabled")
            node = shutil.which("node")
            if node:
                ok(f"Node.js found: {node}")
            else:
                fail("Node.js not found — WhatsApp bridge needs it")
        else:
            warn("WhatsApp not enabled")

    # ── Workspace ──
    console.print("\n[bold]Workspace[/bold]")
    ws = Path("workspace")
    if ws.exists():
        ok("workspace/ directory exists")
        for f in ["SOUL.md", "TOOLS.md"]:
            if (ws / f).exists():
                ok(f"workspace/{f} found")
            else:
                warn(f"workspace/{f} missing — using defaults")
    else:
        warn("workspace/ directory missing — using default prompts")

    # ── Security ──
    console.print("\n[bold]Security[/bold]")
    if settings:
        if settings.koda2_secret_key and settings.koda2_secret_key != "change-me":
            ok("Secret key configured")
        else:
            fail("Secret key is default 'change-me' — change it!")
        if settings.koda2_encryption_key:
            ok("Encryption key configured")
        else:
            warn("Encryption key not set — credentials stored unencrypted")

    # ── Summary ──
    console.print()
    if issues == 0 and warnings == 0:
        console.print("[bold green]All checks passed! ✨[/bold green]")
    elif issues == 0:
        console.print(f"[bold yellow]{warnings} warning(s), no critical issues.[/bold yellow]")
    else:
        console.print(f"[bold red]{issues} issue(s), {warnings} warning(s) — fix the red items above.[/bold red]")
    console.print()


@app.command()
def status() -> None:
    """Show Koda2 status."""
    from koda2.config import get_settings
    from koda2.database import init_db, get_session
    from koda2.modules.account.models import AccountType
    from koda2.modules.account.service import AccountService
    
    async def _status():
        settings = get_settings()
        
        # Print header
        console.print("\n[bold cyan]🤖 Koda2 Status[/bold cyan]\n")
        
        # Environment
        console.print(f"Environment: [green]{settings.koda2_env}[/green]")
        console.print(f"API Port: [green]{settings.api_port}[/green]")
        console.print(f"Log Level: [green]{settings.koda2_log_level}[/green]")
        console.print()
        
        # Database
        try:
            await init_db()
            console.print("Database: [green]✓ Connected[/green]")
        except Exception as e:
            console.print(f"Database: [red]✗ Error: {e}[/red]")
        
        # Accounts
        account_service = AccountService()
        
        table = Table(title="Configured Accounts")
        table.add_column("Type", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Provider", style="yellow")
        table.add_column("Status", style="white")
        table.add_column("Default", style="magenta")
        
        total_accounts = 0
        for acc_type in AccountType:
            accounts = await account_service.get_accounts(account_type=acc_type)
            for acc in accounts:
                total_accounts += 1
                status = "[green]✓ Active" if acc.is_active else "[red]✗ Inactive"
                default = "⭐" if acc.is_default else ""
                table.add_row(
                    acc_type.value,
                    acc.name,
                    acc.provider,
                    status,
                    default,
                )
        
        if total_accounts > 0:
            console.print(table)
        else:
            console.print("[yellow]No accounts configured. Run 'koda2 account add' to add accounts.[/yellow]")
        
        # LLM Providers
        console.print("\n[bold]LLM Providers:[/bold]")
        providers = ["openai", "anthropic", "google", "openrouter"]
        for provider in providers:
            has_it = settings.has_provider(provider)
            symbol = "[green]✓[/green]" if has_it else "[red]✗[/red]"
            console.print(f"  {symbol} {provider.capitalize()}")
        
        console.print()
    
    _async_run(_status())


# ─────────────────────────────────────────────────────────────────────────────
# Account Commands
# ─────────────────────────────────────────────────────────────────────────────

@account_app.command("list")
def account_list(
    account_type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by type (calendar/email/messaging)"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="Filter by provider"),
) -> None:
    """List all accounts."""
    from koda2.modules.account.service import AccountService
    from koda2.modules.account.models import AccountType, ProviderType
    
    async def _list():
        service = AccountService()
        
        # Parse filters
        acc_type = None
        if account_type:
            try:
                acc_type = AccountType(account_type.lower())
            except ValueError:
                console.print(f"[red]Invalid account type: {account_type}[/red]")
                console.print("Valid types: calendar, email, messaging")
                return
        
        prov = None
        if provider:
            try:
                prov = ProviderType(provider.lower())
            except ValueError:
                console.print(f"[red]Invalid provider: {provider}[/red]")
                return
        
        accounts = await service.get_accounts(account_type=acc_type, provider=prov)
        
        if not accounts:
            console.print("[yellow]No accounts found.[/yellow]")
            console.print("Run 'koda2 account add' to add an account.")
            return
        
        table = Table(title="Accounts")
        table.add_column("ID", style="dim", no_wrap=True)
        table.add_column("Name", style="green")
        table.add_column("Type", style="cyan")
        table.add_column("Provider", style="yellow")
        table.add_column("Status", style="white")
        table.add_column("Default", style="magenta")
        
        for acc in accounts:
            status = "[green]✓[/green]" if acc.is_active else "[red]✗[/red]"
            default = "⭐" if acc.is_default else ""
            table.add_row(
                acc.id[:8] + "...",
                acc.name,
                acc.account_type,
                acc.provider,
                status,
                default,
            )
        
        console.print(table)
        console.print(f"\nTotal: {len(accounts)} accounts")
    
    _async_run(_list())


@account_app.command("add")
def account_add() -> None:
    """Add a new account (interactive)."""
    import setup_wizard
    setup_wizard.main()


@account_app.command("delete")
def account_delete(
    account_id: str = typer.Argument(..., help="Account ID (or first 8 characters)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete an account."""
    from koda2.modules.account.service import AccountService
    
    async def _delete():
        service = AccountService()
        
        # Try exact match first
        account = await service.get_account(account_id)
        
        # If not found, try partial match
        if not account:
            all_accounts = await service.get_accounts(active_only=False)
            matches = [a for a in all_accounts if a.id.startswith(account_id)]
            if len(matches) == 1:
                account = matches[0]
            elif len(matches) > 1:
                console.print(f"[red]Multiple accounts match '{account_id}'[/red]")
                return
        
        if not account:
            console.print(f"[red]Account not found: {account_id}[/red]")
            raise typer.Exit(1)
        
        if not force:
            confirm = typer.confirm(f"Delete account '{account.name}' ({account.account_type}/{account.provider})?")
            if not confirm:
                console.print("Cancelled.")
                return
        
        success = await service.delete_account(account.id)
        if success:
            console.print(f"[green]✓ Account '{account.name}' deleted[/green]")
        else:
            console.print("[red]Failed to delete account[/red]")
    
    _async_run(_delete())


@account_app.command("set-default")
def account_set_default(
    account_id: str = typer.Argument(..., help="Account ID (or first 8 characters)"),
) -> None:
    """Set an account as default for its type."""
    from koda2.modules.account.service import AccountService
    
    async def _set_default():
        service = AccountService()
        
        # Try exact match first
        account = await service.get_account(account_id)
        
        # If not found, try partial match
        if not account:
            all_accounts = await service.get_accounts(active_only=False)
            matches = [a for a in all_accounts if a.id.startswith(account_id)]
            if len(matches) == 1:
                account = matches[0]
            elif len(matches) > 1:
                console.print(f"[red]Multiple accounts match '{account_id}'[/red]")
                return
        
        if not account:
            console.print(f"[red]Account not found: {account_id}[/red]")
            raise typer.Exit(1)
        
        updated = await service.set_default(account.id)
        if updated:
            console.print(f"[green]✓ '{account.name}' is now the default {account.account_type} account[/green]")
        else:
            console.print("[red]Failed to update account[/red]")
    
    _async_run(_set_default())


@account_app.command("enable")
def account_enable(
    account_id: str = typer.Argument(..., help="Account ID (or first 8 characters)"),
) -> None:
    """Enable an account."""
    from koda2.modules.account.service import AccountService
    
    async def _enable():
        service = AccountService()
        
        account = await service.get_account(account_id)
        if not account:
            all_accounts = await service.get_accounts(active_only=False)
            matches = [a for a in all_accounts if a.id.startswith(account_id)]
            if len(matches) == 1:
                account = matches[0]
        
        if not account:
            console.print(f"[red]Account not found: {account_id}[/red]")
            raise typer.Exit(1)
        
        updated = await service.update_account(account.id, is_active=True)
        if updated:
            console.print(f"[green]✓ Account '{account.name}' enabled[/green]")
        else:
            console.print("[red]Failed to update account[/red]")
    
    _async_run(_enable())


@account_app.command("disable")
def account_disable(
    account_id: str = typer.Argument(..., help="Account ID (or first 8 characters)"),
) -> None:
    """Disable an account."""
    from koda2.modules.account.service import AccountService
    
    async def _disable():
        service = AccountService()
        
        account = await service.get_account(account_id)
        if not account:
            all_accounts = await service.get_accounts(active_only=False)
            matches = [a for a in all_accounts if a.id.startswith(account_id)]
            if len(matches) == 1:
                account = matches[0]
        
        if not account:
            console.print(f"[red]Account not found: {account_id}[/red]")
            raise typer.Exit(1)
        
        updated = await service.update_account(account.id, is_active=False)
        if updated:
            console.print(f"[green]✓ Account '{account.name}' disabled[/green]")
        else:
            console.print("[red]Failed to update account[/red]")
    
    _async_run(_disable())


@account_app.command("test")
def account_test(
    account_id: str = typer.Argument(..., help="Account ID (or first 8 characters)"),
) -> None:
    """Test account credentials."""
    from koda2.modules.account.service import AccountService
    from koda2.modules.account.models import ProviderType
    
    async def _test():
        service = AccountService()
        
        account = await service.get_account(account_id)
        if not account:
            all_accounts = await service.get_accounts(active_only=False)
            matches = [a for a in all_accounts if a.id.startswith(account_id)]
            if len(matches) == 1:
                account = matches[0]
            elif len(matches) > 1:
                console.print(f"[red]Multiple accounts match '{account_id}'[/red]")
                return
        
        if not account:
            console.print(f"[red]Account not found: {account_id}[/red]")
            raise typer.Exit(1)
        
        console.print(f"Testing account: [cyan]{account.name}[/cyan] ({account.provider})")
        
        # Get decrypted credentials
        try:
            credentials = service.decrypt_credentials(account)
        except Exception as e:
            console.print(f"[red]Failed to decrypt credentials: {e}[/red]")
            return
        
        # Validate
        from koda2.modules.account.models import AccountType, ProviderType
        success, message = await service.validate_account_credentials(
            AccountType(account.account_type),
            ProviderType(account.provider),
            credentials,
        )
        
        if success:
            console.print(f"[green]✓ Credentials are valid![/green]")
        else:
            console.print(f"[red]✗ Validation failed: {message}[/red]")
    
    _async_run(_test())


# ─────────────────────────────────────────────────────────────────────────────
# Service Commands
# ─────────────────────────────────────────────────────────────────────────────

@service_app.command("start")
def service_start(
    daemon: bool = typer.Option(False, "--daemon", "-d", help="Run in background"),
) -> None:
    """Start Koda2 services."""
    import subprocess
    import sys
    
    console.print("[cyan]Starting Koda2...[/cyan]")
    
    if daemon:
        # Start in background (platform-specific)
        import platform
        if platform.system() == "Darwin":  # macOS
            subprocess.Popen(
                [sys.executable, "-m", "koda2.main"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        else:
            subprocess.Popen(
                [sys.executable, "-m", "koda2.main"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        console.print("[green]✓ Koda2 started in background[/green]")
        console.print(f"  Dashboard: http://localhost:8000/dashboard")
    else:
        # Run in foreground
        console.print("Starting in foreground (Ctrl+C to stop)...")
        try:
            subprocess.run([sys.executable, "-m", "koda2.main"])
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped[/yellow]")


@service_app.command("stop")
def service_stop() -> None:
    """Stop Koda2 services."""
    import subprocess
    import signal
    
    console.print("[cyan]Stopping Koda2...[/cyan]")
    
    # Find and kill koda2 processes
    try:
        result = subprocess.run(
            ["pkill", "-f", "koda2.main"],
            capture_output=True,
            text=True,
        )
        console.print("[green]✓ Koda2 stopped[/green]")
    except Exception as e:
        console.print(f"[yellow]Could not stop Koda2: {e}[/yellow]")


@service_app.command("logs")
def service_logs(
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
) -> None:
    """View Koda2 logs."""
    from pathlib import Path
    
    log_file = Path("logs/koda2.log")
    if not log_file.exists():
        console.print("[yellow]No log file found[/yellow]")
        return
    
    if follow:
        import subprocess
        try:
            subprocess.run(["tail", "-f", str(log_file)])
        except KeyboardInterrupt:
            pass
    else:
        content = log_file.read_text().split("\n")
        for line in content[-lines:]:
            console.print(line)


# ─────────────────────────────────────────────────────────────────────────────
# Commands Commands (browse available actions)
# ─────────────────────────────────────────────────────────────────────────────

@cmd_app.command("list")
def commands_list(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="Search commands"),
) -> None:
    """List all available assistant commands."""
    from koda2.modules.commands import get_registry
    
    registry = get_registry()
    
    if search:
        commands = registry.search(search)
        title = f"Commands matching '{search}'"
    elif category:
        commands = registry.list_by_category(category)
        title = f"Commands in category '{category}'"
    else:
        commands = registry.list_all()
        title = "All Available Commands"
    
    if not commands:
        console.print("[yellow]No commands found.[/yellow]")
        return
    
    table = Table(title=title)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Category", style="yellow")
    table.add_column("Description", style="green")
    
    for cmd in commands:
        table.add_row(cmd.name, cmd.category, cmd.description[:60] + "..." if len(cmd.description) > 60 else cmd.description)
    
    console.print(table)
    console.print(f"\nTotal: {len(commands)} commands")
    console.print(f"Categories: {', '.join(registry.categories())}")
    console.print("\nUse 'koda2 commands show <name>' for detailed info on a command.")


@cmd_app.command("show")
def commands_show(
    command_name: str = typer.Argument(..., help="Command name to show details for"),
) -> None:
    """Show detailed information about a specific command."""
    from koda2.modules.commands import get_registry
    
    registry = get_registry()
    cmd = registry.get(command_name)
    
    if not cmd:
        console.print(f"[red]Command '{command_name}' not found.[/red]")
        console.print(f"Available commands: {', '.join(c.name for c in registry.list_all()[:10])}...")
        raise typer.Exit(1)
    
    console.print(f"\n[bold cyan]{cmd.name}[/bold cyan]")
    console.print(f"[dim]Category:[/dim] {cmd.category}")
    console.print(f"\n{cmd.description}")
    
    if cmd.notes:
        console.print(f"\n[yellow]Note:[/yellow] {cmd.notes}")
    
    if cmd.parameters:
        console.print("\n[bold]Parameters:[/bold]")
        for p in cmd.parameters:
            req = "[red]*[/red]" if p.required else "[dim](optional)[/dim]"
            default = f" [dim]default: {p.default}[/dim]" if p.default is not None and not p.required else ""
            console.print(f"  • {p.name} ({p.type}) {req}{default}")
            if p.description:
                console.print(f"    {p.description}")
    
    if cmd.examples:
        console.print("\n[bold]Examples:[/bold]")
        for ex in cmd.examples:
            console.print(f"  {ex}")
    
    console.print()


@cmd_app.command("categories")
def commands_categories() -> None:
    """List all command categories."""
    from koda2.modules.commands import get_registry
    
    registry = get_registry()
    
    console.print("\n[bold]Command Categories:[/bold]\n")
    for cat in registry.categories():
        count = len(registry.list_by_category(cat))
        console.print(f"  • {cat} ({count} commands)")
    
    console.print(f"\nTotal: {len(registry.list_all())} commands across {len(registry.categories())} categories")
    console.print()


# ─────────────────────────────────────────────────────────────────────────────
# Other Commands
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def dashboard() -> None:
    """Open the web dashboard in browser."""
    import webbrowser
    from koda2.config import get_settings
    
    settings = get_settings()
    url = f"http://localhost:{settings.api_port}/dashboard"
    console.print(f"Opening [cyan]{url}[/cyan]...")
    webbrowser.open(url)


@app.command()
def version() -> None:
    """Show Koda2 version."""
    try:
        import importlib.metadata
        ver = importlib.metadata.version("koda2")
    except Exception:
        ver = "unknown"
    
    console.print(f"[bold cyan]Koda2[/bold cyan] version [green]{ver}[/green]")


@app.command()
def chat(
    message: Optional[str] = typer.Argument(None, help="Message to send (if not provided, enters interactive mode)"),
    user_id: str = typer.Option("cli_user", "--user", "-u", help="User ID for the conversation"),
) -> None:
    """Chat with Koda2 from the terminal."""
    import httpx
    from koda2.config import get_settings
    
    settings = get_settings()
    base_url = f"http://localhost:{settings.api_port}"
    
    # Check if server is running
    try:
        response = httpx.get(f"{base_url}/api/health", timeout=5)
        if response.status_code != 200:
            console.print("[red]Koda2 server is not running. Start it with: koda2[/red]")
            raise typer.Exit(1)
    except httpx.ConnectError:
        console.print("[red]Cannot connect to Koda2. Start the server first:[/red]")
        console.print("  [cyan]koda2[/cyan]")
        raise typer.Exit(1)
    
    if message:
        # Single message mode
        try:
            response = httpx.post(
                f"{base_url}/api/chat",
                json={"message": message, "user_id": user_id, "channel": "cli"},
                timeout=60,
            )
            if response.status_code == 200:
                data = response.json()
                console.print(f"[bold green]Koda2:[/bold green] {data.get('response', 'No response')}")
            else:
                console.print(f"[red]Error: {response.status_code}[/red]")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    else:
        # Interactive mode
        console.print("[bold cyan]🤖 Koda2 Terminal Chat[/bold cyan]")
        console.print("[dim]Type your messages below. Use /quit or /exit to exit.[/dim]\n")
        
        while True:
            try:
                user_input = typer.prompt("You")
                
                if user_input.lower() in ("/quit", "/exit", "quit", "exit"):
                    console.print("[dim]Goodbye! 👋[/dim]")
                    break
                
                if not user_input.strip():
                    continue
                
                with console.status("[cyan]Koda2 is thinking...[/cyan]"):
                    response = httpx.post(
                        f"{base_url}/api/chat",
                        json={"message": user_input, "user_id": user_id, "channel": "cli"},
                        timeout=120,
                    )
                
                if response.status_code == 200:
                    data = response.json()
                    console.print(f"[bold green]Koda2:[/bold green] {data.get('response', 'No response')}")
                else:
                    console.print(f"[red]Error: {response.status_code}[/red]")
                    
            except KeyboardInterrupt:
                console.print("\n[dim]Goodbye! 👋[/dim]")
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
