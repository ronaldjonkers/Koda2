"""Local database cache for calendar events.

Stores events fetched from remote providers so the API and assistant
can always access them without hitting the remote server on every request.
A background sync task keeps the cache fresh.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean, Index, select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from koda2.database import Base, get_session
from koda2.logging_config import get_logger
from koda2.modules.calendar.models import CalendarEvent, CalendarProvider, Attendee

logger = get_logger(__name__)


class CachedCalendarEvent(Base):
    """SQLAlchemy model for locally cached calendar events."""

    __tablename__ = "cached_calendar_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(String(512), nullable=False)
    provider = Column(String(50), nullable=True)
    account_name = Column(String(255), nullable=True)
    calendar_name = Column(String(255), nullable=True)
    title = Column(String(1024), nullable=False, default="")
    description = Column(Text, nullable=True, default="")
    location = Column(String(1024), nullable=True, default="")
    start = Column(DateTime, nullable=False)
    end = Column(DateTime, nullable=False)
    all_day = Column(Boolean, default=False)
    organizer = Column(String(512), nullable=True, default="")
    attendees_json = Column(Text, nullable=True, default="[]")
    is_online = Column(Boolean, default=False)
    meeting_url = Column(String(2048), nullable=True, default="")
    status = Column(String(50), nullable=True, default="confirmed")
    synced_at = Column(DateTime, nullable=False, default=dt.datetime.utcnow)

    __table_args__ = (
        Index("ix_cached_events_start", "start"),
        Index("ix_cached_events_provider_id", "provider_id", "account_name", unique=True),
    )


class CalendarCache:
    """Manages the local calendar event cache."""

    @staticmethod
    def _to_db(event: CalendarEvent, account_name: str = "") -> dict:
        """Convert a CalendarEvent to a dict for DB insertion."""
        attendees = [{"name": a.name, "email": a.email, "status": a.status} for a in event.attendees]
        start = event.start.replace(tzinfo=None) if event.start.tzinfo else event.start
        end = event.end.replace(tzinfo=None) if event.end.tzinfo else event.end
        return {
            "provider_id": event.provider_id,
            "provider": event.provider.value if event.provider else None,
            "account_name": account_name or event.calendar_name,
            "calendar_name": event.calendar_name,
            "title": event.title,
            "description": event.description,
            "location": event.location,
            "start": start,
            "end": end,
            "all_day": event.all_day,
            "organizer": event.organizer,
            "attendees_json": json.dumps(attendees),
            "is_online": event.is_online,
            "meeting_url": event.meeting_url,
            "status": event.status,
            "synced_at": dt.datetime.utcnow(),
        }

    @staticmethod
    def _from_db(row: CachedCalendarEvent) -> CalendarEvent:
        """Convert a DB row to a CalendarEvent."""
        attendees = []
        try:
            for a in json.loads(row.attendees_json or "[]"):
                attendees.append(Attendee(name=a.get("name", ""), email=a["email"], status=a.get("status", "")))
        except Exception:
            pass

        return CalendarEvent(
            provider=CalendarProvider(row.provider) if row.provider else None,
            provider_id=row.provider_id,
            title=row.title or "",
            description=row.description or "",
            location=row.location or "",
            start=row.start,
            end=row.end,
            all_day=row.all_day or False,
            attendees=attendees,
            organizer=row.organizer or "",
            calendar_name=row.calendar_name or "",
            is_online=row.is_online or False,
            meeting_url=row.meeting_url or "",
            status=row.status or "confirmed",
        )

    async def sync_events(
        self,
        events: list[CalendarEvent],
        account_name: str,
        window_start: dt.datetime,
        window_end: dt.datetime,
    ) -> int:
        """Sync a batch of events into the cache.

        Deletes old events for this account in the time window, then inserts fresh ones.
        Returns the number of events cached.
        """
        # Normalize to naive UTC
        ws = window_start.replace(tzinfo=None) if window_start.tzinfo else window_start
        we = window_end.replace(tzinfo=None) if window_end.tzinfo else window_end

        async with get_session() as session:
            # Delete existing events for this account in the window
            await session.execute(
                delete(CachedCalendarEvent).where(
                    CachedCalendarEvent.account_name == account_name,
                    CachedCalendarEvent.start >= ws,
                    CachedCalendarEvent.start <= we,
                )
            )

            # Insert fresh events
            for event in events:
                db_data = self._to_db(event, account_name)
                # Upsert: check if exists by provider_id + account
                existing = (await session.execute(
                    select(CachedCalendarEvent).where(
                        CachedCalendarEvent.provider_id == db_data["provider_id"],
                        CachedCalendarEvent.account_name == db_data["account_name"],
                    )
                )).scalar_one_or_none()

                if existing:
                    for key, val in db_data.items():
                        setattr(existing, key, val)
                else:
                    session.add(CachedCalendarEvent(**db_data))

        logger.info("calendar_cache_synced", account=account_name, events=len(events))
        return len(events)

    async def get_events(
        self,
        start: dt.datetime,
        end: dt.datetime,
        account_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """Get cached events from the local DB."""
        ws = start.replace(tzinfo=None) if start.tzinfo else start
        we = end.replace(tzinfo=None) if end.tzinfo else end

        async with get_session() as session:
            stmt = select(CachedCalendarEvent).where(
                CachedCalendarEvent.start >= ws,
                CachedCalendarEvent.start <= we,
            )
            if account_name:
                stmt = stmt.where(CachedCalendarEvent.account_name == account_name)
            stmt = stmt.order_by(CachedCalendarEvent.start)

            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [self._from_db(row) for row in rows]

    async def get_last_sync(self, account_name: Optional[str] = None) -> Optional[dt.datetime]:
        """Get the timestamp of the last sync for an account."""
        async with get_session() as session:
            stmt = select(CachedCalendarEvent.synced_at)
            if account_name:
                stmt = stmt.where(CachedCalendarEvent.account_name == account_name)
            stmt = stmt.order_by(CachedCalendarEvent.synced_at.desc()).limit(1)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return row

    async def clear(self, account_name: Optional[str] = None) -> None:
        """Clear the cache (all or for a specific account)."""
        async with get_session() as session:
            stmt = delete(CachedCalendarEvent)
            if account_name:
                stmt = stmt.where(CachedCalendarEvent.account_name == account_name)
            await session.execute(stmt)
        logger.info("calendar_cache_cleared", account=account_name or "all")
