"""Async task queue service for parallel processing with real-time updates."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from enum import StrEnum
from typing import Any, Callable, Coroutine, Optional

from koda2.logging_config import get_logger

logger = get_logger(__name__)

TaskFunction = Callable[..., Coroutine[Any, Any, Any]]
ProgressCallback = Callable[[str, int, str], Coroutine[Any, Any, None]]


class TaskStatus(StrEnum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Task:
    """Represents a task in the queue."""
    
    def __init__(
        self,
        name: str,
        func: TaskFunction,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        priority: int = 5,
        max_retries: int = 0,
        timeout: Optional[float] = None,
    ):
        self.id = str(uuid.uuid4())
        self.name = name
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self.priority = priority  # 1-10, lower = higher priority
        self.max_retries = max_retries
        self.timeout = timeout
        
        self.status = TaskStatus.PENDING
        self.progress = 0  # 0-100
        self.progress_message = ""
        self.result: Any = None
        self.error: Optional[str] = None
        self.created_at = dt.datetime.now(dt.UTC)
        self.started_at: Optional[dt.datetime] = None
        self.completed_at: Optional[dt.datetime] = None
        self.retry_count = 0
        self.depends_on: list[str] = []  # Task IDs that must complete first
        
    def to_dict(self) -> dict[str, Any]:
        """Serialize task to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "has_result": self.result is not None,
            "error": self.error,
        }
    
    async def update_progress(self, percent: int, message: str = "") -> None:
        """Update task progress."""
        self.progress = min(100, max(0, percent))
        if message:
            self.progress_message = message
        logger.debug("task_progress", task_id=self.id, progress=self.progress, message=message)


class TaskQueueService:
    """Manages parallel task execution with real-time status tracking."""
    
    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers
        self._queue: asyncio.PriorityQueue[tuple[int, dt.datetime, Task]] = asyncio.PriorityQueue()
        self._tasks: dict[str, Task] = {}
        self._running: set[asyncio.Task] = set()
        self._semaphore = asyncio.Semaphore(max_workers)
        self._callbacks: list[Callable[[Task], Coroutine[Any, Any, None]]] = []
        self._shutdown = False
        self._worker_task: Optional[asyncio.Task] = None
        
    async def start(self) -> None:
        """Start the task queue processor."""
        self._shutdown = False
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("task_queue_started", max_workers=self.max_workers)
        
    async def stop(self) -> None:
        """Stop the task queue gracefully."""
        self._shutdown = True
        
        # Cancel all running tasks
        for task in list(self._running):
            task.cancel()
            
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
                
        logger.info("task_queue_stopped")
        
    def register_callback(
        self, 
        callback: Callable[[Task], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for task status changes."""
        self._callbacks.append(callback)
        
    async def _notify_callbacks(self, task: Task) -> None:
        """Notify all registered callbacks of task update."""
        for callback in self._callbacks:
            try:
                await callback(task)
            except Exception as exc:
                logger.error("task_callback_failed", error=str(exc))
                
    async def submit(
        self,
        name: str,
        func: TaskFunction,
        *args: Any,
        priority: int = 5,
        max_retries: int = 0,
        timeout: Optional[float] = None,
        depends_on: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> Task:
        """Submit a new task to the queue."""
        task = Task(
            name=name,
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,
            max_retries=max_retries,
            timeout=timeout,
        )
        if depends_on:
            task.depends_on = depends_on
            
        self._tasks[task.id] = task
        # Priority queue: lower number = higher priority, use timestamp as tiebreaker
        await self._queue.put((priority, dt.datetime.now(dt.UTC), task))
        logger.info("task_submitted", task_id=task.id, name=name, priority=priority)
        await self._notify_callbacks(task)
        return task
        
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        return self._tasks.get(task_id)
        
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or running task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
            
        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            task.status = TaskStatus.CANCELLED
            await self._notify_callbacks(task)
            logger.info("task_cancelled", task_id=task_id)
            return True
        return False
        
    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list[Task]:
        """List tasks, optionally filtered by status."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        # Sort by created_at desc
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]
        
    async def get_active_tasks(self) -> list[Task]:
        """Get currently running or pending tasks."""
        return [
            t for t in self._tasks.values()
            if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
        ]
        
    async def _process_queue(self) -> None:
        """Main queue processing loop."""
        while not self._shutdown:
            try:
                # Wait for an item in the queue
                priority, _, task = await self._queue.get()
                
                if task.status == TaskStatus.CANCELLED:
                    continue
                    
                # Check dependencies
                if task.depends_on:
                    deps_completed = all(
                        self._tasks.get(dep_id) and 
                        self._tasks[dep_id].status == TaskStatus.COMPLETED
                        for dep_id in task.depends_on
                    )
                    if not deps_completed:
                        # Re-queue with same priority
                        await self._queue.put((priority, dt.datetime.now(dt.UTC), task))
                        await asyncio.sleep(1)
                        continue
                
                # Execute with semaphore to limit concurrency
                async with self._semaphore:
                    if task.status != TaskStatus.CANCELLED:
                        await self._execute_task(task)
                        
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("queue_processing_error", error=str(exc))
                await asyncio.sleep(1)
                
    async def _execute_task(self, task: Task) -> None:
        """Execute a single task."""
        task.status = TaskStatus.RUNNING
        task.started_at = dt.datetime.now(dt.UTC)
        await self._notify_callbacks(task)
        
        try:
            # Inject progress callback into kwargs if function accepts it
            if 'progress_callback' in task.func.__code__.co_varnames:
                task.kwargs['progress_callback'] = task.update_progress
                
            # Execute with timeout if specified
            if task.timeout:
                task.result = await asyncio.wait_for(
                    task.func(*task.args, **task.kwargs),
                    timeout=task.timeout
                )
            else:
                task.result = await task.func(*task.args, **task.kwargs)
                
            task.progress = 100
            task.progress_message = "Completed"
            task.status = TaskStatus.COMPLETED
            logger.info("task_completed", task_id=task.id, name=task.name)
            
        except asyncio.TimeoutError:
            task.status = TaskStatus.FAILED
            task.error = f"Timeout after {task.timeout}s"
            await self._maybe_retry(task)
            
        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            logger.error("task_failed", task_id=task.id, error=str(exc))
            await self._maybe_retry(task)
            
        finally:
            task.completed_at = dt.datetime.now(dt.UTC)
            await self._notify_callbacks(task)
            
    async def _maybe_retry(self, task: Task) -> None:
        """Retry a failed task if retries remain."""
        if task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.PENDING
            task.error = None
            await self._queue.put((task.priority, dt.datetime.now(dt.UTC), task))
            logger.info("task_retrying", task_id=task.id, attempt=task.retry_count)
        else:
            logger.error("task_failed_permanently", task_id=task.id, retries=task.retry_count)
            
    async def wait_for_task(self, task_id: str, timeout: Optional[float] = None) -> Task:
        """Wait for a task to complete."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")
            
        start = dt.datetime.now(dt.UTC)
        while task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            await asyncio.sleep(0.1)
            if timeout and (dt.datetime.now(dt.UTC) - start).total_seconds() > timeout:
                raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")
                
        return task
