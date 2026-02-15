"""Koda2 application entry point.

Quick Start:
    $ koda2                    # Start the server
    $ koda2-setup              # Run setup wizard
    $ koda2-config             # Edit configuration
    
Environment:
    KODA2_ENV                   # development/production (default: production)
    KODA2_LOG_LEVEL            # DEBUG/INFO/WARNING/ERROR (default: INFO)
"""

from __future__ import annotations

import asyncio
import atexit
import os
import signal
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import socketio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# ── Enable faulthandler for SIGSEGV diagnostics ──────────────────────
# Prints a Python traceback on SIGSEGV/SIGFPE/SIGABRT so we can identify
# which C extension (ChromaDB/hnswlib, SQLite, etc.) caused a native crash.
import faulthandler as _faulthandler
_faulthandler.enable()

# ── Startup hygiene: clean stale bytecode and shadow directories ──────
# After git pull, stale __pycache__ .pyc files can shadow updated .py sources
# on some systems (timestamp skew, NFS mounts, etc.). Purge them once at import.
import shutil as _shutil

_koda2_root = Path(__file__).parent
for _cache_dir in _koda2_root.rglob("__pycache__"):
    _shutil.rmtree(_cache_dir, ignore_errors=True)

# Remove stale package directories that shadow module files.
# The evolution engine sometimes creates directories (e.g. orchestrator/, routes/)
# that shadow the corresponding .py files, breaking imports.
for _py_file in _koda2_root.rglob("*.py"):
    _shadow_dir = _py_file.with_suffix("")
    if _shadow_dir.is_dir():
        _shutil.rmtree(_shadow_dir, ignore_errors=True)

from koda2 import __version__
from koda2.api.routes import router, set_orchestrator
from koda2.config import get_settings
from koda2.dashboard.websocket import sio
from koda2.database import close_db, init_db
from koda2.logging_config import get_logger, setup_logging
from koda2.modules.metrics.service import MetricsService
from koda2.orchestrator import Orchestrator

setup_logging()
logger = get_logger(__name__)

_orchestrator: Orchestrator | None = None
_metrics: MetricsService | None = None
_background_tasks: list[asyncio.Task] = []
_shutdown_in_progress = False

BLUE = "\033[0;34m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
BOLD = "\033[1m"
NC = "\033[0m"


def _print_banner(settings) -> None:
    """Print the Koda2 startup banner."""
    print(f"""
{BOLD}{BLUE}  ██╗  ██╗ ██████╗ ██████╗  █████╗ ██████╗
  ██║ ██╔╝██╔═══██╗██╔══██╗██╔══██╗╚════██╗
  █████╔╝ ██║   ██║██║  ██║███████║ █████╔╝
  ██╔═██╗ ██║   ██║██║  ██║██╔══██║██╔═══╝
  ██║  ██╗╚██████╔╝██████╔╝██║  ██║███████╗
  ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝{NC}

  {DIM}Professional AI Executive Assistant — v{__version__}{NC}
""")


