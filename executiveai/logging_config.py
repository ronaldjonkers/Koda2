"""Structured logging configuration using structlog."""

from __future__ import annotations

import logging
import sys

import structlog

from executiveai.config import get_settings


def setup_logging() -> None:
    """Configure structured logging for the entire application."""
    settings = get_settings()
    log_level = getattr(logging, settings.executiveai_log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer() if settings.executiveai_env == "production"
            else structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a named structured logger."""
    return structlog.get_logger(name)
