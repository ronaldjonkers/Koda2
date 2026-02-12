"""Calendar provider implementations (EWS, Google, MS Graph, CalDAV)."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from koda2.logging_config import get_logger
from koda2.modules.calendar.models import Attendee, CalendarEvent, CalendarProvider

logger = get_logger(__name__)


class BaseCalendarProvider(ABC):
    """Abstract calendar provider interface."""

    provider: CalendarProvider

    @abstractmethod
    async def list_events(
        self, start: dt.datetime, end: dt.datetime, calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        """List events in a date range."""

    @abstractmethod
    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        """Create a new calendar event."""

    @abstractmethod
    async def update_event(self, event: CalendarEvent) -> CalendarEvent:
        """Update an existing event."""

    @abstractmethod
    async def delete_event(self, event_id: str) -> bool:
        """Delete an event by its provider-specific ID."""

    @abstractmethod
    async def list_calendars(self) -> list[str]:
        """List available calendar names."""


class EWSCalendarProvider(BaseCalendarProvider):
    """Exchange Web Services calendar integration."""

    provider = CalendarProvider.EWS

    def __init__(
        self,
        server: str,
        username: str,
        password: str,
        email: str,
    ) -> None:
        self._server = server
        self._username = username
        self._password = password
        self._email = email
        self._account = None

    def _get_account(self):
        """Lazy-initialize the Exchange account connection."""
        if self._account is not None:
            return self._account
        from exchangelib import Account, Configuration, Credentials, DELEGATE

        creds = Credentials(self._username, self._password)
        config = Configuration(server=self._server, credentials=creds)
        self._account = Account(
            self._email,
            config=config,
            autodiscover=False,
            access_type=DELEGATE,
        )
        return self._account

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def list_events(
        self, start: dt.datetime, end: dt.datetime, calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        import asyncio
        from exchangelib import EWSDateTime, EWSTimeZone

        account = self._get_account()
        tz = EWSTimeZone.timezone("UTC")
        ews_start = EWSDateTime.from_datetime(start.replace(tzinfo=tz))
        ews_end = EWSDateTime.from_datetime(end.replace(tzinfo=tz))

        def _fetch():
            calendar = account.calendar
            items = calendar.view(start=ews_start, end=ews_end)
            events = []
            for item in items:
                attendees = []
                if item.required_attendees:
                    attendees.extend(
                        Attendee(email=a.mailbox.email_address, name=a.mailbox.name or "")
                        for a in item.required_attendees
                    )
                events.append(CalendarEvent(
                    provider=self.provider,
                    provider_id=str(item.id),
                    title=item.subject or "",
                    description=item.body or "",
                    location=item.location or "",
                    start=item.start,
                    end=item.end,
                    attendees=attendees,
                    organizer=str(item.organizer) if item.organizer else "",
                    calendar_name="default",
                ))
            return events

        return await asyncio.to_thread(_fetch)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        import asyncio
        from exchangelib import CalendarItem, EWSDateTime, EWSTimeZone

        account = self._get_account()
        tz = EWSTimeZone.timezone("UTC")

        def _create():
            item = CalendarItem(
                account=account,
                folder=account.calendar,
                subject=event.title,
                body=event.description,
                start=EWSDateTime.from_datetime(event.start.replace(tzinfo=tz)),
                end=EWSDateTime.from_datetime(event.end.replace(tzinfo=tz)),
                location=event.location,
            )
            item.save(send_meeting_invitations="SendToAllAndSaveCopy")
            return str(item.id)

        provider_id = await asyncio.to_thread(_create)
        event.provider_id = provider_id
        event.provider = self.provider
        return event

    async def update_event(self, event: CalendarEvent) -> CalendarEvent:
        logger.warning("ews_update_not_fully_implemented")
        return event

    async def delete_event(self, event_id: str) -> bool:
        import asyncio
        account = self._get_account()

        def _delete():
            from exchangelib import CalendarItem
            items = account.calendar.filter(id=event_id)
            for item in items:
                item.delete(send_meeting_cancellations="SendToAllAndSaveCopy")
            return True

        return await asyncio.to_thread(_delete)

    async def list_calendars(self) -> list[str]:
        return ["default"]


class GoogleCalendarProvider(BaseCalendarProvider):
    """Google Calendar API integration."""

    provider = CalendarProvider.GOOGLE

    def __init__(
        self,
        credentials_file: str,
        token_file: str,
    ) -> None:
        self._credentials_file = credentials_file
        self._token_file = token_file
        self._service = None

    def _get_service(self):
        """Lazy-init Google Calendar service."""
        if self._service is not None:
            return self._service
        from pathlib import Path

        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.modify",
        ]
        creds = None
        token_path = Path(self._token_file)
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._credentials_file, SCOPES
                )
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def list_events(
        self, start: dt.datetime, end: dt.datetime, calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        import asyncio

        service = self._get_service()
        cal_id = calendar_name or "primary"

        def _fetch():
            result = service.events().list(
                calendarId=cal_id,
                timeMin=start.isoformat() + "Z",
                timeMax=end.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            events = []
            for item in result.get("items", []):
                s = item.get("start", {})
                e = item.get("end", {})
                start_dt = dt.datetime.fromisoformat(
                    s.get("dateTime", s.get("date", "")).replace("Z", "+00:00")
                )
                end_dt = dt.datetime.fromisoformat(
                    e.get("dateTime", e.get("date", "")).replace("Z", "+00:00")
                )
                attendees = [
                    Attendee(email=a["email"], name=a.get("displayName", ""),
                             status=a.get("responseStatus", "needsAction"))
                    for a in item.get("attendees", [])
                ]
                events.append(CalendarEvent(
                    provider=CalendarProvider.GOOGLE,
                    provider_id=item["id"],
                    title=item.get("summary", ""),
                    description=item.get("description", ""),
                    location=item.get("location", ""),
                    start=start_dt,
                    end=end_dt,
                    attendees=attendees,
                    organizer=item.get("organizer", {}).get("email", ""),
                    is_online="hangoutLink" in item,
                    meeting_url=item.get("hangoutLink", ""),
                    calendar_name=cal_id,
                ))
            return events

        return await asyncio.to_thread(_fetch)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        import asyncio

        service = self._get_service()

        def _create():
            body = {
                "summary": event.title,
                "description": event.description,
                "location": event.location,
                "start": {"dateTime": event.start.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": event.end.isoformat(), "timeZone": "UTC"},
                "attendees": [{"email": a.email} for a in event.attendees],
                "reminders": {"useDefault": False, "overrides": [
                    {"method": "popup", "minutes": m} for m in event.reminders
                ]},
            }
            result = service.events().insert(
                calendarId=event.calendar_name or "primary",
                body=body,
                sendUpdates="all",
            ).execute()
            return result["id"]

        provider_id = await asyncio.to_thread(_create)
        event.provider_id = provider_id
        event.provider = self.provider
        return event

    async def update_event(self, event: CalendarEvent) -> CalendarEvent:
        import asyncio
        service = self._get_service()

        def _update():
            body = {
                "summary": event.title,
                "description": event.description,
                "location": event.location,
                "start": {"dateTime": event.start.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": event.end.isoformat(), "timeZone": "UTC"},
            }
            service.events().update(
                calendarId=event.calendar_name or "primary",
                eventId=event.provider_id,
                body=body,
                sendUpdates="all",
            ).execute()

        await asyncio.to_thread(_update)
        return event

    async def delete_event(self, event_id: str) -> bool:
        import asyncio
        service = self._get_service()

        def _delete():
            service.events().delete(calendarId="primary", eventId=event_id).execute()
        await asyncio.to_thread(_delete)
        return True

    async def list_calendars(self) -> list[str]:
        import asyncio
        service = self._get_service()

        def _list():
            result = service.calendarList().list().execute()
            return [c["id"] for c in result.get("items", [])]
        return await asyncio.to_thread(_list)


class MSGraphCalendarProvider(BaseCalendarProvider):
    """Microsoft Graph API calendar integration for Office 365."""

    provider = CalendarProvider.MSGRAPH

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._tenant_id = tenant_id

    async def _get_token(self) -> str:
        """Acquire an OAuth2 token via client credentials."""
        import httpx

        url = f"https://login.microsoftonline.com/{self._tenant_id}/oauth2/v2.0/token"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            })
            resp.raise_for_status()
            return resp.json()["access_token"]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def list_events(
        self, start: dt.datetime, end: dt.datetime, calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        import httpx

        token = await self._get_token()
        url = "https://graph.microsoft.com/v1.0/me/calendarview"
        params = {
            "startDateTime": start.isoformat() + "Z",
            "endDateTime": end.isoformat() + "Z",
            "$orderby": "start/dateTime",
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()

        events = []
        for item in data.get("value", []):
            events.append(CalendarEvent(
                provider=self.provider,
                provider_id=item["id"],
                title=item.get("subject", ""),
                description=item.get("bodyPreview", ""),
                location=item.get("location", {}).get("displayName", ""),
                start=dt.datetime.fromisoformat(item["start"]["dateTime"]),
                end=dt.datetime.fromisoformat(item["end"]["dateTime"]),
                attendees=[
                    Attendee(
                        email=a.get("emailAddress", {}).get("address", ""),
                        name=a.get("emailAddress", {}).get("name", ""),
                    )
                    for a in item.get("attendees", [])
                ],
                is_online=item.get("isOnlineMeeting", False),
                meeting_url=item.get("onlineMeeting", {}).get("joinUrl", "") if item.get("onlineMeeting") else "",
                calendar_name=calendar_name or "default",
            ))
        return events

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        import httpx

        token = await self._get_token()
        body = {
            "subject": event.title,
            "body": {"contentType": "text", "content": event.description},
            "start": {"dateTime": event.start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": event.end.isoformat(), "timeZone": "UTC"},
            "location": {"displayName": event.location},
            "attendees": [
                {"emailAddress": {"address": a.email, "name": a.name}, "type": "required"}
                for a in event.attendees
            ],
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://graph.microsoft.com/v1.0/me/events",
                json=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        event.provider_id = data["id"]
        event.provider = self.provider
        return event

    async def update_event(self, event: CalendarEvent) -> CalendarEvent:
        import httpx

        token = await self._get_token()
        body = {
            "subject": event.title,
            "body": {"contentType": "text", "content": event.description},
            "start": {"dateTime": event.start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": event.end.isoformat(), "timeZone": "UTC"},
            "location": {"displayName": event.location},
        }
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"https://graph.microsoft.com/v1.0/me/events/{event.provider_id}",
                json=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
        return event

    async def delete_event(self, event_id: str) -> bool:
        import httpx

        token = await self._get_token()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
        return True

    async def list_calendars(self) -> list[str]:
        import httpx

        token = await self._get_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://graph.microsoft.com/v1.0/me/calendars",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        return [c["name"] for c in data.get("value", [])]


class CalDAVCalendarProvider(BaseCalendarProvider):
    """CalDAV protocol calendar integration."""

    provider = CalendarProvider.CALDAV

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
    ) -> None:
        self._url = url
        self._username = username
        self._password = password

    def _get_client(self):
        import caldav
        return caldav.DAVClient(
            url=self._url,
            username=self._username,
            password=self._password,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def list_events(
        self, start: dt.datetime, end: dt.datetime, calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        import asyncio

        def _fetch():
            client = self._get_client()
            principal = client.principal()
            calendars = principal.calendars()
            events = []
            for cal in calendars:
                if calendar_name and cal.name != calendar_name:
                    continue
                results = cal.date_search(start=start, end=end, expand=True)
                for item in results:
                    vevent = item.vobject_instance.vevent
                    events.append(CalendarEvent(
                        provider=self.provider,
                        provider_id=str(item.url),
                        title=str(getattr(vevent, "summary", "")),
                        description=str(getattr(vevent, "description", "")),
                        location=str(getattr(vevent, "location", "")),
                        start=vevent.dtstart.value if hasattr(vevent.dtstart.value, "hour")
                            else dt.datetime.combine(vevent.dtstart.value, dt.time.min),
                        end=vevent.dtend.value if hasattr(vevent.dtend.value, "hour")
                            else dt.datetime.combine(vevent.dtend.value, dt.time.min),
                        calendar_name=cal.name,
                    ))
            return events

        return await asyncio.to_thread(_fetch)

    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        import asyncio

        def _create():
            client = self._get_client()
            principal = client.principal()
            calendars = principal.calendars()
            cal = calendars[0]
            vcal = f"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:{event.start.strftime('%Y%m%dT%H%M%SZ')}
DTEND:{event.end.strftime('%Y%m%dT%H%M%SZ')}
SUMMARY:{event.title}
DESCRIPTION:{event.description}
LOCATION:{event.location}
END:VEVENT
END:VCALENDAR"""
            new_event = cal.save_event(vcal)
            return str(new_event.url)

        provider_id = await asyncio.to_thread(_create)
        event.provider_id = provider_id
        event.provider = self.provider
        return event

    async def update_event(self, event: CalendarEvent) -> CalendarEvent:
        logger.warning("caldav_update_basic")
        return event

    async def delete_event(self, event_id: str) -> bool:
        import asyncio

        def _delete():
            client = self._get_client()
            import caldav
            event = caldav.CalendarObjectResource(client=client, url=event_id)
            event.delete()
        await asyncio.to_thread(_delete)
        return True

    async def list_calendars(self) -> list[str]:
        import asyncio

        def _list():
            client = self._get_client()
            principal = client.principal()
            return [c.name for c in principal.calendars()]
        return await asyncio.to_thread(_list)
