"""Tests for the calendar module."""

from __future__ import annotations

import datetime as dt

import pytest

from koda2.modules.calendar.models import (
    Attendee,
    CalendarEvent,
    CalendarProvider,
)


class TestCalendarEvent:
    """Tests for the CalendarEvent model."""

    def test_duration_minutes(self) -> None:
        """Duration calculation is correct."""
        event = CalendarEvent(
            title="Test",
            start=dt.datetime(2026, 2, 12, 10, 0),
            end=dt.datetime(2026, 2, 12, 11, 30),
        )
        assert event.duration_minutes == 90

    def test_attendee_model(self) -> None:
        """Attendee model has proper defaults."""
        att = Attendee(email="john@example.com")
        assert att.email == "john@example.com"
        assert att.name == ""
        assert att.status == "pending"

    def test_event_with_attendees(self) -> None:
        """Event can hold multiple attendees."""
        event = CalendarEvent(
            title="Team Standup",
            start=dt.datetime(2026, 2, 12, 9, 0),
            end=dt.datetime(2026, 2, 12, 9, 15),
            attendees=[
                Attendee(email="a@test.com", name="Alice"),
                Attendee(email="b@test.com", name="Bob"),
            ],
        )
        assert len(event.attendees) == 2

