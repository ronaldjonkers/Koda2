"""Tests for the calendar service (conflict detection, prep time, unified interface)."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.calendar.models import Attendee, CalendarEvent, CalendarProvider
from koda2.modules.calendar.service import CalendarService


@pytest.fixture
def mock_google_provider():
    """Create a mock Google Calendar provider."""
    provider = MagicMock()
    provider.provider = CalendarProvider.GOOGLE
    provider.is_configured.return_value = True
    provider.list_events = AsyncMock(return_value=[])
    provider.create_event = AsyncMock()
    provider.update_event = AsyncMock()
    provider.delete_event = AsyncMock(return_value=True)
    provider.list_calendars = AsyncMock(return_value=["primary", "work"])
    return provider


@pytest.fixture
def calendar_service(mock_google_provider):
    """Create a CalendarService with a mocked provider."""
    with patch("koda2.modules.calendar.service.EWSCalendarProvider") as ews, \
         patch("koda2.modules.calendar.service.GoogleCalendarProvider") as google, \
         patch("koda2.modules.calendar.service.MSGraphCalendarProvider") as graph, \
         patch("koda2.modules.calendar.service.CalDAVCalendarProvider") as caldav:

        ews.return_value.is_configured.return_value = False
        google.return_value = mock_google_provider
        graph.return_value.is_configured.return_value = False
        caldav.return_value.is_configured.return_value = False

        service = CalendarService()
        return service


class TestCalendarService:
    """Tests for the unified calendar service."""

    def test_active_providers(self, calendar_service) -> None:
        """Active providers list only configured providers."""
        assert CalendarProvider.GOOGLE in calendar_service.active_providers

    @pytest.mark.asyncio
    async def test_list_all_calendars(self, calendar_service) -> None:
        """list_all_calendars returns calendars from all providers."""
        result = await calendar_service.list_all_calendars()
        assert CalendarProvider.GOOGLE in result
        assert "primary" in result[CalendarProvider.GOOGLE]

    @pytest.mark.asyncio
    async def test_list_events(self, calendar_service) -> None:
        """list_events returns sorted events."""
        now = dt.datetime(2026, 2, 12, 10, 0)
        events = [
            CalendarEvent(title="B", start=now + dt.timedelta(hours=2), end=now + dt.timedelta(hours=3)),
            CalendarEvent(title="A", start=now, end=now + dt.timedelta(hours=1)),
        ]
        calendar_service._providers[CalendarProvider.GOOGLE].list_events = AsyncMock(return_value=events)

        result = await calendar_service.list_events(now, now + dt.timedelta(days=1))
        assert len(result) == 2
        assert result[0].title == "A"
        assert result[1].title == "B"

    @pytest.mark.asyncio
    async def test_list_events_provider_error(self, calendar_service) -> None:
        """Provider errors are caught and logged."""
        calendar_service._providers[CalendarProvider.GOOGLE].list_events = AsyncMock(
            side_effect=Exception("API error")
        )
        result = await calendar_service.list_events(
            dt.datetime(2026, 2, 12), dt.datetime(2026, 2, 13)
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_create_event(self, calendar_service, mock_google_provider) -> None:
        """create_event delegates to the right provider."""
        event = CalendarEvent(
            title="Test Meeting",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        mock_google_provider.create_event = AsyncMock(return_value=event)

        result = await calendar_service.create_event(event, CalendarProvider.GOOGLE)
        mock_google_provider.create_event.assert_called_once_with(event)
        assert result.title == "Test Meeting"

    @pytest.mark.asyncio
    async def test_create_event_no_provider(self, calendar_service) -> None:
        """create_event raises when provider is unavailable."""
        event = CalendarEvent(
            title="Test",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        with pytest.raises(ValueError, match="No calendar provider"):
            await calendar_service.create_event(event, CalendarProvider.EWS)

    @pytest.mark.asyncio
    async def test_detect_conflicts_none(self, calendar_service) -> None:
        """No conflicts when calendar is empty."""
        calendar_service._providers[CalendarProvider.GOOGLE].list_events = AsyncMock(return_value=[])

        proposed = CalendarEvent(
            title="New Meeting",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        result = await calendar_service.detect_conflicts(proposed)
        assert result.has_conflict is False

    @pytest.mark.asyncio
    async def test_detect_conflicts_found(self, calendar_service) -> None:
        """Conflicts detected when events overlap."""
        existing = CalendarEvent(
            title="Existing",
            start=dt.datetime(2026, 2, 15, 10, 30),
            end=dt.datetime(2026, 2, 15, 11, 30),
        )
        calendar_service._providers[CalendarProvider.GOOGLE].list_events = AsyncMock(return_value=[existing])

        proposed = CalendarEvent(
            title="New Meeting",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        result = await calendar_service.detect_conflicts(proposed)
        assert result.has_conflict is True
        assert len(result.conflicting_events) == 1

    @pytest.mark.asyncio
    async def test_calculate_prep_time_no_prior(self, calendar_service) -> None:
        """Prep time calculation with no prior events."""
        calendar_service._providers[CalendarProvider.GOOGLE].list_events = AsyncMock(return_value=[])

        event = CalendarEvent(
            title="Meeting",
            start=dt.datetime(2026, 2, 15, 14, 0),
            end=dt.datetime(2026, 2, 15, 15, 0),
        )
        result = await calendar_service.calculate_prep_time(event, 15)
        assert result.available_minutes == 240
        assert result.suggested_prep_minutes == 15

    @pytest.mark.asyncio
    async def test_calculate_prep_time_with_prior(self, calendar_service) -> None:
        """Prep time calculation with a prior event."""
        prior = CalendarEvent(
            title="Earlier",
            start=dt.datetime(2026, 2, 15, 13, 0),
            end=dt.datetime(2026, 2, 15, 13, 30),
        )
        calendar_service._providers[CalendarProvider.GOOGLE].list_events = AsyncMock(return_value=[prior])

        event = CalendarEvent(
            title="Meeting",
            start=dt.datetime(2026, 2, 15, 14, 0),
            end=dt.datetime(2026, 2, 15, 15, 0),
        )
        result = await calendar_service.calculate_prep_time(event, 15)
        assert result.available_minutes == 30
        assert result.event_before is not None
        assert result.event_before.title == "Earlier"

    @pytest.mark.asyncio
    async def test_calculate_prep_time_travel(self, calendar_service) -> None:
        """Prep time detects travel needed between different locations."""
        prior = CalendarEvent(
            title="Earlier",
            start=dt.datetime(2026, 2, 15, 13, 0),
            end=dt.datetime(2026, 2, 15, 13, 30),
            location="Office A",
        )
        calendar_service._providers[CalendarProvider.GOOGLE].list_events = AsyncMock(return_value=[prior])

        event = CalendarEvent(
            title="Meeting",
            start=dt.datetime(2026, 2, 15, 14, 0),
            end=dt.datetime(2026, 2, 15, 15, 0),
            location="Office B",
        )
        result = await calendar_service.calculate_prep_time(event, 15)
        assert result.travel_time_needed is True

    @pytest.mark.asyncio
    async def test_schedule_with_prep(self, calendar_service, mock_google_provider) -> None:
        """schedule_with_prep creates both event and prep block."""
        event = CalendarEvent(
            title="Important Meeting",
            start=dt.datetime(2026, 2, 15, 14, 0),
            end=dt.datetime(2026, 2, 15, 15, 0),
        )
        mock_google_provider.create_event = AsyncMock(side_effect=lambda e: e)
        mock_google_provider.list_events = AsyncMock(return_value=[])

        created, prep = await calendar_service.schedule_with_prep(
            event, prep_minutes=15, provider=CalendarProvider.GOOGLE,
        )
        assert created.title == "Important Meeting"
        assert prep is not None
        assert "[Prep]" in prep.title

    @pytest.mark.asyncio
    async def test_delete_event(self, calendar_service, mock_google_provider) -> None:
        """delete_event delegates to the right provider."""
        result = await calendar_service.delete_event("event123", CalendarProvider.GOOGLE)
        assert result is True
        mock_google_provider.delete_event.assert_called_once_with("event123")

    @pytest.mark.asyncio
    async def test_update_event(self, calendar_service, mock_google_provider) -> None:
        """update_event delegates to the right provider."""
        event = CalendarEvent(
            title="Updated",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
            provider=CalendarProvider.GOOGLE,
        )
        mock_google_provider.update_event = AsyncMock(return_value=event)
        result = await calendar_service.update_event(event)
        assert result.title == "Updated"
