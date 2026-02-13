"""Improvement Queue — persistent, chronological queue for self-improvement tasks.

Stores improvement requests in a JSON file and processes them one-by-one
in a background asyncio task. Items can be added by:
- Users via the dashboard ("Request Self-Improvement")
- The ContinuousLearner (auto-detected observations)
- The supervisor (error patterns, recurring crashes)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any, Optional

from koda2.logging_config import get_logger

logger = get_logger(__name__)

QUEUE_DIR = Path("data/supervisor")
QUEUE_FILE = QUEUE_DIR / "improvement_queue.json"


class QueueItemStatus(StrEnum):
    """Status of a queued improvement item."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class QueueItemSource(StrEnum):
    """Where the improvement request originated."""

    USER = "user"
    LEARNER = "learner"
    SUPERVISOR = "supervisor"
    SYSTEM = "system"


class ImprovementQueue:
    """Persistent, chronological improvement queue with background processing."""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    # ── Persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        """Load queue from disk."""
        if QUEUE_FILE.exists():
            try:
                self._items = json.loads(QUEUE_FILE.read_text())
                # Reset any stuck in_progress items back to pending
                for item in self._items:
                    if item.get("status") == QueueItemStatus.IN_PROGRESS:
                        item["status"] = QueueItemStatus.PENDING
            except Exception as exc:
                logger.error("queue_load_failed", error=str(exc))
                self._items = []

    def _save(self) -> None:
        """Persist queue to disk."""
        try:
            QUEUE_FILE.write_text(json.dumps(self._items, indent=2, ensure_ascii=False))
        except Exception as exc:
            logger.error("queue_save_failed", error=str(exc))

    # ── Public API ───────────────────────────────────────────────────

    def add(
        self,
        request: str,
        source: str = QueueItemSource.USER,
        priority: int = 5,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Add an improvement request to the queue.

        Args:
            request: Description of the improvement to make.
            source: Where the request came from (user, learner, supervisor, system).
            priority: 1 (highest) to 10 (lowest). Lower = processed first.
            metadata: Optional extra context.

        Returns:
            The created queue item dict.
        """
        item = {
            "id": uuid.uuid4().hex[:12],
            "request": request,
            "source": source,
            "priority": priority,
            "status": QueueItemStatus.PENDING,
            "created_at": dt.datetime.now().isoformat(),
            "started_at": None,
            "finished_at": None,
            "result_message": None,
            "success": None,
            "metadata": metadata or {},
        }
        self._items.append(item)
        self._save()
        logger.info("queue_item_added", id=item["id"], source=source, request=request[:100])
        return item

    def list_items(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List queue items, optionally filtered by status."""
        items = self._items
        if status:
            items = [i for i in items if i.get("status") == status]
        return items[-limit:]

    def get_item(self, item_id: str) -> Optional[dict[str, Any]]:
        """Get a single queue item by ID."""
        for item in self._items:
            if item["id"] == item_id:
                return item
        return None

    def cancel_item(self, item_id: str) -> bool:
        """Cancel a pending item."""
        for item in self._items:
            if item["id"] == item_id and item["status"] == QueueItemStatus.PENDING:
                item["status"] = QueueItemStatus.SKIPPED
                item["result_message"] = "Cancelled by user"
                item["finished_at"] = dt.datetime.now().isoformat()
                self._save()
                return True
        return False

    def pending_count(self) -> int:
        """Number of items waiting to be processed."""
        return sum(1 for i in self._items if i["status"] == QueueItemStatus.PENDING)

    def _next_pending(self) -> Optional[dict[str, Any]]:
        """Get the next item to process (lowest priority number first, then oldest)."""
        pending = [i for i in self._items if i["status"] == QueueItemStatus.PENDING]
        if not pending:
            return None
        pending.sort(key=lambda i: (i.get("priority", 5), i.get("created_at", "")))
        return pending[0]

    def stats(self) -> dict[str, Any]:
        """Queue statistics."""
        counts: dict[str, int] = {}
        for item in self._items:
            s = item.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
        return {
            "total": len(self._items),
            "pending": counts.get(QueueItemStatus.PENDING, 0),
            "in_progress": counts.get(QueueItemStatus.IN_PROGRESS, 0),
            "completed": counts.get(QueueItemStatus.COMPLETED, 0),
            "failed": counts.get(QueueItemStatus.FAILED, 0),
            "skipped": counts.get(QueueItemStatus.SKIPPED, 0),
        }

    # ── Background Worker ────────────────────────────────────────────

    async def _process_one(self, item: dict[str, Any]) -> None:
        """Process a single queue item through the EvolutionEngine."""
        from koda2.supervisor.safety import SafetyGuard
        from koda2.supervisor.evolution import EvolutionEngine

        item["status"] = QueueItemStatus.IN_PROGRESS
        item["started_at"] = dt.datetime.now().isoformat()
        self._save()

        logger.info("queue_processing", id=item["id"], request=item["request"][:100])

        try:
            safety = SafetyGuard()
            engine = EvolutionEngine(safety)
            success, message = await engine.implement_improvement(item["request"])

            item["success"] = success
            item["status"] = QueueItemStatus.COMPLETED if success else QueueItemStatus.FAILED
            item["result_message"] = message[:500]
        except Exception as exc:
            item["success"] = False
            item["status"] = QueueItemStatus.FAILED
            item["result_message"] = f"Error: {exc}"[:500]
            logger.error("queue_item_error", id=item["id"], error=str(exc))

        item["finished_at"] = dt.datetime.now().isoformat()
        self._save()
        logger.info(
            "queue_item_done",
            id=item["id"],
            success=item["success"],
            status=item["status"],
        )

    async def _worker_loop(self) -> None:
        """Background worker that processes the queue chronologically."""
        logger.info("improvement_queue_worker_started")
        while self._running:
            try:
                async with self._lock:
                    item = self._next_pending()

                if item:
                    await self._process_one(item)
                    # Small pause between items to avoid overload
                    await asyncio.sleep(5)
                else:
                    # No pending items — poll every 30 seconds
                    await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("queue_worker_error", error=str(exc))
                await asyncio.sleep(30)

        logger.info("improvement_queue_worker_stopped")

    def start_worker(self) -> None:
        """Start the background worker task."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())

    def stop_worker(self) -> None:
        """Stop the background worker."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()

    @property
    def is_running(self) -> bool:
        return self._running

    # ── Cleanup ──────────────────────────────────────────────────────

    def prune_old(self, keep_days: int = 30) -> int:
        """Remove completed/failed/skipped items older than keep_days."""
        cutoff = (dt.datetime.now() - dt.timedelta(days=keep_days)).isoformat()
        terminal = {QueueItemStatus.COMPLETED, QueueItemStatus.FAILED, QueueItemStatus.SKIPPED}
        before = len(self._items)
        self._items = [
            i for i in self._items
            if i["status"] not in terminal or (i.get("finished_at") or "") > cutoff
        ]
        removed = before - len(self._items)
        if removed:
            self._save()
        return removed


# ── Singleton ────────────────────────────────────────────────────────

_queue_instance: Optional[ImprovementQueue] = None


def get_improvement_queue() -> ImprovementQueue:
    """Get or create the singleton ImprovementQueue instance."""
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = ImprovementQueue()
    return _queue_instance
