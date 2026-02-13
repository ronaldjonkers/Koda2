"""Database models for persistent scheduled tasks."""

from __future__ import annotations

import datetime as dt
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Text, Boolean, Integer

from koda2.database import Base


class ScheduledTaskRecord(Base):
    """Persisted scheduled task that survives service restarts.

    Only user-created tasks are stored here. System tasks (email check,
    contact sync, etc.) are re-registered at startup and don't need persistence.
    """

    __tablename__ = "scheduled_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(256), nullable=False)
    task_type = Column(String(32), nullable=False)  # cron, interval, once
    schedule_info = Column(String(256), nullable=False)  # cron expr, interval str, or ISO datetime
    action_type = Column(String(32), nullable=False)  # "command" or "message"
    action_payload = Column(Text, nullable=False)  # shell command or message text
    is_active = Column(Boolean, default=True, nullable=False)
    run_count = Column(Integer, default=0, nullable=False)
    last_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: dt.datetime.now(dt.UTC), nullable=False)
    created_by = Column(String(128), default="system", nullable=False)

    # For interval tasks
    interval_hours = Column(Integer, default=0, nullable=False)
    interval_minutes = Column(Integer, default=0, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<ScheduledTaskRecord(id={self.id}, name={self.name}, "
            f"type={self.task_type}, active={self.is_active})>"
        )
