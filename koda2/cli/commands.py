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


def _async_run(coro):
    """Run an async coroutine."""
    return asyncio.run(coro)


@app.command()
def setup(
    reconfigure: bool = typer.Option(False, "--reconfigure", "-r", help="Force reconfiguration"),
) -> None:
    """Run the setup wizard."""
    from setup_wizard import main
    main()


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
def commit(
    message: Optional[str] = typer.Argument(None, help="Commit message"),
    push: bool = typer.Option(True, "--push/--no-push", help="Push to remote"),
) -> None:
    """Manually trigger git commit and push."""
    async def _commit():
        from koda2.modules.git_manager import commit_now
        
        console.print("[cyan]Checking for changes to commit...[/cyan]")
        result = await commit_now(message or "Manual commit via CLI")
        
        if result["committed"]:
            console.print(f"[green]✓ Committed:[/green] {result.get('message', '').split(chr(10))[0]}")
            if push and result.get("pushed"):
                console.print("[green]✓ Pushed to remote[/green]")
            elif push:
                console.print("[yellow]⚠ Could not push to remote[/yellow]")
        else:
            if result.get("reason") == "disabled":
                console.print("[yellow]Auto-commit is disabled in .env[/yellow]")
            elif result.get("reason") == "not_a_repo":
                console.print("[red]Not a git repository[/red]")
            else:
                console.print("[yellow]No changes to commit[/yellow]")
    
    _async_run(_commit())


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