async def _print_status(settings, orch: Orchestrator) -> None:
    """Print the system status after startup."""
    llm = ", ".join(str(p) for p in orch.llm.available_providers) or "none"
    cal_providers = await orch.calendar.active_providers()
    cal = ", ".join(str(p) for p in cal_providers) or "none"
    plugins = len(orch.self_improve.list_plugins())
    tasks = len(orch.scheduler.list_tasks())
    tg_configured = await orch.telegram.is_configured()
    tg = "✔ enabled" if tg_configured else "✘ disabled"
    wa = "✔ enabled" if orch.whatsapp.is_configured else "✘ disabled"

    print(f"""  {BOLD}{GREEN}╔══════════════════════════════════════════════════╗
  ║  🚀 Koda2 is running!                           ║
  ╚══════════════════════════════════════════════════╝{NC}

  {CYAN}▸{NC} Environment:  {BOLD}{settings.koda2_env}{NC}
  {CYAN}▸{NC} API:          {BOLD}http://{settings.api_host}:{settings.api_port}{NC}
  {CYAN}▸{NC} Dashboard:    {BOLD}http://localhost:{settings.api_port}/dashboard{NC}
  {CYAN}▸{NC} API docs:     {DIM}http://localhost:{settings.api_port}/docs{NC}
  {CYAN}▸{NC} LLM:          {llm}
  {CYAN}▸{NC} Calendar:     {cal}
  {CYAN}▸{NC} Telegram:     {tg}
  {CYAN}▸{NC} WhatsApp:     {wa}
  {CYAN}▸{NC} Plugins:      {plugins} loaded
  {CYAN}▸{NC} Scheduled:    {tasks} tasks
""")
    if orch.whatsapp.is_configured:
        print(f"  {BOLD}📱 WhatsApp:{NC} Scan QR at {DIM}http://localhost:{settings.api_port}/api/whatsapp/qr{NC}")
    print(f"  {BOLD}🖥️  Dashboard:{NC} Open {DIM}http://localhost:{settings.api_port}/dashboard{NC} for the web interface")
    print()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    global _orchestrator, _task_queue, _metrics
    settings = get_settings()

    _print_banner(settings)
    logger.info("koda2_starting", version=__version__)

    # Check if LLM is configured, if not prompt user
    await _ensure_llm_configured(settings)

    settings.data_dir
    settings.logs_dir

    await init_db()

    # Repair accounts with broken encryption (e.g. after key change)
    from koda2.modules.account.service import AccountService
    _acct_svc = AccountService()
    repaired = await _acct_svc.repair_broken_accounts()
    if repaired:
        logger.info("accounts_repaired_on_startup", count=repaired)

    # Initialize orchestrator (includes task queue)
    _orchestrator = Orchestrator()
    
    # Initialize metrics
    _metrics = MetricsService(collection_interval=5)
    await _metrics.start()
    _orchestrator.metrics = _metrics
    set_orchestrator(_orchestrator)

    # Full startup: scheduler + restore persisted tasks + system tasks + proactive + task queue + plugins
    if hasattr(_orchestrator, "startup"):
        await _orchestrator.startup()
    else:
        logger.error("orchestrator_missing_startup_method — run: git fetch origin && git reset --hard origin/main")

    # Initialize WebSocket with orchestrator's task queue and metrics
    from koda2.dashboard.websocket import DashboardWebSocket
    dashboard_ws = DashboardWebSocket(_orchestrator.task_queue, _metrics)
    sio.dashboard_ws = dashboard_ws
    await dashboard_ws.start()

    _background_tasks.append(asyncio.create_task(_start_messaging(_orchestrator)))
    _background_tasks.append(asyncio.create_task(_start_whatsapp(_orchestrator)))
    _background_tasks.append(asyncio.create_task(_periodic_token_refresh(_orchestrator)))
    _background_tasks.append(asyncio.create_task(_periodic_calendar_sync(_orchestrator)))

    await _print_status(settings, _orchestrator)
    
    # Open browser automatically (unless disabled)
    if not getattr(main, '_no_browser', False):
        await _open_browser(settings)
    
    cal_providers = await _orchestrator.calendar.active_providers()
    logger.info(
        "koda2_ready",
        version=__version__,
        env=settings.koda2_env,
        llm_providers=[str(p) for p in _orchestrator.llm.available_providers],
        calendar_providers=[str(p) for p in cal_providers],
    )

    # Register atexit safety net (kills child processes even on hard exit)
    atexit.register(_atexit_cleanup)

    yield

    await _graceful_shutdown()


async def _graceful_shutdown() -> None:
    """Gracefully shut down all services and child processes."""
    global _shutdown_in_progress
    if _shutdown_in_progress:
        return
    _shutdown_in_progress = True

    print(f"\n  {DIM}🛑 Koda2 shutting down...{NC}")
    logger.info("koda2_shutting_down")

    # 1. Cancel background asyncio tasks
    for task in _background_tasks:
        if not task.done():
            task.cancel()
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()

    # 2. Stop services (order: orchestrator → metrics → ws → db)
    if _orchestrator:
        try:
            await _orchestrator.shutdown()
        except Exception as exc:
            logger.warning("orchestrator_shutdown_error", error=str(exc))

    if _metrics:
        try:
            await _metrics.stop()
        except Exception as exc:
            logger.warning("metrics_stop_error", error=str(exc))

    if hasattr(sio, 'dashboard_ws') and sio.dashboard_ws:
        try:
            await sio.dashboard_ws.stop()
        except Exception as exc:
            logger.warning("websocket_stop_error", error=str(exc))

    try:
        await close_db()
    except Exception as exc:
        logger.warning("db_close_error", error=str(exc))

    print(f"  {GREEN}✔{NC} Koda2 stopped. Goodbye! 👋\n")
    logger.info("koda2_stopped")


