"""Agent models for task planning and execution tracking."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Optional


class AgentStatus(StrEnum):
    """Status of an agent task."""
    PENDING = "pending"           # Waiting to start
    PLANNING = "planning"         # Creating execution plan
    RUNNING = "running"           # Executing steps
    WAITING = "waiting"           # Waiting for user input/clarification
    PAUSED = "paused"             # Paused by user
    COMPLETED = "completed"       # All steps done
    FAILED = "failed"             # Failed with error
    CANCELLED = "cancelled"       # Cancelled by user


class StepStatus(StrEnum):
    """Status of an individual step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentStep:
    """A single step in an agent task plan."""
    id: str
    description: str
    action: dict[str, Any]  # The action to execute
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[dt.datetime] = None
    completed_at: Optional[dt.datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status.value,
            "action": self.action,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "retry_count": self.retry_count,
        }


@dataclass
class AgentTask:
    """A complete agent task with plan and execution state."""
    id: str
    user_id: str
    original_request: str
    status: AgentStatus = AgentStatus.PENDING
    plan: list[AgentStep] = field(default_factory=list)
    current_step_index: int = 0
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    started_at: Optional[dt.datetime] = None
    completed_at: Optional[dt.datetime] = None
    result_summary: str = ""
    error_message: Optional[str] = None
    context: dict[str, Any] = field(default_factory=dict)  # Shared context across steps
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "original_request": self.original_request,
            "status": self.status.value,
            "plan": [s.to_dict() for s in self.plan],
            "current_step": self.current_step_index,
            "total_steps": len(self.plan),
            "progress_pct": self._calculate_progress(),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_summary": self.result_summary,
            "error_message": self.error_message,
        }
    
    def _calculate_progress(self) -> int:
        if not self.plan:
            return 0
        completed = sum(1 for s in self.plan if s.status == StepStatus.COMPLETED)
        return int((completed / len(self.plan)) * 100)
    
    def get_current_step(self) -> Optional[AgentStep]:
        if 0 <= self.current_step_index < len(self.plan):
            return self.plan[self.current_step_index]
        return None
    
    def is_complete(self) -> bool:
        return self.status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED)
