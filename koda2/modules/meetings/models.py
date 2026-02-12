"""Meeting and action item data models."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field


class MeetingStatus(StrEnum):
    """Meeting status."""
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ActionItemStatus(StrEnum):
    """Action item status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class Attendee(BaseModel):
    """Meeting attendee."""
    name: str
    email: Optional[str] = None
    role: str = "participant"  # organizer, participant, optional
    attended: bool = False


class ActionItem(BaseModel):
    """Action item from a meeting."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    description: str
    assignee: str
    assignee_email: Optional[str] = None
    due_date: Optional[dt.date] = None
    status: ActionItemStatus = ActionItemStatus.PENDING
    priority: str = "medium"  # low, medium, high, critical
    meeting_id: Optional[str] = None
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    completed_at: Optional[dt.datetime] = None
    notes: str = ""
    
    def mark_completed(self) -> None:
        """Mark action item as completed."""
        self.status = ActionItemStatus.COMPLETED
        self.completed_at = dt.datetime.now(dt.UTC)
        
    def check_overdue(self) -> bool:
        """Check if action item is overdue."""
        if self.status == ActionItemStatus.COMPLETED:
            return False
        if self.due_date and dt.date.today() > self.due_date:
            self.status = ActionItemStatus.OVERDUE
            return True
        return False


class MeetingSegment(BaseModel):
    """A segment of a meeting (topic)."""
    start_time: dt.datetime
    end_time: Optional[dt.datetime] = None
    topic: str
    summary: str = ""
    speaker: Optional[str] = None
    transcript: str = ""


class Meeting(BaseModel):
    """Meeting with transcription and minutes."""
    id: str = Field(default_factory=lambda: str(id(dt.datetime.now())))
    title: str
    description: str = ""
    scheduled_start: dt.datetime
    scheduled_end: dt.datetime
    actual_start: Optional[dt.datetime] = None
    actual_end: Optional[dt.datetime] = None
    location: str = ""  # Can be physical or video link
    meeting_link: Optional[str] = None  # Zoom, Teams, etc.
    organizer: str
    attendees: list[Attendee] = Field(default_factory=list)
    status: MeetingStatus = MeetingStatus.SCHEDULED
    
    # Content
    transcript: str = ""  # Full transcript
    segments: list[MeetingSegment] = Field(default_factory=list)
    summary: str = ""  # AI-generated summary
    action_items: list[ActionItem] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    
    # Files
    audio_file_path: Optional[str] = None
    minutes_pdf_path: Optional[str] = None
    
    # Metadata
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    updated_at: Optional[dt.datetime] = None
    
    def start_meeting(self) -> None:
        """Mark meeting as started."""
        self.status = MeetingStatus.IN_PROGRESS
        self.actual_start = dt.datetime.now(dt.UTC)
        self.updated_at = dt.datetime.now(dt.UTC)
        
    def end_meeting(self) -> None:
        """Mark meeting as completed."""
        self.status = MeetingStatus.COMPLETED
        self.actual_end = dt.datetime.now(dt.UTC)
        self.updated_at = dt.datetime.now(dt.UTC)
        
    def add_action_item(
        self,
        description: str,
        assignee: str,
        due_date: Optional[dt.date] = None,
        priority: str = "medium",
    ) -> ActionItem:
        """Add an action item to the meeting."""
        item = ActionItem(
            description=description,
            assignee=assignee,
            due_date=due_date,
            priority=priority,
            meeting_id=self.id,
        )
        self.action_items.append(item)
        self.updated_at = dt.datetime.now(dt.UTC)
        return item
        
    def get_pending_actions(self) -> list[ActionItem]:
        """Get all pending action items."""
        return [a for a in self.action_items if a.status != ActionItemStatus.COMPLETED]
        
    def get_overdue_actions(self) -> list[ActionItem]:
        """Get overdue action items."""
        overdue = []
        for item in self.action_items:
            if item.check_overdue():
                overdue.append(item)
        return overdue
