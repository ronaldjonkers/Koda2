"""Robust task scheduler with recurring tasks, reminders, and event triggers.

User-created tasks are persisted to SQLite so they survive service restarts.
System tasks (email check, contact sync, etc.) are re-registered at startup.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Coroutine, Optional
from uuid import uuid4

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, update

from koda2.database import get_session
from koda2.logging_config import get_logger
from koda2.modules.scheduler.models import ScheduledTaskRecord

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
        persisted: bool = False,
    ) -> None:
        self.task_id = task_id
        self.name = name
        self.task_type = task_type
        self.schedule_info = schedule_info
        self.func_name = func_name
        self.persisted = persisted
        self.created_at = dt.datetime.now(dt.UTC)
        self.last_run: Optional[dt.datetime] = None
        self.run_count: int = 0


class SchedulerService:
    """Manages scheduled tasks, reminders, and recurring jobs."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": 300,  # 5 min grace (default 1s is way too strict)
                "coalesce": True,           # merge missed runs into one
                "max_instances": 1,
            },
        )
        self._tasks: dict[str, ScheduledTask] = {}
        self._event_handlers: dict[str, list[AsyncTask]] = {}
        self._executor: Optional[Any] = None  # Set by orchestrator for restoring tasks

    def set_executor(self, executor: Any) -> None:
        """Set the executor (orchestrator) used to restore persisted tasks."""
        self._executor = executor

    async def start(self) -> None:
        """Start the scheduler (idempotent — safe to call multiple times)."""
        if self._scheduler.running:
            return
        self._scheduler.add_listener(self._on_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
        self._scheduler.start()
        logger.info("scheduler_started")

    @staticmethod
    def _on_job_event(event) -> None:
        """Log APScheduler job events for diagnostics."""
        job_id = getattr(event, "job_id", "?")
        if event.code == EVENT_JOB_EXECUTED:
            logger.info("apscheduler_job_executed", job_id=job_id)
        elif event.code == EVENT_JOB_ERROR:
            logger.error("apscheduler_job_error", job_id=job_id, error=str(getattr(event, "exception", "")))
        elif event.code == EVENT_JOB_MISSED:
            logger.warning("apscheduler_job_missed", job_id=job_id)

    async def stop(self) -> None:
        """Shut down the scheduler gracefully."""
        # Persist run counts before shutdown
        await self._sync_run_counts()
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
                    meta.last_run = dt.datetime.now(dt.UTC)
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
                    meta.last_run = dt.datetime.now(dt.UTC)
                    meta.run_count += 1
                logger.info("recurring_task_executed", task_id=task_id, name=name)
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
        run_immediately: bool = False,
    ) -> str:
        """Schedule a task at a fixed interval.

        Args:
            run_immediately: If True, fire once right away then repeat at interval.
        """
        task_id = str(uuid4())

        async def _wrapper():
            try:
                await func(**(kwargs or {}))
                meta = self._tasks.get(task_id)
                if meta:
                    meta.last_run = dt.datetime.now(dt.UTC)
                    meta.run_count += 1
                logger.info("interval_task_executed", task_id=task_id, name=name)
            except Exception as exc:
                logger.error("interval_task_failed", task_id=task_id, error=str(exc))

        next_run = dt.datetime.now(dt.UTC) if run_immediately else None
        self._scheduler.add_job(
            _wrapper,
            trigger=IntervalTrigger(hours=hours, minutes=minutes, seconds=seconds),
            id=task_id,
            name=name,
            next_run_time=next_run,
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
        """Cancel a scheduled task and remove from DB if persisted."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        try:
            self._scheduler.remove_job(task_id)
        except Exception:
            pass  # Job may already be gone from APScheduler
        self._tasks.pop(task_id, None)
        # Always try DB deletion — the task may have been persisted even if
        # the in-memory flag is missing (e.g. after a restart with stale state).
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._delete_from_db(task_id))
            else:
                loop.run_until_complete(self._delete_from_db(task_id))
        except Exception as exc:
            logger.error("cancel_db_delete_failed", task_id=task_id, error=str(exc))
        logger.info("task_cancelled", task_id=task_id)
        return True

    async def run_now(self, task_id: str) -> bool:
        """Manually trigger a scheduled task immediately.

        The task keeps its regular schedule — this is an extra one-off execution.
        Returns True if the task was found and triggered.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return False
        job = self._scheduler.get_job(task_id)
        if job is None:
            return False
        logger.info("task_manual_trigger", task_id=task_id, name=task.name)
        try:
            # Run the job's function directly
            result = job.func()
            # If it's a coroutine, await it
            import asyncio
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.error("task_manual_trigger_failed", task_id=task_id, error=str(exc))
            raise
        return True

    def list_tasks(self) -> list[ScheduledTask]:
        """List all registered tasks."""
        return list(self._tasks.values())

    # ── Persistence ──────────────────────────────────────────────────

    async def persist_task(
        self,
        task_id: str,
        name: str,
        task_type: str,
        schedule_info: str,
        action_type: str,
        action_payload: str,
        created_by: str = "user",
        interval_hours: int = 0,
        interval_minutes: int = 0,
    ) -> None:
        """Save a user-created task to the database."""
        try:
            async with get_session() as session:
                record = ScheduledTaskRecord(
                    id=task_id,
                    name=name,
                    task_type=task_type,
                    schedule_info=schedule_info,
                    action_type=action_type,
                    action_payload=action_payload,
                    is_active=True,
                    created_by=created_by,
                    interval_hours=interval_hours,
                    interval_minutes=interval_minutes,
                )
                session.add(record)
            # Mark in-memory task as persisted
            if task_id in self._tasks:
                self._tasks[task_id].persisted = True
            logger.info("task_persisted", task_id=task_id, name=name)
        except Exception as exc:
            logger.error("task_persist_failed", task_id=task_id, error=str(exc))

    async def restore_persisted_tasks(self) -> int:
        """Restore user-created tasks from the database after restart.

        Returns the number of tasks restored.
        """
        if not self._executor:
            logger.warning("scheduler_no_executor_set_cannot_restore")
            return 0

        restored = 0
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(ScheduledTaskRecord).where(ScheduledTaskRecord.is_active == True)  # noqa: E712
                )
                records = result.scalars().all()

            for rec in records:
                try:
                    if rec.action_type == "command":
                        async def _make_cmd_func(cmd=rec.action_payload):
                            return await self._executor.macos.run_shell(cmd)
                        func = _make_cmd_func
                    elif rec.action_type == "message":
                        async def _make_msg_func(msg=rec.action_payload):
                            if self._executor.whatsapp.is_configured:
                                await self._executor.whatsapp.send_message("me", msg)
                        func = _make_msg_func
                    elif rec.action_type == "chat":
                        async def _make_chat_func(msg=rec.action_payload, by=rec.created_by):
                            result = await self._executor.process_message(by, msg, channel="scheduler")
                            response = result.get("response", "")
                            if self._executor.whatsapp.is_configured and response:
                                try:
                                    await self._executor.whatsapp.send_message(by, response)
                                except Exception:
                                    pass
                        func = _make_chat_func
                    else:
                        logger.warning("unknown_action_type", task_id=rec.id, action_type=rec.action_type)
                        continue

                    if rec.task_type == "cron":
                        self.schedule_recurring(
                            name=rec.name, func=func, cron_expression=rec.schedule_info,
                        )
                        # Fix: replace auto-generated ID with the persisted one
                        self._fix_task_id(rec)
                    elif rec.task_type == "interval":
                        self.schedule_interval(
                            name=rec.name, func=func,
                            hours=rec.interval_hours, minutes=rec.interval_minutes,
                        )
                        self._fix_task_id(rec)
                    elif rec.task_type == "once":
                        from koda2.config import ensure_local_tz
                        run_at = ensure_local_tz(dt.datetime.fromisoformat(rec.schedule_info))
                        if run_at > dt.datetime.now(dt.UTC):
                            self.schedule_once(name=rec.name, func=func, run_at=run_at)
                            self._fix_task_id(rec)
                        else:
                            logger.info("skipping_expired_once_task", task_id=rec.id, name=rec.name)
                            continue

                    restored += 1
                    logger.info("task_restored", task_id=rec.id, name=rec.name, type=rec.task_type)
                except Exception as exc:
                    logger.error("task_restore_failed", task_id=rec.id, error=str(exc))

        except Exception as exc:
            logger.error("restore_persisted_tasks_failed", error=str(exc))

        logger.info("tasks_restored_from_db", count=restored)
        return restored

    def _fix_task_id(self, rec: ScheduledTaskRecord) -> None:
        """Replace the auto-generated task ID with the persisted DB ID.

        When we call schedule_recurring/interval/once, a new UUID is generated.
        We need to swap it with the original DB ID so cancel works correctly.
        """
        # Find the most recently added task (last in dict)
        if not self._tasks:
            return
        last_key = list(self._tasks.keys())[-1]
        last_task = self._tasks.pop(last_key)

        # Remove the auto-generated APScheduler job and re-add with correct ID
        try:
            job = self._scheduler.get_job(last_key)
            if job:
                self._scheduler.remove_job(last_key)
                job.id = rec.id
                self._scheduler.add_job(
                    job.func, trigger=job.trigger, id=rec.id, name=rec.name,
                )
        except Exception:
            pass

        # Store with the correct ID
        last_task.task_id = rec.id
        last_task.persisted = True
        last_task.run_count = rec.run_count
        last_task.last_run = rec.last_run
        self._tasks[rec.id] = last_task

    async def _delete_from_db(self, task_id: str) -> None:
        """Delete a task record from the database."""
        try:
            async with get_session() as session:
                result = await session.execute(
                    select(ScheduledTaskRecord).where(ScheduledTaskRecord.id == task_id)
                )
                record = result.scalar_one_or_none()
                if record:
                    await session.delete(record)
            logger.info("task_deleted_from_db", task_id=task_id)
        except Exception as exc:
            logger.error("task_db_delete_failed", task_id=task_id, error=str(exc))

    async def _sync_run_counts(self) -> None:
        """Sync run counts and last_run to DB for persisted tasks."""
        for task in self._tasks.values():
            if task.persisted and task.run_count > 0:
                try:
                    async with get_session() as session:
                        await session.execute(
                            update(ScheduledTaskRecord)
                            .where(ScheduledTaskRecord.id == task.task_id)
                            .values(run_count=task.run_count, last_run=task.last_run)
                        )
                except Exception as exc:
                    logger.error("sync_run_count_failed", task_id=task.task_id, error=str(exc))

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
                logger.error("event_handler_failed", event_name=event_name, error=str(exc))
