"""Tests for the calendar module."""

from __future__ import annotations

import datetime as dt

import pytest

from koda2.modules.calendar.models import (
    Attendee,
    CalendarEvent,
    CalendarProvider,
    ConflictResult,
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

    def test_conflicts_with_overlapping(self) -> None:
        """Overlapping events are detected as conflicts."""
        e1 = CalendarEvent(
            title="Meeting A",
            start=dt.datetime(2026, 2, 12, 10, 0),
            end=dt.datetime(2026, 2, 12, 11, 0),
        )
        e2 = CalendarEvent(
            title="Meeting B",
            start=dt.datetime(2026, 2, 12, 10, 30),
            end=dt.datetime(2026, 2, 12, 11, 30),
        )
        assert e1.conflicts_with(e2) is True
        assert e2.conflicts_with(e1) is True

    def test_no_conflict_sequential(self) -> None:
        """Sequential events don't conflict."""
        e1 = CalendarEvent(
            title="Meeting A",
            start=dt.datetime(2026, 2, 12, 10, 0),
            end=dt.datetime(2026, 2, 12, 11, 0),
        )
        e2 = CalendarEvent(
            title="Meeting B",
            start=dt.datetime(2026, 2, 12, 11, 0),
            end=dt.datetime(2026, 2, 12, 12, 0),
        )
        assert e1.conflicts_with(e2) is False

    def test_no_conflict_gap(self) -> None:
        """Events with gap between them don't conflict."""
        e1 = CalendarEvent(
            title="Meeting A",
            start=dt.datetime(2026, 2, 12, 10, 0),
            end=dt.datetime(2026, 2, 12, 11, 0),
        )
        e2 = CalendarEvent(
            title="Meeting B",
            start=dt.datetime(2026, 2, 12, 14, 0),
            end=dt.datetime(2026, 2, 12, 15, 0),
        )
        assert e1.conflicts_with(e2) is False

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

    def test_conflict_result(self) -> None:
        """ConflictResult model."""
        result = ConflictResult(has_conflict=True, conflicting_events=[
            CalendarEvent(
                title="Conflict",
                start=dt.datetime(2026, 2, 12, 10, 0),
                end=dt.datetime(2026, 2, 12, 11, 0),
            )
        ])
        assert result.has_conflict is True
        assert len(result.conflicting_events) == 1
