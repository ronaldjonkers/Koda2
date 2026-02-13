"""Calendar service — unified interface across all providers with multi-account support.

Events are cached locally in SQLite so the API and assistant always have
access, even when the remote provider is temporarily unreachable.
A background sync task keeps the cache fresh.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from koda2.logging_config import get_logger
from koda2.modules.account.models import AccountType, ProviderType
from koda2.modules.account.service import AccountService
from koda2.modules.calendar.cache import CalendarCache
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
    """Unified calendar management with multi-account support."""

    # How far ahead to sync events (days)
    SYNC_WINDOW_DAYS = 30

    def __init__(self, account_service: Optional[AccountService] = None) -> None:
        self._account_service = account_service or AccountService()
        self._providers: dict[str, BaseCalendarProvider] = {}  # account_id -> provider
        self._cache = CalendarCache()
        self._last_sync: Optional[dt.datetime] = None

    async def _get_provider(self, account_id: Optional[str] = None) -> tuple[str, BaseCalendarProvider]:
        """Get a calendar provider for the specified account or default.
        
        Returns:
            Tuple of (account_id, provider_instance)
        """
        if account_id and account_id in self._providers:
            return account_id, self._providers[account_id]
        
        if account_id:
            # Look up the specific account by ID
            account = await self._account_service.get_account(account_id)
        else:
            # Fall back to default calendar account
            account = await self._account_service.get_default_account(AccountType.CALENDAR)
        
        if not account:
            raise ValueError("No calendar account configured")
        
        # Initialize provider if needed
        if account.id not in self._providers:
            provider = self._create_provider(account)
            if provider:
                self._providers[account.id] = provider
        
        if account.id not in self._providers:
            raise ValueError(f"Could not initialize provider for account: {account.name}")
        
        return account.id, self._providers[account.id]

    def _create_provider(self, account) -> Optional[BaseCalendarProvider]:
        """Create a provider instance from an account."""
        try:
            credentials = self._account_service.decrypt_credentials(account)
            provider_type = ProviderType(account.provider)
            
            if provider_type == ProviderType.EWS:
                return EWSCalendarProvider(
                    server=credentials["server"],
                    username=credentials["username"],
                    password=credentials["password"],
                    email=credentials["email"],
                )
            elif provider_type == ProviderType.GOOGLE:
                return GoogleCalendarProvider(
                    credentials_file=credentials["credentials_file"],
                    token_file=credentials["token_file"],
                )
            elif provider_type == ProviderType.MSGRAPH:
                return MSGraphCalendarProvider(
                    client_id=credentials["client_id"],
                    client_secret=credentials["client_secret"],
                    tenant_id=credentials["tenant_id"],
                )
            elif provider_type == ProviderType.CALDAV:
                return CalDAVCalendarProvider(
                    url=credentials["url"],
                    username=credentials["username"],
                    password=credentials["password"],
                )
            else:
                logger.error("unsupported_calendar_provider", provider=provider_type)
                return None
        except Exception as exc:
            import traceback
            logger.error(
                "failed_to_create_provider",
                account_id=account.id,
                account_name=account.name,
                provider=account.provider,
                error=f"{type(exc).__name__}: {exc}",
                traceback=traceback.format_exc(),
            )
            return None

    async def get_accounts(self, active_only: bool = True) -> list:
        """Get all calendar accounts."""
        return await self._account_service.get_accounts(
            account_type=AccountType.CALENDAR,
            active_only=active_only,
        )

    async def active_accounts(self) -> list:
        """List active calendar account names."""
        accounts = await self.get_accounts()
        return [acc.name for acc in accounts]

    async def active_providers(self) -> list[str]:
        """List active provider types."""
        accounts = await self.get_accounts()
        return list(set(acc.provider for acc in accounts))

    async def list_all_calendars(self) -> dict[str, list[str]]:
        """List all calendars across all active accounts.
        
        Deduplicates calendars that appear in multiple accounts sharing
        the same provider credentials (e.g. two Google accounts with same token).
        """
        result: dict[str, list[str]] = {}
        seen_cal_ids: set[str] = set()
        accounts = await self.get_accounts()
        
        for account in accounts:
            try:
                _, provider = await self._get_provider(account.id)
                cals = await provider.list_calendars()
                # Deduplicate: skip calendar IDs we've already seen
                unique_cals = [c for c in cals if c not in seen_cal_ids]
                seen_cal_ids.update(unique_cals)
                if unique_cals:
                    result[account.name] = unique_cals
            except Exception as exc:
                logger.error("list_calendars_failed", account=account.name, error=str(exc))
                result[account.name] = []
        
        return result

    async def list_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        account_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """List events — always fetches live from all providers."""
        events = await self._fetch_events_live(start, end, account_id, calendar_name)

        # Update cache in the background (best-effort)
        if events:
            try:
                accounts = await self.get_accounts()
                account_name = accounts[0].name if accounts else "default"
                await self._cache.sync_events(events, account_name, start, end)
            except Exception as exc:
                logger.warning("cache_write_failed", error=str(exc))

        return events

    async def _fetch_events_live(
        self,
        start: dt.datetime,
        end: dt.datetime,
        account_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """Fetch events directly from remote providers (no cache)."""
        events: list[CalendarEvent] = []

        if account_id:
            try:
                _, provider = await self._get_provider(account_id)
                events = await provider.list_events(start, end, calendar_name)
            except Exception as exc:
                logger.error("list_events_failed", account_id=account_id, error=str(exc))
        else:
            accounts = await self.get_accounts()
            for account in accounts:
                try:
                    _, provider = await self._get_provider(account.id)
                    acc_events = await provider.list_events(start, end, calendar_name)
                    for event in acc_events:
                        event.calendar_name = account.name
                    events.extend(acc_events)
                except Exception as exc:
                    logger.error("list_events_failed", account=account.name, error=str(exc))

        # Deduplicate events by provider_id (multiple accounts may share the same token)
        seen_ids: set[str] = set()
        unique_events: list[CalendarEvent] = []
        for event in events:
            key = event.provider_id
            if key and key in seen_ids:
                continue
            if key:
                seen_ids.add(key)
            unique_events.append(event)

        # Normalize to naive UTC for sorting (some providers return tz-aware, others naive)
        def _sort_key(e):
            s = e.start
            if s.tzinfo is not None:
                s = s.replace(tzinfo=None)
            return s
        unique_events.sort(key=_sort_key)
        return unique_events

    async def sync_all(self) -> dict[str, int]:
        """Sync events from all accounts into the local cache.

        Called periodically by the background sync task.
        Returns dict of account_name -> number of events synced.
        """
        results: dict[str, int] = {}
        now = dt.datetime.now(dt.UTC)
        start = now - dt.timedelta(days=7)  # Include recent past
        end = now + dt.timedelta(days=self.SYNC_WINDOW_DAYS)

        accounts = await self.get_accounts()
        for account in accounts:
            try:
                _, provider = await self._get_provider(account.id)
                events = await provider.list_events(start, end)
                for event in events:
                    event.calendar_name = event.calendar_name or account.name
                count = await self._cache.sync_events(events, account.name, start, end)
                results[account.name] = count
            except Exception as exc:
                logger.error("calendar_sync_failed", account=account.name, error=str(exc))
                results[account.name] = -1

        self._last_sync = dt.datetime.now(dt.UTC)
        logger.info("calendar_sync_complete", results=results)
        return results

    @property
    def last_sync(self) -> Optional[dt.datetime]:
        """When the last sync completed."""
        return self._last_sync

    async def create_event(
        self,
        event: CalendarEvent,
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
    ) -> CalendarEvent:
        """Create an event on the specified account (or default)."""
        # Find account by name if specified
        if account_name:
            accounts = await self.get_accounts()
            for acc in accounts:
                if acc.name.lower() == account_name.lower():
                    account_id = acc.id
                    break
        
        acc_id, provider = await self._get_provider(account_id)
        created = await provider.create_event(event)
        
        # Get account name for logging
        accounts = await self.get_accounts()
        account_name = next((a.name for a in accounts if a.id == acc_id), acc_id)
        logger.info("event_created", title=event.title, account=account_name)
        
        return created

    async def update_event(
        self,
        event: CalendarEvent,
        account_id: Optional[str] = None,
    ) -> CalendarEvent:
        """Update an event."""
        _, provider = await self._get_provider(account_id)
        return await provider.update_event(event)

    async def delete_event(
        self,
        event_id: str,
        account_id: str,
    ) -> bool:
        """Delete an event by account and ID."""
        _, provider = await self._get_provider(account_id)
        return await provider.delete_event(event_id)

    async def detect_conflicts(
        self,
        proposed: CalendarEvent,
        buffer_minutes: int = 0,
        account_id: Optional[str] = None,
    ) -> ConflictResult:
        """Detect scheduling conflicts with existing events."""
        search_start = proposed.start - dt.timedelta(minutes=buffer_minutes)
        search_end = proposed.end + dt.timedelta(minutes=buffer_minutes)
        existing = await self.list_events(search_start, search_end, account_id)

        conflicts = [e for e in existing if proposed.conflicts_with(e)]
        return ConflictResult(
            has_conflict=len(conflicts) > 0,
            conflicting_events=conflicts,
        )

    async def calculate_prep_time(
        self,
        event: CalendarEvent,
        default_prep_minutes: int = 15,
        account_id: Optional[str] = None,
    ) -> PrepTimeResult:
        """Calculate available preparation time before an event."""
        search_start = event.start - dt.timedelta(hours=4)
        earlier_events = await self.list_events(search_start, event.start, account_id)
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
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
    ) -> tuple[CalendarEvent, Optional[CalendarEvent]]:
        """Create an event and optionally a prep-time block before it."""
        created = await self.create_event(event, account_id, account_name)

        prep_event = None
        if prep_minutes > 0:
            prep_time = await self.calculate_prep_time(event, prep_minutes, account_id)
            if prep_time.available_minutes >= prep_minutes:
                prep_event = CalendarEvent(
                    title=f"[Prep] {event.title}",
                    description=f"Preparation time for: {event.title}",
                    start=event.start - dt.timedelta(minutes=prep_minutes),
                    end=event.start,
                    calendar_name=event.calendar_name,
                )
                prep_event = await self.create_event(prep_event, account_id, account_name)
                logger.info("prep_time_scheduled", minutes=prep_minutes, event_title=event.title)

        return created, prep_event