def _atexit_cleanup() -> None:
    """Safety-net cleanup called on interpreter exit.

    This runs even when the event loop is gone, so it can only do
    synchronous work — primarily killing child processes.
    """
    if _orchestrator:
        try:
            _orchestrator.whatsapp.stop_sync()
        except Exception:
            pass


async def _ensure_llm_configured(settings) -> None:
    """Check if LLM is configured and prompt user if not."""
    # Check if any provider is configured
    has_provider = False
    provider_name = None
    
    if settings.openai_api_key:
        has_provider = True
        provider_name = "openai"
    elif settings.anthropic_api_key:
        has_provider = True
        provider_name = "anthropic"
    elif settings.google_ai_api_key:
        has_provider = True
        provider_name = "google"
    elif settings.openrouter_api_key:
        has_provider = True
        provider_name = "openrouter"
    
    if not has_provider:
        print(f"\n  {YELLOW}⚠ No LLM provider configured!{NC}")
        print(f"  Koda2 needs an AI model to function.\n")
        
        print("  Available providers:")
        print("    1. OpenAI (recommended)")
        print("    2. Anthropic (Claude)")
        print("    3. Google AI (Gemini)")
        print("    4. OpenRouter")
        print("    5. Exit and configure manually\n")
        
        choice = input("  Select provider (1-5): ").strip()
        
        if choice == "5":
            print(f"\n  Run setup wizard: {CYAN}koda2 --setup{NC}")
            raise SystemExit(1)
        
        # Import here to avoid circular dependency
        import getpass
        
        if choice == "1":
            api_key = getpass.getpass("  OpenAI API key: ").strip()
            if api_key:
                model = input("  Model (default: gpt-4o): ").strip() or "gpt-4o"
                _update_env_file({
                    "OPENAI_API_KEY": api_key,
                    "LLM_DEFAULT_PROVIDER": "openai",
                    "LLM_DEFAULT_MODEL": model,
                })
                # Reload settings
                from koda2.config import get_settings
                settings = get_settings()
                print(f"  {GREEN}✓ OpenAI configured{NC}")
        
        elif choice == "2":
            api_key = getpass.getpass("  Anthropic API key: ").strip()
            if api_key:
                model = input("  Model (default: claude-3-opus-20240229): ").strip() or "claude-3-opus-20240229"
                _update_env_file({
                    "ANTHROPIC_API_KEY": api_key,
                    "LLM_DEFAULT_PROVIDER": "anthropic",
                    "LLM_DEFAULT_MODEL": model,
                })
                print(f"  {GREEN}✓ Anthropic configured{NC}")
        
        elif choice == "3":
            api_key = getpass.getpass("  Google AI API key: ").strip()
            if api_key:
                _update_env_file({
                    "GOOGLE_AI_API_KEY": api_key,
                    "LLM_DEFAULT_PROVIDER": "google",
                    "LLM_DEFAULT_MODEL": "gemini-pro",
                })
                print(f"  {GREEN}✓ Google AI configured{NC}")
        
        elif choice == "4":
            api_key = getpass.getpass("  OpenRouter API key: ").strip()
            if api_key:
                model = input("  Model (default: openai/gpt-4o): ").strip() or "openai/gpt-4o"
                _update_env_file({
                    "OPENROUTER_API_KEY": api_key,
                    "OPENROUTER_MODEL": model,
                    "LLM_DEFAULT_PROVIDER": "openrouter",
                    "LLM_DEFAULT_MODEL": model,
                })
                print(f"  {GREEN}✓ OpenRouter configured{NC}")
        else:
            print(f"  {YELLOW}Invalid choice. Run setup with:{NC} koda2 --setup")
            raise SystemExit(1)
    
    # Check if model is set (especially important for OpenRouter)
    elif has_provider and (not settings.llm_default_model or 
                           (provider_name == "openrouter" and not settings.openrouter_model)):
        print(f"\n  {YELLOW}⚠ LLM provider configured but no model selected!{NC}")
        
        default_models = {
            "openai": "gpt-4o",
            "anthropic": "claude-3-opus-20240229",
            "google": "gemini-pro",
            "openrouter": settings.openrouter_model or "openai/gpt-4o",
        }
        
        default = default_models.get(provider_name, "gpt-4o")
        model = input(f"  Model (default: {default}): ").strip() or default
        
        updates = {"LLM_DEFAULT_MODEL": model}
        if provider_name == "openrouter":
            updates["OPENROUTER_MODEL"] = model
        
        _update_env_file(updates)
        print(f"  {GREEN}✓ Model set to {model}{NC}")


