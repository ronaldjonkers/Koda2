"""Koda2 application entry point."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from koda2 import __version__
from koda2.api.routes import router, set_orchestrator
from koda2.config import get_settings
from koda2.database import close_db, init_db
from koda2.logging_config import get_logger, setup_logging
from koda2.orchestrator import Orchestrator

setup_logging()
logger = get_logger(__name__)

_orchestrator: Orchestrator | None = None

BLUE = "\033[0;34m"
GREEN = "\033[0;32m"
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


def _print_status(settings, orch: Orchestrator) -> None:
    """Print the system status after startup."""
    llm = ", ".join(str(p) for p in orch.llm.available_providers) or "none"
    cal = ", ".join(str(p) for p in orch.calendar.active_providers) or "none"
    plugins = len(orch.self_improve.list_plugins())
    tasks = len(orch.scheduler.list_tasks())
    tg = "✔ enabled" if orch.telegram.is_configured else "✘ disabled"
    wa = "✔ enabled" if orch.whatsapp.is_configured else "✘ disabled"

    print(f"""  {BOLD}{GREEN}╔══════════════════════════════════════════════════╗
  ║  🚀 Koda2 is running!                           ║
  ╚══════════════════════════════════════════════════╝{NC}

  {CYAN}▸{NC} Environment:  {BOLD}{settings.koda2_env}{NC}
  {CYAN}▸{NC} API:          {BOLD}http://{settings.api_host}:{settings.api_port}{NC}
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
        print()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    global _orchestrator
    settings = get_settings()

    _print_banner(settings)
    logger.info("koda2_starting", version=__version__)

    settings.data_dir
    settings.logs_dir

    await init_db()

    _orchestrator = Orchestrator()
    set_orchestrator(_orchestrator)

    _orchestrator.self_improve.load_all_plugins()

    await _orchestrator.scheduler.start()

    asyncio.create_task(_start_messaging(_orchestrator))
    asyncio.create_task(_start_whatsapp(_orchestrator))

    _print_status(settings, _orchestrator)
    logger.info(
        "koda2_ready",
        version=__version__,
        env=settings.koda2_env,
        llm_providers=[str(p) for p in _orchestrator.llm.available_providers],
        calendar_providers=[str(p) for p in _orchestrator.calendar.active_providers],
    )

    yield

    print(f"\n  {DIM}🛑 Koda2 shutting down...{NC}")
    logger.info("koda2_shutting_down")
    if _orchestrator:
        await _orchestrator.telegram.stop()
        await _orchestrator.whatsapp.stop()
        await _orchestrator.scheduler.stop()
    await close_db()
    print(f"  {GREEN}✔{NC} Koda2 stopped. Goodbye! 👋\n")
    logger.info("koda2_stopped")


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


app = FastAPI(
    title="Koda2",
    description="Professional AI Executive Assistant — director-level secretary",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


def main() -> None:
    """CLI entry point."""
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
