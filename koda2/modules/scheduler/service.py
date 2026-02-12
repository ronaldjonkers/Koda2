"""Robust task scheduler with recurring tasks, reminders, and event triggers."""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Coroutine, Optional
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from koda2.logging_config import get_logger

logger = get_logger(__name__)

AsyncTask = Callable[..., Coroutine[Any, Any, Any]]


class ScheduledTask:
    """Metadata about a scheduled task."""

    def __init__(
        self,
        task_id: str,
        name: str,
        task_type: str,
        schedule_info: str,
        func_name: str,
    ) -> None:
        self.task_id = task_id
        self.name = name
        self.task_type = task_type
        self.schedule_info = schedule_info
        self.func_name = func_name
        self.created_at = dt.datetime.utcnow()
        self.last_run: Optional[dt.datetime] = None
        self.run_count: int = 0


class SchedulerService:
    """Manages scheduled tasks, reminders, and recurring jobs."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._tasks: dict[str, ScheduledTask] = {}
        self._event_handlers: dict[str, list[AsyncTask]] = {}

    async def start(self) -> None:
        """Start the scheduler."""
        self._scheduler.start()
        logger.info("scheduler_started")

    async def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        self._scheduler.shutdown(wait=True)
        logger.info("scheduler_stopped")

    def schedule_once(
        self,
        name: str,
        func: AsyncTask,
        run_at: dt.datetime,
        kwargs: Optional[dict[str, Any]] = None,
    ) -> str:
        """Schedule a one-time task at a specific datetime."""
        task_id = str(uuid4())

        async def _wrapper():
            try:
                await func(**(kwargs or {}))
                meta = self._tasks.get(task_id)
                if meta:
                    meta.last_run = dt.datetime.utcnow()
                    meta.run_count += 1
                logger.info("task_executed", task_id=task_id, name=name)
            except Exception as exc:
                logger.error("task_failed", task_id=task_id, name=name, error=str(exc))

        self._scheduler.add_job(
            _wrapper,
            trigger=DateTrigger(run_date=run_at),
            id=task_id,
            name=name,
        )
        self._tasks[task_id] = ScheduledTask(
            task_id=task_id, name=name, task_type="once",
            schedule_info=run_at.isoformat(), func_name=func.__name__,
        )
        logger.info("task_scheduled_once", task_id=task_id, name=name, at=run_at.isoformat())
        return task_id

    def schedule_recurring(
        self,
        name: str,
        func: AsyncTask,
        cron_expression: str,
        kwargs: Optional[dict[str, Any]] = None,
    ) -> str:
        """Schedule a recurring task using a cron expression.

        Cron format: minute hour day_of_month month day_of_week
        """
        task_id = str(uuid4())
        parts = cron_expression.split()
        trigger_kwargs: dict[str, str] = {}
        fields = ["minute", "hour", "day", "month", "day_of_week"]
        for i, part in enumerate(parts):
            if i < len(fields):
                trigger_kwargs[fields[i]] = part

        async def _wrapper():
            try:
                await func(**(kwargs or {}))
                meta = self._tasks.get(task_id)
                if meta:
                    meta.last_run = dt.datetime.utcnow()
                    meta.run_count += 1
            except Exception as exc:
                logger.error("recurring_task_failed", task_id=task_id, error=str(exc))

        self._scheduler.add_job(
            _wrapper,
            trigger=CronTrigger(**trigger_kwargs),
            id=task_id,
            name=name,
        )
        self._tasks[task_id] = ScheduledTask(
            task_id=task_id, name=name, task_type="cron",
            schedule_info=cron_expression, func_name=func.__name__,
        )
        logger.info("task_scheduled_recurring", task_id=task_id, name=name, cron=cron_expression)
        return task_id

    def schedule_interval(
        self,
        name: str,
        func: AsyncTask,
        minutes: int = 0,
        hours: int = 0,
        seconds: int = 0,
        kwargs: Optional[dict[str, Any]] = None,
    ) -> str:
        """Schedule a task at a fixed interval."""
        task_id = str(uuid4())

        async def _wrapper():
            try:
                await func(**(kwargs or {}))
                meta = self._tasks.get(task_id)
                if meta:
                    meta.last_run = dt.datetime.utcnow()
                    meta.run_count += 1
            except Exception as exc:
                logger.error("interval_task_failed", task_id=task_id, error=str(exc))

        self._scheduler.add_job(
            _wrapper,
            trigger=IntervalTrigger(hours=hours, minutes=minutes, seconds=seconds),
            id=task_id,
            name=name,
        )
        interval_str = f"{hours}h{minutes}m{seconds}s"
        self._tasks[task_id] = ScheduledTask(
            task_id=task_id, name=name, task_type="interval",
            schedule_info=interval_str, func_name=func.__name__,
        )
        logger.info("task_scheduled_interval", task_id=task_id, name=name, interval=interval_str)
        return task_id

    def schedule_reminder(
        self,
        name: str,
        callback: AsyncTask,
        remind_at: dt.datetime,
        message: str = "",
    ) -> str:
        """Schedule a reminder notification."""
        return self.schedule_once(
            name=f"reminder: {name}",
            func=callback,
            run_at=remind_at,
            kwargs={"reminder_name": name, "message": message},
        )

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a scheduled task."""
        try:
            self._scheduler.remove_job(task_id)
            self._tasks.pop(task_id, None)
            logger.info("task_cancelled", task_id=task_id)
            return True
        except Exception:
            return False

    def list_tasks(self) -> list[ScheduledTask]:
        """List all registered tasks."""
        return list(self._tasks.values())

    # ── Event-driven triggers ────────────────────────────────────────

    def on_event(self, event_name: str, handler: AsyncTask) -> None:
        """Register a handler for a named event."""
        self._event_handlers.setdefault(event_name, []).append(handler)
        logger.debug("event_handler_registered", event_name=event_name)

    async def emit_event(self, event_name: str, data: Optional[dict[str, Any]] = None) -> None:
        """Emit an event, triggering all registered handlers."""
        handlers = self._event_handlers.get(event_name, [])
        for handler in handlers:
            try:
                await handler(**(data or {}))
            except Exception as exc:
                logger.error("event_handler_failed", event=event_name, error=str(exc))