def _update_env_file(updates: dict[str, str]) -> None:
    """Update environment variables in .env file."""
    env_path = Path(".env")
    
    # Read existing
    lines = []
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()
    
    # Parse existing values
    existing = {}
    for i, line in enumerate(lines):
        if "=" in line and not line.strip().startswith("#"):
            key, _, value = line.strip().partition("=")
            existing[key] = (i, value)
    
    # Update or append
    for key, value in updates.items():
        if key in existing:
            idx, _ = existing[key]
            lines[idx] = f"{key}={value}\n"
        else:
            lines.append(f"{key}={value}\n")
    
    # Write back
    with open(env_path, "w") as f:
        f.writelines(lines)


async def _open_browser(settings, delay: float = 2.0) -> None:
    """Open the dashboard in the default browser after a short delay."""
    import webbrowser
    await asyncio.sleep(delay)  # Wait for server to be fully ready
    
    url = f"http://localhost:{settings.api_port}/dashboard"
    try:
        # Try to open browser
        opened = webbrowser.open(url, new=2)  # new=2 opens in new tab
        if opened:
            print(f"\n  {GREEN}✔{NC} Opened dashboard in your browser")
            print(f"     {DIM}{url}{NC}")
        else:
            print(f"\n  {YELLOW}⚠{NC} Could not open browser automatically")
            print(f"     Please open manually: {CYAN}{url}{NC}")
    except Exception as exc:
        logger.warning("browser_open_failed", error=str(exc))
        print(f"\n  {YELLOW}⚠{NC} Could not open browser: {exc}")
        print(f"     Please open manually: {CYAN}{url}{NC}")


async def _start_messaging(orch: Orchestrator) -> None:
    """Start messaging integrations in the background."""
    try:
        await orch.setup_telegram()
    except Exception as exc:
        logger.error("telegram_start_failed", error=str(exc))


async def _start_whatsapp(orch: Orchestrator) -> None:
    """Start WhatsApp bridge in the background."""
    try:
        await orch.setup_whatsapp()
    except Exception as exc:
        logger.error("whatsapp_start_failed", error=str(exc))


async def _periodic_calendar_sync(orch: Orchestrator) -> None:
    """Periodically sync calendar events from remote providers to local DB.
    
    First sync after 10 seconds, then every 5 minutes.
    """
    SYNC_INTERVAL = 5 * 60  # 5 minutes
    await asyncio.sleep(10)  # Let startup finish

    while True:
        try:
            results = await orch.calendar.sync_all()
            total = sum(v for v in results.values() if v >= 0)
            logger.info("calendar_sync_done", total_events=total, accounts=results)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("calendar_sync_error", error=str(exc))

        try:
            await asyncio.sleep(SYNC_INTERVAL)
        except asyncio.CancelledError:
            break


async def _periodic_token_refresh(orch: Orchestrator) -> None:
    """Periodically refresh Google OAuth tokens to keep connections alive.
    
    Runs every 45 minutes (tokens expire after 60 minutes).
    """
    REFRESH_INTERVAL = 45 * 60  # 45 minutes
    # Wait a bit before first refresh to let startup complete
    await asyncio.sleep(60)

    while True:
        try:
            # Refresh tokens for all Google calendar providers
            for provider in orch.calendar._providers.values():
                if hasattr(provider, 'refresh_token'):
                    success = await provider.refresh_token()
                    if success:
                        logger.info("google_token_refreshed")
                    else:
                        logger.warning("google_token_refresh_failed")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.error("token_refresh_error", error=str(exc))

        try:
            await asyncio.sleep(REFRESH_INTERVAL)
        except asyncio.CancelledError:
            break


