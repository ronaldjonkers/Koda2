"""Improvement Queue — persistent, chronological queue for self-development tasks.

Supports multiple concurrent worker agents:
- LLM planning runs in parallel across workers (IO-bound, safe)
- Git/file/test operations are serialized via a shared lock (not concurrent-safe)

Items can be added by:
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
DEFAULT_MAX_WORKERS = 1


class QueueItemStatus(StrEnum):
    """Status of a queued improvement item."""

    PENDING = "pending"
    PLANNING = "planning"
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
    """Persistent queue with multiple concurrent workers.

    Architecture:
        ┌──────────────────────────────────────────────┐
        │  Worker 1: plan (LLM) ──┐                    │
        │  Worker 2: plan (LLM) ──┼─► git_lock ──► apply/test/commit
        │  Worker 3: plan (LLM) ──┘   (1 at a time)   │
        └──────────────────────────────────────────────┘
    """

    def __init__(self, max_workers: int = DEFAULT_MAX_WORKERS) -> None:
        self._items: list[dict[str, Any]] = []
        self._running = False
        self._max_workers = max(1, max_workers)
        self._worker_tasks: list[asyncio.Task] = []
        self._pick_lock = asyncio.Lock()
        self._git_lock = asyncio.Lock()
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    # ── Persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        """Load queue from disk."""
        if QUEUE_FILE.exists():
            try:
                self._items = json.loads(QUEUE_FILE.read_text())
                # Reset any stuck items back to pending on load
                for item in self._items:
                    if item.get("status") in (QueueItemStatus.IN_PROGRESS, QueueItemStatus.PLANNING):
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

    def retry_item(self, item_id: str) -> bool:
        """Reset a failed/skipped item back to pending so it can be retried."""
        for item in self._items:
            if item["id"] == item_id and item.get("status") in (
                QueueItemStatus.FAILED, QueueItemStatus.SKIPPED,
            ):
                item["status"] = QueueItemStatus.PENDING
                item["result_message"] = ""
                item.pop("error_details", None)
                item.pop("plan_summary", None)
                item.pop("finished_at", None)
                self._save()
                logger.info("queue_item_retried", item_id=item_id)
                return True
        return False

    def purge_finished(self) -> int:
        """Remove all completed, failed, and skipped items from the queue.

        Returns the number of items removed.
        """
        before = len(self._items)
        self._items = [
            i for i in self._items
            if i.get("status") not in (
                QueueItemStatus.COMPLETED,
                QueueItemStatus.FAILED,
                QueueItemStatus.SKIPPED,
            )
        ]
        removed = before - len(self._items)
        if removed:
            self._save()
            logger.info("queue_purged", removed=removed, remaining=len(self._items))
        return removed

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
            "planning": counts.get(QueueItemStatus.PLANNING, 0),
            "in_progress": counts.get(QueueItemStatus.IN_PROGRESS, 0),
            "completed": counts.get(QueueItemStatus.COMPLETED, 0),
            "failed": counts.get(QueueItemStatus.FAILED, 0),
            "skipped": counts.get(QueueItemStatus.SKIPPED, 0),
            "max_workers": self._max_workers,
            "active_workers": len([t for t in self._worker_tasks if not t.done()]),
        }

    # ── Background Workers ───────────────────────────────────────────

    async def _pick_item(self) -> Optional[dict[str, Any]]:
        """Atomically pick the next pending item and mark it as planning.

        Uses _pick_lock so two workers never grab the same item.
        """
        async with self._pick_lock:
            item = self._next_pending()
            if item:
                item["status"] = QueueItemStatus.PLANNING
                item["started_at"] = dt.datetime.now().isoformat()
                self._save()
            return item

    async def _process_one(self, worker_id: int, item: dict[str, Any]) -> None:
        """Process a single queue item: plan in parallel, apply under git lock.

        Phase 1 — Planning (parallel-safe):
            Call LLM to produce an improvement plan. Multiple workers
            can plan simultaneously.

        Phase 2 — Applying (serialized via git_lock):
            Stash → write files → run tests → commit/push or rollback.
            Only one worker can do this at a time.
        """
        import traceback as _tb
        from koda2.supervisor.safety import SafetyGuard
        from koda2.supervisor.evolution import EvolutionEngine

        item["worker_id"] = worker_id
        item.setdefault("error_details", {})
        logger.info("queue_planning", worker=worker_id, id=item["id"], request=item["request"][:80])

        try:
            safety = SafetyGuard()
            engine = EvolutionEngine(safety)

            # Phase 1: Plan (parallel — no lock needed)
            safety.audit("evolution_start", {"request": item["request"], "worker": worker_id})
            plan = await engine.plan_improvement(item["request"])

            # Store plan details for debugging regardless of outcome
            item["plan_summary"] = plan.get("summary", "")[:500]
            item["plan_risk"] = plan.get("risk", "unknown")
            item["plan_changes"] = [
                {"action": c.get("action"), "file": c.get("file"), "description": c.get("description", "")[:200]}
                for c in plan.get("changes", [])
            ]

            if not plan.get("changes"):
                item["success"] = False
                item["status"] = QueueItemStatus.FAILED
                item["result_message"] = f"No changes planned. {plan.get('summary', '')}"[:2000]
                item["error_details"] = {
                    "phase": "planning",
                    "reason": "no_changes",
                    "plan_response": plan.get("summary", ""),
                }
                item["finished_at"] = dt.datetime.now().isoformat()
                self._save()
                return

            if plan.get("risk") == "high":
                item["success"] = False
                item["status"] = QueueItemStatus.FAILED
                item["result_message"] = f"High-risk — needs manual review. {plan['summary']}"[:2000]
                item["error_details"] = {
                    "phase": "planning",
                    "reason": "high_risk",
                    "plan_summary": plan["summary"],
                }
                item["finished_at"] = dt.datetime.now().isoformat()
                self._save()
                return

            # Phase 2: Apply (serialized — acquire git lock)
            item["status"] = QueueItemStatus.IN_PROGRESS
            self._save()
            logger.info("queue_applying", worker=worker_id, id=item["id"], summary=plan["summary"][:80])

            async with self._git_lock:
                success, message = await engine.apply_plan(plan)

            item["success"] = success
            item["status"] = QueueItemStatus.COMPLETED if success else QueueItemStatus.FAILED
            item["result_message"] = message[:2000]
            if not success:
                item["error_details"] = {
                    "phase": "apply",
                    "reason": "tests_or_apply_failed",
                    "full_output": message[:4000],
                    "plan_summary": plan.get("summary", ""),
                    "files_touched": [c.get("file", "") for c in plan.get("changes", [])],
                }

        except Exception as exc:
            item["success"] = False
            item["status"] = QueueItemStatus.FAILED
            item["result_message"] = f"Error: {exc}"[:2000]
            item["error_details"] = {
                "phase": "exception",
                "reason": type(exc).__name__,
                "message": str(exc),
                "traceback": _tb.format_exc()[:4000],
            }
            logger.error("queue_item_error", worker=worker_id, id=item["id"], error=str(exc))

        item["finished_at"] = dt.datetime.now().isoformat()
        self._save()
        logger.info("queue_item_done", worker=worker_id, id=item["id"], success=item["success"])

    async def _worker_loop(self, worker_id: int) -> None:
        """Background worker loop. Multiple instances run concurrently."""
        logger.info("queue_worker_started", worker=worker_id)
        while self._running:
            try:
                item = await self._pick_item()

                if item:
                    await self._process_one(worker_id, item)
                    await asyncio.sleep(2)
                else:
                    # No pending items — poll every 15 seconds
                    await asyncio.sleep(15)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("queue_worker_error", worker=worker_id, error=str(exc))
                await asyncio.sleep(15)

        logger.info("queue_worker_stopped", worker=worker_id)

    def start_worker(self) -> None:
        """Start the background worker pool."""
        if self._running:
            return
        self._running = True
        # Clean up any old done tasks
        self._worker_tasks = [t for t in self._worker_tasks if not t.done()]
        # Spawn workers up to max
        for i in range(self._max_workers):
            task = asyncio.create_task(self._worker_loop(i + 1))
            self._worker_tasks.append(task)
        logger.info("queue_workers_started", count=self._max_workers)

    def stop_worker(self) -> None:
        """Stop all background workers."""
        self._running = False
        for task in self._worker_tasks:
            if not task.done():
                task.cancel()
        self._worker_tasks.clear()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @max_workers.setter
    def max_workers(self, value: int) -> None:
        self._max_workers = max(1, value)

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
