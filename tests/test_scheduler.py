"""Tests for the task scheduler module."""

from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from koda2.modules.scheduler.service import SchedulerService


class TestSchedulerService:
    """Tests for the scheduler service."""

    @pytest.fixture
    def scheduler(self) -> SchedulerService:
        """Create a SchedulerService instance."""
        return SchedulerService()

    @pytest.mark.asyncio
    async def test_start_and_stop(self, scheduler: SchedulerService) -> None:
        """Scheduler starts and stops cleanly."""
        await scheduler.start()
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_schedule_once(self, scheduler: SchedulerService) -> None:
        """One-time task is registered."""
        await scheduler.start()

        async def dummy_task(**kwargs):
            pass

        task_id = scheduler.schedule_once(
            "test_task",
            dummy_task,
            run_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
        )
        assert task_id is not None
        assert len(scheduler.list_tasks()) == 1
        assert scheduler.list_tasks()[0].name == "test_task"

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_schedule_recurring(self, scheduler: SchedulerService) -> None:
        """Recurring task is registered with cron expression."""
        await scheduler.start()

        async def dummy_task(**kwargs):
            pass

        task_id = scheduler.schedule_recurring(
            "daily_check",
            dummy_task,
            cron_expression="0 9 * * *",
        )
        assert task_id is not None
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_type == "cron"

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_schedule_interval(self, scheduler: SchedulerService) -> None:
        """Interval task is registered."""
        await scheduler.start()

        async def dummy_task(**kwargs):
            pass

        task_id = scheduler.schedule_interval(
            "periodic_check", dummy_task, minutes=30,
        )
        assert task_id is not None
        tasks = scheduler.list_tasks()
        assert tasks[0].task_type == "interval"

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_cancel_task(self, scheduler: SchedulerService) -> None:
        """Cancelling a task removes it."""
        await scheduler.start()

        async def dummy_task(**kwargs):
            pass

        task_id = scheduler.schedule_once(
            "to_cancel", dummy_task,
            run_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
        )
        assert len(scheduler.list_tasks()) == 1
        assert scheduler.cancel_task(task_id) is True
        assert len(scheduler.list_tasks()) == 0

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, scheduler: SchedulerService) -> None:
        """Cancelling a nonexistent task returns False."""
        await scheduler.start()
        assert scheduler.cancel_task("nonexistent-id") is False
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_event_handler(self, scheduler: SchedulerService) -> None:
        """Event handlers are triggered on emit."""
        results = []

        async def handler(**kwargs):
            results.append(kwargs)

        scheduler.on_event("test_event", handler)
        await scheduler.emit_event("test_event", {"key": "value"})
        assert len(results) == 1
        assert results[0]["key"] == "value"

    @pytest.mark.asyncio
    async def test_schedule_reminder(self, scheduler: SchedulerService) -> None:
        """Reminders are scheduled as one-time tasks."""
        await scheduler.start()

        async def callback(**kwargs):
            pass

        task_id = scheduler.schedule_reminder(
            "standup", callback,
            remind_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
            message="Daily standup in 15 minutes",
        )
        tasks = scheduler.list_tasks()
        assert len(tasks) == 1
        assert "reminder" in tasks[0].name

        await scheduler.stop()
