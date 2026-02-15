"""Models for proactive alerts and suggestions."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


class AlertType(Enum):
    """Types of proactive alerts."""
    MEETING_SOON = "meeting_soon"  # Meeting starting in X minutes
    PREPARATION_NEEDED = "preparation_needed"  # Suggest prep for meeting
    TRAFFIC_WARNING = "traffic_warning"  # Heavy traffic to next meeting
    WEATHER_WARNING = "weather_warning"  # Weather affecting plans
    FOLLOW_UP_NEEDED = "follow_up_needed"  # Suggest follow-up after meeting
    EMAIL_URGENT = "email_urgent"  # Important unread email
    TASK_DUE = "task_due"  # Task deadline approaching
    BIRTHDAY_REMINDER = "birthday_reminder"  # Contact birthday
    SUGGESTION = "suggestion"  # General helpful suggestion


class AlertPriority(Enum):
    """Priority levels for alerts."""
    CRITICAL = "critical"  # Immediate action needed
    HIGH = "high"  # Important, soon
    MEDIUM = "medium"  # Worth knowing
    LOW = "low"  # FYI


@dataclass
class ProactiveAlert:
    """A proactive alert or suggestion."""
    
    id: str
    type: AlertType
    priority: AlertPriority
    title: str
    message: str
    
    # Context
    related_event_id: Optional[str] = None
    related_contact_id: Optional[str] = None
    related_email_id: Optional[str] = None
    
    # Timing
    created_at: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    valid_until: Optional[dt.datetime] = None
    dismissed_at: Optional[dt.datetime] = None
    
    # Actions the user can take
    suggested_actions: list[dict[str, Any]] = field(default_factory=list)
    # e.g., [{"label": "Send message", "action": "send_whatsapp", "params": {...}}]
    
    # Metadata
    context: dict[str, Any] = field(default_factory=dict)
    
    def is_active(self) -> bool:
        """Check if alert is still active (not dismissed and valid)."""
        if self.dismissed_at:
            return False
        if self.valid_until and dt.datetime.now(dt.UTC) > self.valid_until:
            return False
        return True
    
    def dismiss(self) -> None:
        """Mark alert as dismissed."""
        self.dismissed_at = dt.datetime.now(dt.UTC)


@dataclass
class UserContext:
    """Current context of the user for proactive analysis."""
    
    # Time and location
    current_time: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.UTC))
    timezone: str = "UTC"
    current_location: Optional[str] = None  # Could be "home", "office", or address
    
    # Calendar
    current_meeting: Optional[dict] = None  # Meeting happening now
    next_meeting: Optional[dict] = None  # Next upcoming meeting
    meetings_today: list[dict] = field(default_factory=list)
    
    # Communications
    unread_emails_count: int = 0
    unread_urgent_emails: list[dict] = field(default_factory=list)
    unread_messages_count: int = 0
    
    # Tasks
    pending_tasks: list[dict] = field(default_factory=list)
    overdue_tasks: list[dict] = field(default_factory=list)
    
    # Recent activity
    last_interaction: Optional[dt.datetime] = None
    last_location_change: Optional[dt.datetime] = None
    
    # Preferences (learned)
    usual_commute_time: Optional[int] = None  # minutes
    preferred_prep_time: int = 15  # minutes before meeting
    work_hours: tuple[int, int] = (9, 17)  # start, end