# Create main FastAPI app first
_fastapi_app = FastAPI(
    title="Koda2",
    description="Professional AI Executive Assistant — director-level secretary",
    version=__version__,
    lifespan=lifespan,
)

_fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
_fastapi_app.include_router(router, prefix="/api")


# Dashboard routes - must be defined before Socket.IO wraps the app
@_fastapi_app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    """Serve the dashboard HTML."""
    dashboard_path = Path(__file__).parent / "dashboard" / "templates" / "index.html"
    if dashboard_path.exists():
        return dashboard_path.read_text(encoding="utf-8")
    return "<h1>Dashboard not found</h1><p>Please check installation.</p>"


@_fastapi_app.get("/", response_class=HTMLResponse)
async def root() -> str:
    """Redirect to dashboard."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="0; url=/dashboard">
        <title>Koda2</title>
    </head>
    <body>
        <p>Redirecting to <a href="/dashboard">dashboard</a>...</p>
    </body>
    </html>
    """


# Mount static files for dashboard
static_path = Path(__file__).parent / "dashboard" / "static"
if static_path.exists():
    _fastapi_app.mount("/static", StaticFiles(directory=str(static_path)), name="static")


# Create the combined Socket.IO + FastAPI app
# Socket.IO handles WebSocket at /socket.io/, everything else goes to FastAPI
app = socketio.ASGIApp(sio, other_asgi_app=_fastapi_app)


def check_first_run() -> bool:
    """Check if this is the first time running Koda2."""
    env_path = Path(".env")
    if not env_path.exists():
        return True
    content = env_path.read_text()
    if "change-me" in content:
        return True
    if "KODA2_SECRET_KEY=" not in content or "KODA2_SECRET_KEY=change-me" in content:
        return True
    return False


def run_setup_wizard() -> None:
    """Run the setup wizard."""
    setup_script = Path(__file__).parent.parent / "setup_wizard.py"
    subprocess.run([sys.executable, str(setup_script)])


def main() -> None:
    """CLI entry point with argument parsing."""
    import argparse
    
    # Initialize attribute for lifespan context
    main._no_browser = False
    
    parser = argparse.ArgumentParser(
        description="Koda2 - Professional AI Executive Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  koda2                      Start the server (opens browser automatically)
  koda2 --no-browser         Start without opening browser
  koda2 --setup              Run setup wizard
  koda2 --config             Edit configuration
  koda2 --version            Show version
        """
    )
    
    parser.add_argument(
        "--setup", "-s",
        action="store_true",
        help="Run the setup wizard to configure Koda2"
    )
    parser.add_argument(
        "--config", "-c",
        action="store_true",
        help="Edit configuration (same as --setup)"
    )
    parser.add_argument(
        "--version", "-v",
        action="store_true",
        help="Show version information"
    )
    parser.add_argument(
        "--no-setup-check",
        action="store_true",
        help="Skip first-run setup check"
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically on startup"
    )
    
    args = parser.parse_args()
    
    # Store --no-browser flag for lifespan context
    main._no_browser = args.no_browser
    
    if args.version:
        from koda2 import __version__
        print(f"Koda2 version {__version__}")
        return
    
    if args.setup or args.config:
        run_setup_wizard()
        return
    
    # Check first run
    if not args.no_setup_check and check_first_run():
        print("""
╔══════════════════════════════════════════════════════════════╗
║  🤖 Welcome to Koda2!                                        ║
║                                                              ║
║  It looks like this is your first time running Koda2.        ║
║  Let's get you set up!                                       ║
╚══════════════════════════════════════════════════════════════╝
""")
        response = input("Start setup wizard now? [Y/n]: ").strip().lower()
        if response in ("", "y", "yes"):
            run_setup_wizard()
            # After setup, ask if they want to start
            print("\nSetup complete!")
            start_now = input("Start Koda2 now? [Y/n]: ").strip().lower()
            if start_now not in ("", "y", "yes"):
                return
        else:
            print("\nYou can run setup later with: koda2 --setup")
            print("Continuing with default configuration...\n")
    
    # Start the server
    settings = get_settings()
    uvicorn.run(
        "koda2.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.koda2_env == "development",
        log_level=settings.koda2_log_level.lower(),
    )


if __name__ == "__main__":
    main()
