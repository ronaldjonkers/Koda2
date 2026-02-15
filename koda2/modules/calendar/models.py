"""Data models for calendar events and providers."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class CalendarProvider(StrEnum):
    """Supported calendar backends."""

    EWS = "ews"
    GOOGLE = "google"
    MSGRAPH = "msgraph"
    CALDAV = "caldav"


class Attendee(BaseModel):
    """Meeting attendee."""

    name: str = ""
    email: str
    status: str = "pending"


class CalendarEvent(BaseModel):
    """Unified calendar event model across all providers."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    provider: Optional[CalendarProvider] = None
    provider_id: str = ""
    title: str
    description: str = ""
    location: str = ""
    start: dt.datetime
    end: dt.datetime
    all_day: bool = False
    attendees: list[Attendee] = Field(default_factory=list)
    organizer: str = ""
    recurrence: Optional[str] = None
    reminders: list[int] = Field(default_factory=lambda: [15])
    calendar_name: str = ""
    is_online: bool = False
    meeting_url: str = ""
    status: str = "confirmed"
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))
    updated_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.UTC))

    @property
    def duration_minutes(self) -> int:
        """Event duration in minutes."""
        return int((self.end - self.start).total_seconds() / 60)

class PrepTimeResult(BaseModel):
    """Preparation time calculation between events."""

    event_before: Optional[CalendarEvent] = None
    event_after: CalendarEvent
    available_minutes: int = 0
    suggested_prep_minutes: int = 15
    travel_time_needed: bool = False
