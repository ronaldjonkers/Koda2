"""ExecutiveAI application entry point."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from executiveai import __version__
from executiveai.api.routes import router, set_orchestrator
from executiveai.config import get_settings
from executiveai.database import close_db, init_db
from executiveai.logging_config import get_logger, setup_logging
from executiveai.orchestrator import Orchestrator

setup_logging()
logger = get_logger(__name__)

_orchestrator: Orchestrator | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    global _orchestrator
    logger.info("executiveai_starting", version=__version__)

    settings = get_settings()
    settings.data_dir
    settings.logs_dir

    await init_db()

    _orchestrator = Orchestrator()
    set_orchestrator(_orchestrator)

    _orchestrator.self_improve.load_all_plugins()

    await _orchestrator.scheduler.start()

    asyncio.create_task(_start_messaging(_orchestrator))

    logger.info(
        "executiveai_ready",
        version=__version__,
        env=settings.executiveai_env,
        llm_providers=[str(p) for p in _orchestrator.llm.available_providers],
        calendar_providers=[str(p) for p in _orchestrator.calendar.active_providers],
    )

    yield

    logger.info("executiveai_shutting_down")
    if _orchestrator:
        await _orchestrator.telegram.stop()
        await _orchestrator.scheduler.stop()
    await close_db()
    logger.info("executiveai_stopped")


async def _start_messaging(orch: Orchestrator) -> None:
    """Start messaging integrations in the background."""
    try:
        await orch.setup_telegram()
    except Exception as exc:
        logger.error("telegram_start_failed", error=str(exc))


app = FastAPI(
    title="ExecutiveAI",
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
        "executiveai.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.executiveai_env == "development",
        log_level=settings.executiveai_log_level.lower(),
    )


if __name__ == "__main__":
    main()
