"""Tests for the calendar service (conflict detection, prep time, unified interface)."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.calendar.models import Attendee, CalendarEvent, CalendarProvider
from koda2.modules.calendar.service import CalendarService


ACCOUNT_ID = "test-account-1"


@pytest.fixture
def mock_provider():
    """Create a mock calendar provider."""
    provider = MagicMock()
    provider.list_events = AsyncMock(return_value=[])
    provider.create_event = AsyncMock()
    provider.update_event = AsyncMock()
    provider.delete_event = AsyncMock(return_value=True)
    provider.list_calendars = AsyncMock(return_value=["primary", "work"])
    return provider


@pytest.fixture
def mock_account():
    """Create a mock account object."""
    account = MagicMock()
    account.id = ACCOUNT_ID
    account.name = "Test Calendar"
    account.provider = "google"
    account.is_active = True
    account.is_default = True
    return account


@pytest.fixture
def mock_account_service(mock_account):
    """Create a mock AccountService."""
    svc = MagicMock()
    svc.get_accounts = AsyncMock(return_value=[mock_account])
    svc.get_default_account = AsyncMock(return_value=mock_account)
    svc.decrypt_credentials = MagicMock(return_value={
        "credentials_file": "config/google_credentials.json",
        "token_file": "config/google_token.json",
    })
    return svc


@pytest.fixture
def calendar_service(mock_account_service, mock_provider):
    """Create a CalendarService with mocked account service and pre-injected provider."""
    service = CalendarService(mock_account_service)
    # Pre-inject the provider so _get_provider finds it
    service._providers[ACCOUNT_ID] = mock_provider
    return service


class TestCalendarService:
    """Tests for the unified calendar service."""

    @pytest.mark.asyncio
    async def test_active_providers(self, calendar_service) -> None:
        """Active providers list only configured providers."""
        providers = await calendar_service.active_providers()
        assert "google" in providers

    @pytest.mark.asyncio
    async def test_list_all_calendars(self, calendar_service) -> None:
        """list_all_calendars returns calendars from all accounts."""
        result = await calendar_service.list_all_calendars()
        assert "Test Calendar" in result
        assert "primary" in result["Test Calendar"]

    @pytest.mark.asyncio
    async def test_list_events(self, calendar_service, mock_provider) -> None:
        """list_events returns sorted events."""
        now = dt.datetime(2026, 2, 12, 10, 0)
        events = [
            CalendarEvent(title="B", start=now + dt.timedelta(hours=2), end=now + dt.timedelta(hours=3)),
            CalendarEvent(title="A", start=now, end=now + dt.timedelta(hours=1)),
        ]
        mock_provider.list_events = AsyncMock(return_value=events)

        result = await calendar_service.list_events(now, now + dt.timedelta(days=1))
        assert len(result) == 2
        assert result[0].title == "A"
        assert result[1].title == "B"

    @pytest.mark.asyncio
    async def test_list_events_provider_error(self, calendar_service, mock_provider) -> None:
        """Provider errors are caught and logged."""
        mock_provider.list_events = AsyncMock(side_effect=Exception("API error"))
        result = await calendar_service.list_events(
            dt.datetime(2026, 2, 12), dt.datetime(2026, 2, 13)
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_create_event(self, calendar_service, mock_provider) -> None:
        """create_event delegates to the provider."""
        event = CalendarEvent(
            title="Test Meeting",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        mock_provider.create_event = AsyncMock(return_value=event)

        result = await calendar_service.create_event(event, ACCOUNT_ID)
        mock_provider.create_event.assert_called_once_with(event)
        assert result.title == "Test Meeting"

    @pytest.mark.asyncio
    async def test_create_event_no_account(self) -> None:
        """create_event raises when no account is configured."""
        mock_svc = MagicMock()
        mock_svc.get_accounts = AsyncMock(return_value=[])
        mock_svc.get_default_account = AsyncMock(return_value=None)
        service = CalendarService(mock_svc)

        event = CalendarEvent(
            title="Test",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        with pytest.raises(ValueError, match="No calendar account"):
            await service.create_event(event)

    @pytest.mark.asyncio
    async def test_detect_conflicts_none(self, calendar_service, mock_provider) -> None:
        """No conflicts when calendar is empty."""
        mock_provider.list_events = AsyncMock(return_value=[])

        proposed = CalendarEvent(
            title="New Meeting",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        result = await calendar_service.detect_conflicts(proposed)
        assert result.has_conflict is False

    @pytest.mark.asyncio
    async def test_detect_conflicts_found(self, calendar_service, mock_provider) -> None:
        """Conflicts detected when events overlap."""
        existing = CalendarEvent(
            title="Existing",
            start=dt.datetime(2026, 2, 15, 10, 30),
            end=dt.datetime(2026, 2, 15, 11, 30),
        )
        mock_provider.list_events = AsyncMock(return_value=[existing])

        proposed = CalendarEvent(
            title="New Meeting",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        result = await calendar_service.detect_conflicts(proposed)
        assert result.has_conflict is True
        assert len(result.conflicting_events) == 1

    @pytest.mark.asyncio
    async def test_calculate_prep_time_no_prior(self, calendar_service, mock_provider) -> None:
        """Prep time calculation with no prior events."""
        mock_provider.list_events = AsyncMock(return_value=[])

        event = CalendarEvent(
            title="Meeting",
            start=dt.datetime(2026, 2, 15, 14, 0),
            end=dt.datetime(2026, 2, 15, 15, 0),
        )
        result = await calendar_service.calculate_prep_time(event, 15)
        assert result.available_minutes == 240
        assert result.suggested_prep_minutes == 15

    @pytest.mark.asyncio
    async def test_calculate_prep_time_with_prior(self, calendar_service, mock_provider) -> None:
        """Prep time calculation with a prior event."""
        prior = CalendarEvent(
            title="Earlier",
            start=dt.datetime(2026, 2, 15, 13, 0),
            end=dt.datetime(2026, 2, 15, 13, 30),
        )
        mock_provider.list_events = AsyncMock(return_value=[prior])

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
    async def test_calculate_prep_time_travel(self, calendar_service, mock_provider) -> None:
        """Prep time detects travel needed between different locations."""
        prior = CalendarEvent(
            title="Earlier",
            start=dt.datetime(2026, 2, 15, 13, 0),
            end=dt.datetime(2026, 2, 15, 13, 30),
            location="Office A",
        )
        mock_provider.list_events = AsyncMock(return_value=[prior])

        event = CalendarEvent(
            title="Meeting",
            start=dt.datetime(2026, 2, 15, 14, 0),
            end=dt.datetime(2026, 2, 15, 15, 0),
            location="Office B",
        )
        result = await calendar_service.calculate_prep_time(event, 15)
        assert result.travel_time_needed is True

    @pytest.mark.asyncio
    async def test_schedule_with_prep(self, calendar_service, mock_provider) -> None:
        """schedule_with_prep creates both event and prep block."""
        event = CalendarEvent(
            title="Important Meeting",
            start=dt.datetime(2026, 2, 15, 14, 0),
            end=dt.datetime(2026, 2, 15, 15, 0),
        )
        mock_provider.create_event = AsyncMock(side_effect=lambda e: e)
        mock_provider.list_events = AsyncMock(return_value=[])

        created, prep = await calendar_service.schedule_with_prep(
            event, prep_minutes=15, account_id=ACCOUNT_ID,
        )
        assert created.title == "Important Meeting"
        assert prep is not None
        assert "[Prep]" in prep.title

    @pytest.mark.asyncio
    async def test_delete_event(self, calendar_service, mock_provider) -> None:
        """delete_event delegates to the provider."""
        result = await calendar_service.delete_event("event123", ACCOUNT_ID)
        assert result is True
        mock_provider.delete_event.assert_called_once_with("event123")

    @pytest.mark.asyncio
    async def test_update_event(self, calendar_service, mock_provider) -> None:
        """update_event delegates to the provider."""
        event = CalendarEvent(
            title="Updated",
            start=dt.datetime(2026, 2, 15, 10, 0),
            end=dt.datetime(2026, 2, 15, 11, 0),
        )
        mock_provider.update_event = AsyncMock(return_value=event)
        result = await calendar_service.update_event(event, ACCOUNT_ID)
        assert result.title == "Updated"
