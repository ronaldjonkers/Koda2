"""Tests for the Improvement Queue system."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from koda2.supervisor.improvement_queue import (
    ImprovementQueue,
    QueueItemStatus,
    QueueItemSource,
    get_improvement_queue,
)


class TestImprovementQueue:
    """Tests for the ImprovementQueue class."""

    def _make_queue(self, tmp_path: Path) -> ImprovementQueue:
        """Create a queue with a temp file for persistence."""
        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", tmp_path), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", tmp_path / "queue.json"):
            return ImprovementQueue()

    def test_add_item(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("Add weather command", source="user")
        assert item["id"]
        assert item["request"] == "Add weather command"
        assert item["source"] == "user"
        assert item["status"] == QueueItemStatus.PENDING
        assert item["priority"] == 5

    def test_add_item_with_priority(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("Fix bug", source="supervisor", priority=1)
        assert item["priority"] == 1
        assert item["source"] == "supervisor"

    def test_add_item_with_metadata(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("Cleanup", metadata={"type": "hygiene"})
        assert item["metadata"]["type"] == "hygiene"

    def test_list_items(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        queue.add("Item 1")
        queue.add("Item 2")
        queue.add("Item 3")
        items = queue.list_items()
        assert len(items) == 3

    def test_list_items_filter_status(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        queue.add("Item 1")
        item2 = queue.add("Item 2")
        item2["status"] = QueueItemStatus.COMPLETED
        items = queue.list_items(status="pending")
        assert len(items) == 1
        assert items[0]["request"] == "Item 1"

    def test_get_item(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("Find me")
        found = queue.get_item(item["id"])
        assert found is not None
        assert found["request"] == "Find me"

    def test_get_item_not_found(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        assert queue.get_item("nonexistent") is None

    def test_cancel_item(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("Cancel me")
        assert queue.cancel_item(item["id"])
        found = queue.get_item(item["id"])
        assert found["status"] == QueueItemStatus.SKIPPED
        assert found["result_message"] == "Cancelled by user"

    def test_cancel_non_pending_fails(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("In progress")
        item["status"] = QueueItemStatus.IN_PROGRESS
        assert not queue.cancel_item(item["id"])

    def test_pending_count(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        queue.add("One")
        queue.add("Two")
        item3 = queue.add("Three")
        item3["status"] = QueueItemStatus.COMPLETED
        assert queue.pending_count() == 2

    def test_next_pending_priority_order(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        queue.add("Low priority", priority=10)
        queue.add("High priority", priority=1)
        queue.add("Medium priority", priority=5)
        nxt = queue._next_pending()
        assert nxt is not None
        assert nxt["request"] == "High priority"

    def test_next_pending_none_when_empty(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        assert queue._next_pending() is None

    def test_stats(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        queue.add("Pending 1")
        item2 = queue.add("Completed")
        item2["status"] = QueueItemStatus.COMPLETED
        item3 = queue.add("Failed")
        item3["status"] = QueueItemStatus.FAILED
        stats = queue.stats()
        assert stats["total"] == 3
        assert stats["pending"] == 1
        assert stats["completed"] == 1
        assert stats["failed"] == 1

    def test_persistence_save_and_load(self, tmp_path: Path) -> None:
        queue_file = tmp_path / "queue.json"
        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", tmp_path), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", queue_file):
            q1 = ImprovementQueue()
            q1.add("Persisted item", priority=3)
            q1.add("Another item")

            # Load in a new instance
            q2 = ImprovementQueue()
            assert len(q2.list_items()) == 2
            assert q2.list_items()[0]["request"] == "Persisted item"

    def test_load_resets_in_progress_to_pending(self, tmp_path: Path) -> None:
        queue_file = tmp_path / "queue.json"
        items = [{"id": "abc", "request": "stuck", "status": "in_progress",
                  "source": "user", "priority": 5, "created_at": "2025-01-01",
                  "started_at": None, "finished_at": None, "result_message": None,
                  "success": None, "metadata": {}}]
        queue_file.write_text(json.dumps(items))

        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", tmp_path), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", queue_file):
            q = ImprovementQueue()
            assert q.get_item("abc")["status"] == QueueItemStatus.PENDING

    def test_load_resets_planning_to_pending(self, tmp_path: Path) -> None:
        queue_file = tmp_path / "queue.json"
        items = [{"id": "def", "request": "stuck planning", "status": "planning",
                  "source": "user", "priority": 5, "created_at": "2025-01-01",
                  "started_at": None, "finished_at": None, "result_message": None,
                  "success": None, "metadata": {}}]
        queue_file.write_text(json.dumps(items))

        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", tmp_path), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", queue_file):
            q = ImprovementQueue()
            assert q.get_item("def")["status"] == QueueItemStatus.PENDING

    def test_prune_old(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("Old item")
        item["status"] = QueueItemStatus.COMPLETED
        item["finished_at"] = "2020-01-01T00:00:00"
        queue._save()
        removed = queue.prune_old(keep_days=30)
        assert removed == 1
        assert len(queue.list_items()) == 0

    def test_prune_keeps_recent(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("Recent item")
        item["status"] = QueueItemStatus.COMPLETED
        item["finished_at"] = "2099-01-01T00:00:00"
        queue._save()
        removed = queue.prune_old(keep_days=30)
        assert removed == 0
        assert len(queue.list_items()) == 1

    def test_worker_not_running_initially(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        assert not queue.is_running

    def test_stop_worker_idempotent(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        queue.stop_worker()
        assert not queue.is_running

    def test_default_max_workers(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        assert queue.max_workers == 1

    def test_custom_max_workers(self, tmp_path: Path) -> None:
        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", tmp_path), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", tmp_path / "queue.json"):
            queue = ImprovementQueue(max_workers=5)
            assert queue.max_workers == 5

    def test_max_workers_minimum_one(self, tmp_path: Path) -> None:
        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", tmp_path), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", tmp_path / "queue.json"):
            queue = ImprovementQueue(max_workers=0)
            assert queue.max_workers == 1

    def test_max_workers_setter(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        queue.max_workers = 7
        assert queue.max_workers == 7
        queue.max_workers = 0
        assert queue.max_workers == 1

    def test_stats_includes_worker_info(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        stats = queue.stats()
        assert "max_workers" in stats
        assert "active_workers" in stats
        assert stats["max_workers"] == 1
        assert stats["active_workers"] == 0

    def test_stats_includes_planning(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = queue.add("Planning item")
        item["status"] = QueueItemStatus.PLANNING
        stats = queue.stats()
        assert stats["planning"] == 1

    @pytest.mark.asyncio
    async def test_pick_item_marks_as_planning(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        queue.add("Pick me")
        item = await queue._pick_item()
        assert item is not None
        assert item["status"] == QueueItemStatus.PLANNING
        assert item["started_at"] is not None

    @pytest.mark.asyncio
    async def test_pick_item_returns_none_when_empty(self, tmp_path: Path) -> None:
        queue = self._make_queue(tmp_path)
        item = await queue._pick_item()
        assert item is None

    @pytest.mark.asyncio
    async def test_pick_item_no_double_pick(self, tmp_path: Path) -> None:
        """Two concurrent picks should return different items."""
        queue = self._make_queue(tmp_path)
        queue.add("Item A")
        queue.add("Item B")
        item1 = await queue._pick_item()
        item2 = await queue._pick_item()
        assert item1 is not None
        assert item2 is not None
        assert item1["id"] != item2["id"]


class TestGetImprovementQueue:
    """Tests for the singleton accessor."""

    def test_returns_same_instance(self) -> None:
        with patch("koda2.supervisor.improvement_queue._queue_instance", None):
            q1 = get_improvement_queue()
            q2 = get_improvement_queue()
            assert q1 is q2


class TestQueueItemEnums:
    """Tests for enum values."""

    def test_status_values(self) -> None:
        assert QueueItemStatus.PENDING == "pending"
        assert QueueItemStatus.PLANNING == "planning"
        assert QueueItemStatus.IN_PROGRESS == "in_progress"
        assert QueueItemStatus.COMPLETED == "completed"
        assert QueueItemStatus.FAILED == "failed"
        assert QueueItemStatus.SKIPPED == "skipped"

    def test_source_values(self) -> None:
        assert QueueItemSource.USER == "user"
        assert QueueItemSource.LEARNER == "learner"
        assert QueueItemSource.SUPERVISOR == "supervisor"
        assert QueueItemSource.SYSTEM == "system"
