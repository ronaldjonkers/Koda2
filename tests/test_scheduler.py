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
    async def test_schedule_interval_run_immediately(self, scheduler: SchedulerService) -> None:
        """Interval task with run_immediately fires within seconds."""
        await scheduler.start()

        fired = asyncio.Event()

        async def callback(**kwargs):
            fired.set()

        scheduler.schedule_interval(
            "immediate_check", callback, minutes=60, run_immediately=True,
        )

        # Should fire almost immediately (within 3 seconds)
        try:
            await asyncio.wait_for(fired.wait(), timeout=3)
        except asyncio.TimeoutError:
            pytest.fail("run_immediately task did not fire within 3 seconds")

        await scheduler.stop()

    def test_misfire_grace_time_configured(self, scheduler: SchedulerService) -> None:
        """Scheduler has a generous misfire_grace_time (not the 1s default)."""
        grace = scheduler._scheduler._job_defaults.get("misfire_grace_time", 1)
        assert grace >= 60, f"misfire_grace_time too low: {grace}s (jobs get silently skipped)"

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

    @pytest.mark.asyncio
    async def test_verify_selftest(self, scheduler: SchedulerService) -> None:
        """Scheduler self-test fires a diagnostic job and confirms it works."""
        await scheduler.start()
        assert await scheduler.verify() is True
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_fix_task_id_preserves_run_count(self, scheduler: SchedulerService) -> None:
        """After _fix_task_id, the wrapper still increments run_count correctly."""
        await scheduler.start()

        fired = asyncio.Event()

        async def callback(**kwargs):
            fired.set()

        scheduler.schedule_interval(
            "trackable", callback, seconds=1, run_immediately=True,
        )
        # Simulate what restore_persisted_tasks does: rename the task ID
        from unittest.mock import MagicMock
        fake_rec = MagicMock()
        fake_rec.id = "db-persisted-id-123"
        fake_rec.name = "trackable"
        fake_rec.run_count = 0
        fake_rec.last_run = None
        scheduler._fix_task_id(fake_rec)

        # The task should now be stored under the new ID
        assert "db-persisted-id-123" in scheduler._tasks

        # Wait for the job to fire
        try:
            await asyncio.wait_for(fired.wait(), timeout=5)
        except asyncio.TimeoutError:
            pytest.fail("Job did not fire after _fix_task_id")

        # Give a moment for the wrapper to update metadata
        await asyncio.sleep(0.1)

        task = scheduler._tasks["db-persisted-id-123"]
        assert task.run_count >= 1, f"run_count should be >=1 but was {task.run_count}"
        assert task.last_run is not None

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_fix_task_id_preserves_next_run_time(self, scheduler: SchedulerService) -> None:
        """_fix_task_id preserves the original next_run_time instead of resetting it."""
        await scheduler.start()

        async def noop(**kwargs):
            pass

        # Schedule with run_immediately=True so next_run_time is ~now
        scheduler.schedule_interval("preserve_nrt", noop, hours=6, run_immediately=True)
        old_key = list(scheduler._tasks.keys())[-1]
        old_job = scheduler._scheduler.get_job(old_key)
        original_nrt = old_job.next_run_time

        from unittest.mock import MagicMock
        fake_rec = MagicMock()
        fake_rec.id = "preserved-nrt-id"
        fake_rec.name = "preserve_nrt"
        fake_rec.run_count = 0
        fake_rec.last_run = None
        scheduler._fix_task_id(fake_rec)

        new_job = scheduler._scheduler.get_job("preserved-nrt-id")
        assert new_job is not None, "Job not found after _fix_task_id"
        # next_run_time should be close to original (not pushed out by 6 hours)
        delta = abs((new_job.next_run_time - original_nrt).total_seconds())
        assert delta < 2, f"next_run_time shifted by {delta}s — should be preserved"

        await scheduler.stop()
