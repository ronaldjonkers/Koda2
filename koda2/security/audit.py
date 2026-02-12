"""Comprehensive audit logging for all system actions."""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.sqlite import JSON as SQLiteJSON

from koda2.database import Base, get_session
from koda2.logging_config import get_logger

logger = get_logger(__name__)


class AuditLog(Base):
    """Persistent audit log entry."""

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    timestamp = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC), nullable=False, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    action = Column(String(256), nullable=False, index=True)
    module = Column(String(128), nullable=False)
    details = Column(SQLiteJSON, nullable=True)
    ip_address = Column(String(45), nullable=True)
    status = Column(String(32), default="success")


async def log_action(
    user_id: str,
    action: str,
    module: str,
    details: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    status: str = "success",
) -> None:
    """Write an audit log entry to the database."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        module=module,
        details=details,
        ip_address=ip_address,
        status=status,
    )
    try:
        async with get_session() as session:
            session.add(entry)
        logger.debug("audit_logged", action=action, user_id=user_id, module=module)
    except Exception as exc:
        logger.error("audit_log_failed", action=action, error=str(exc))
