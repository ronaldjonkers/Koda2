"""Calendar service — unified interface across all providers."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from koda2.logging_config import get_logger
from koda2.modules.calendar.models import (
    CalendarEvent,
    CalendarProvider,
    ConflictResult,
    PrepTimeResult,
)
from koda2.modules.calendar.providers import (
    BaseCalendarProvider,
    CalDAVCalendarProvider,
    EWSCalendarProvider,
    GoogleCalendarProvider,
    MSGraphCalendarProvider,
)

logger = get_logger(__name__)


class CalendarService:
    """Unified calendar management across all configured providers."""

    def __init__(self) -> None:
        self._providers: dict[CalendarProvider, BaseCalendarProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        """Initialize all configured calendar providers."""
        candidates: list[BaseCalendarProvider] = [
            EWSCalendarProvider(),
            GoogleCalendarProvider(),
            MSGraphCalendarProvider(),
            CalDAVCalendarProvider(),
        ]
        for p in candidates:
            if p.is_configured():
                self._providers[p.provider] = p
                logger.info("calendar_provider_enabled", provider=p.provider)

    @property
    def active_providers(self) -> list[CalendarProvider]:
        """List active provider names."""
        return list(self._providers.keys())

    async def list_all_calendars(self) -> dict[CalendarProvider, list[str]]:
        """List all calendars across all active providers."""
        result: dict[CalendarProvider, list[str]] = {}
        for provider, impl in self._providers.items():
            try:
                cals = await impl.list_calendars()
                result[provider] = cals
            except Exception as exc:
                logger.error("list_calendars_failed", provider=provider, error=str(exc))
                result[provider] = []
        return result

    async def list_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        provider: Optional[CalendarProvider] = None,
        calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """List events from one or all providers."""
        events: list[CalendarEvent] = []
        targets = (
            {provider: self._providers[provider]}
            if provider and provider in self._providers
            else self._providers
        )
        for p_name, impl in targets.items():
            try:
                p_events = await impl.list_events(start, end, calendar_name)
                events.extend(p_events)
            except Exception as exc:
                logger.error("list_events_failed", provider=p_name, error=str(exc))

        events.sort(key=lambda e: e.start)
        return events

    async def create_event(
        self,
        event: CalendarEvent,
        provider: Optional[CalendarProvider] = None,
    ) -> CalendarEvent:
        """Create an event on the specified provider (or first available)."""
        target_provider = provider or (self.active_providers[0] if self.active_providers else None)
        if not target_provider or target_provider not in self._providers:
            raise ValueError(f"No calendar provider available: {target_provider}")

        impl = self._providers[target_provider]
        created = await impl.create_event(event)
        logger.info("event_created", title=event.title, provider=target_provider)
        return created

    async def update_event(
        self,
        event: CalendarEvent,
        provider: Optional[CalendarProvider] = None,
    ) -> CalendarEvent:
        """Update an event."""
        target = provider or event.provider
        if not target or target not in self._providers:
            raise ValueError(f"Provider not available: {target}")
        return await self._providers[target].update_event(event)

    async def delete_event(
        self,
        event_id: str,
        provider: CalendarProvider,
    ) -> bool:
        """Delete an event by provider and ID."""
        if provider not in self._providers:
            raise ValueError(f"Provider not available: {provider}")
        return await self._providers[provider].delete_event(event_id)

    async def detect_conflicts(
        self,
        proposed: CalendarEvent,
        buffer_minutes: int = 0,
    ) -> ConflictResult:
        """Detect scheduling conflicts with existing events."""
        search_start = proposed.start - dt.timedelta(minutes=buffer_minutes)
        search_end = proposed.end + dt.timedelta(minutes=buffer_minutes)
        existing = await self.list_events(search_start, search_end)

        conflicts = [e for e in existing if proposed.conflicts_with(e)]
        return ConflictResult(
            has_conflict=len(conflicts) > 0,
            conflicting_events=conflicts,
        )

    async def calculate_prep_time(
        self,
        event: CalendarEvent,
        default_prep_minutes: int = 15,
    ) -> PrepTimeResult:
        """Calculate available preparation time before an event."""
        search_start = event.start - dt.timedelta(hours=4)
        earlier_events = await self.list_events(search_start, event.start)
        earlier_events = [e for e in earlier_events if e.end <= event.start]

        if earlier_events:
            prev = max(earlier_events, key=lambda e: e.end)
            available = int((event.start - prev.end).total_seconds() / 60)
            travel = bool(prev.location and event.location and prev.location != event.location)
            return PrepTimeResult(
                event_before=prev,
                event_after=event,
                available_minutes=available,
                suggested_prep_minutes=min(default_prep_minutes, available),
                travel_time_needed=travel,
            )

        return PrepTimeResult(
            event_after=event,
            available_minutes=240,
            suggested_prep_minutes=default_prep_minutes,
        )

    async def schedule_with_prep(
        self,
        event: CalendarEvent,
        prep_minutes: int = 15,
        provider: Optional[CalendarProvider] = None,
    ) -> tuple[CalendarEvent, Optional[CalendarEvent]]:
        """Create an event and optionally a prep-time block before it."""
        created = await self.create_event(event, provider)

        prep_event = None
        if prep_minutes > 0:
            prep_time = await self.calculate_prep_time(event, prep_minutes)
            if prep_time.available_minutes >= prep_minutes:
                prep_event = CalendarEvent(
                    title=f"[Prep] {event.title}",
                    description=f"Preparation time for: {event.title}",
                    start=event.start - dt.timedelta(minutes=prep_minutes),
                    end=event.start,
                    calendar_name=event.calendar_name,
                )
                prep_event = await self.create_event(prep_event, provider)
                logger.info("prep_time_scheduled", minutes=prep_minutes, event_title=event.title)

        return created, prep_event
