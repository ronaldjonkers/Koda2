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
    """Exchange Web Services calendar integration via direct SOAP + httpx-ntlm.

    Uses raw SOAP requests instead of exchangelib because exchangelib's NTLM
    handshake hangs on many Exchange servers with Python 3.13+.
    """

    provider = CalendarProvider.EWS

    def __init__(
        self,
        server: str,
        username: str,
        password: str,
        email: str,
    ) -> None:
        from koda2.modules.account.validators import _normalize_ews_server
        self._server = _normalize_ews_server(server)
        self._username = username
        self._password = password
        self._email = email
        self._ews_url = f"https://{self._server}/EWS/Exchange.asmx"
        self._headers = {"Content-Type": "text/xml; charset=utf-8"}
        self._auth = None  # Lazy init
        self._verified = False  # Whether we've verified the server works

    def _get_auth(self):
        """Get httpx-ntlm auth, building DOMAIN\\user variants."""
        if self._auth is not None:
            return self._auth
        try:
            from httpx_ntlm import HttpNtlmAuth
        except ImportError:
            raise RuntimeError("httpx-ntlm is required for EWS. Run: pip install httpx-ntlm")

        user = self._username
        # Auto-add domain prefix if not present
        if "\\" not in user and "@" not in user:
            domain = self._email.split("@")[-1].split(".")[0].upper() if "@" in self._email else ""
            if domain:
                user = f"{domain}\\{self._username}"
        self._auth = HttpNtlmAuth(user, self._password)
        return self._auth

    def _ensure_server(self) -> None:
        """Verify the configured server works; autodiscover if it doesn't."""
        if self._verified:
            return

        import httpx
        auth = self._get_auth()

        # Quick test on configured server
        try:
            with httpx.Client(verify=True, timeout=10) as client:
                resp = client.get(self._ews_url)
            if resp.status_code in (200, 401):
                # Server is reachable — try NTLM
                test_soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">
  <soap:Header><t:RequestServerVersion Version="Exchange2016"/></soap:Header>
  <soap:Body>
    <m:ResolveNames ReturnFullContactData="false">
      <m:UnresolvedEntry>{self._email}</m:UnresolvedEntry>
    </m:ResolveNames>
  </soap:Body>
</soap:Envelope>"""
                with httpx.Client(verify=True, timeout=15) as client:
                    resp = client.post(self._ews_url, content=test_soap, headers=self._headers, auth=auth)
                if resp.status_code == 200:
                    self._verified = True
                    logger.info("ews_server_verified", server=self._server)
                    return
        except Exception:
            pass

        # Server didn't work — try autodiscover
        logger.info("ews_autodiscovering", original_server=self._server, email=self._email)
        from koda2.modules.account.validators import _discover_ews_servers
        candidates = _discover_ews_servers(self._server, self._email)

        for srv in candidates:
            if srv == self._server:
                continue  # Already tried
            ews_url = f"https://{srv}/EWS/Exchange.asmx"
            try:
                test_soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">
  <soap:Header><t:RequestServerVersion Version="Exchange2016"/></soap:Header>
  <soap:Body>
    <m:ResolveNames ReturnFullContactData="false">
      <m:UnresolvedEntry>{self._email}</m:UnresolvedEntry>
    </m:ResolveNames>
  </soap:Body>
</soap:Envelope>"""
                with httpx.Client(verify=True, timeout=15) as client:
                    resp = client.post(ews_url, content=test_soap, headers=self._headers, auth=auth)
                if resp.status_code == 200:
                    logger.info("ews_autodiscovered", old_server=self._server, new_server=srv)
                    self._server = srv
                    self._ews_url = ews_url
                    self._verified = True
                    return
            except Exception:
                continue

        # If nothing worked, keep original and hope for the best
        self._verified = True
        logger.warning("ews_autodiscover_failed", server=self._server)

    def _soap_request(self, body_xml: str) -> str:
        """Execute a SOAP request against EWS and return the response XML."""
        import httpx
        self._ensure_server()
        soap = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
               xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"
               xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">
  <soap:Header>
    <t:RequestServerVersion Version="Exchange2016"/>
  </soap:Header>
  <soap:Body>
    {body_xml}
  </soap:Body>
</soap:Envelope>"""
        with httpx.Client(verify=True, timeout=30) as client:
            resp = client.post(self._ews_url, content=soap, headers=self._headers, auth=self._get_auth())
        if resp.status_code != 200:
            raise RuntimeError(f"EWS request failed: HTTP {resp.status_code}")
        return resp.text

    @staticmethod
    def _parse_events_xml(xml_text: str) -> list[dict]:
        """Parse CalendarItem elements from EWS FindItem response XML."""
        import xml.etree.ElementTree as ET
        ns = {
            "s": "http://schemas.xmlsoap.org/soap/envelope/",
            "t": "http://schemas.microsoft.com/exchange/services/2006/types",
            "m": "http://schemas.microsoft.com/exchange/services/2006/messages",
        }
        root = ET.fromstring(xml_text)
        items = root.findall(".//t:CalendarItem", ns)
        events = []
        for item in items:
            def _text(tag: str) -> str:
                el = item.find(f"t:{tag}", ns)
                return el.text if el is not None and el.text else ""

            # Parse organizer
            organizer = ""
            org_el = item.find(".//t:Organizer/t:Mailbox/t:Name", ns)
            if org_el is not None and org_el.text:
                organizer = org_el.text

            # Parse attendees
            attendees_data = []
            for att in item.findall(".//t:RequiredAttendees/t:Attendee", ns):
                mb = att.find("t:Mailbox", ns)
                if mb is not None:
                    att_email = ""
                    att_name = ""
                    e_el = mb.find("t:EmailAddress", ns)
                    n_el = mb.find("t:Name", ns)
                    if e_el is not None and e_el.text:
                        att_email = e_el.text
                    if n_el is not None and n_el.text:
                        att_name = n_el.text
                    resp_el = att.find("t:ResponseType", ns)
                    status = resp_el.text if resp_el is not None else "Unknown"
                    if att_email:
                        attendees_data.append({"email": att_email, "name": att_name, "status": status})

            # Parse location
            location = _text("Location")

            # Parse ItemId
            item_id_el = item.find("t:ItemId", ns)
            item_id = item_id_el.get("Id", "") if item_id_el is not None else ""

            # Parse boolean
            is_all_day = _text("IsAllDayEvent").lower() == "true"

            # Parse online meeting URL
            meeting_url = ""
            # Check for OnlineMeetingUrl or JoinUrl
            for tag in ["OnlineMeetingUrl", "JoinOnlineMeetingUrl"]:
                url_el = item.find(f"t:{tag}", ns)
                if url_el is not None and url_el.text:
                    meeting_url = url_el.text
                    break

            events.append({
                "id": item_id,
                "subject": _text("Subject"),
                "start": _text("Start"),
                "end": _text("End"),
                "location": location,
                "organizer": organizer,
                "attendees": attendees_data,
                "is_all_day": is_all_day,
                "meeting_url": meeting_url,
                "body": _text("Body"),
            })
        return events

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def list_events(
        self, start: dt.datetime, end: dt.datetime, calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        import asyncio

        start_str = start.strftime("%Y-%m-%dT%H:%M:%SZ") if start.tzinfo else start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%SZ") if end.tzinfo else end.strftime("%Y-%m-%dT%H:%M:%SZ")

        body_xml = f"""<m:FindItem Traversal="Shallow">
      <m:ItemShape>
        <t:BaseShape>Default</t:BaseShape>
        <t:AdditionalProperties>
          <t:FieldURI FieldURI="item:Subject"/>
          <t:FieldURI FieldURI="calendar:Start"/>
          <t:FieldURI FieldURI="calendar:End"/>
          <t:FieldURI FieldURI="calendar:Location"/>
          <t:FieldURI FieldURI="calendar:Organizer"/>
          <t:FieldURI FieldURI="calendar:IsAllDayEvent"/>
          <t:FieldURI FieldURI="calendar:RequiredAttendees"/>
          <t:FieldURI FieldURI="item:Body"/>
        </t:AdditionalProperties>
      </m:ItemShape>
      <m:CalendarView StartDate="{start_str}" EndDate="{end_str}"/>
      <m:ParentFolderIds>
        <t:DistinguishedFolderId Id="calendar"/>
      </m:ParentFolderIds>
    </m:FindItem>"""

        def _fetch():
            xml_text = self._soap_request(body_xml)
            raw_events = self._parse_events_xml(xml_text)
            events = []
            for raw in raw_events:
                try:
                    start_dt = dt.datetime.fromisoformat(raw["start"].replace("Z", "+00:00"))
                    end_dt = dt.datetime.fromisoformat(raw["end"].replace("Z", "+00:00"))
                except ValueError:
                    continue

                attendees = [
                    Attendee(email=a["email"], name=a.get("name", ""), status=a.get("status", ""))
                    for a in raw.get("attendees", [])
                ]
                events.append(CalendarEvent(
                    provider=self.provider,
                    provider_id=raw["id"],
                    title=raw["subject"],
                    description=raw.get("body", ""),
                    location=raw.get("location", ""),
                    start=start_dt,
                    end=end_dt,
                    all_day=raw.get("is_all_day", False),
                    attendees=attendees,
                    organizer=raw.get("organizer", ""),
                    is_online=bool(raw.get("meeting_url")),
                    meeting_url=raw.get("meeting_url", ""),
                    calendar_name=calendar_name or "Exchange",
                ))
            return events

        return await asyncio.to_thread(_fetch)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        import asyncio

        start_str = event.start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = event.end.strftime("%Y-%m-%dT%H:%M:%SZ")

        attendees_xml = ""
        if event.attendees:
            attendees_xml = "<t:RequiredAttendees>"
            for a in event.attendees:
                attendees_xml += f"""<t:Attendee><t:Mailbox>
                    <t:EmailAddress>{a.email}</t:EmailAddress>
                    </t:Mailbox></t:Attendee>"""
            attendees_xml += "</t:RequiredAttendees>"

        body_xml = f"""<m:CreateItem SendMeetingInvitations="SendToAllAndSaveCopy">
      <m:Items>
        <t:CalendarItem>
          <t:Subject>{event.title}</t:Subject>
          <t:Body BodyType="Text">{event.description}</t:Body>
          <t:Start>{start_str}</t:Start>
          <t:End>{end_str}</t:End>
          <t:Location>{event.location}</t:Location>
          {attendees_xml}
        </t:CalendarItem>
      </m:Items>
    </m:CreateItem>"""

        def _create():
            xml_text = self._soap_request(body_xml)
            # Extract ItemId from response
            import xml.etree.ElementTree as ET
            ns = {"t": "http://schemas.microsoft.com/exchange/services/2006/types"}
            root = ET.fromstring(xml_text)
            item_id_el = root.find(".//t:ItemId", ns)
            return item_id_el.get("Id", "") if item_id_el is not None else ""

        provider_id = await asyncio.to_thread(_create)
        event.provider_id = provider_id
        event.provider = self.provider
        return event

    async def update_event(self, event: CalendarEvent) -> CalendarEvent:
        logger.warning("ews_update_not_fully_implemented")
        return event

    async def delete_event(self, event_id: str) -> bool:
        import asyncio

        body_xml = f"""<m:DeleteItem DeleteType="MoveToDeletedItems"
                                     SendMeetingCancellations="SendToAllAndSaveCopy">
      <m:ItemIds>
        <t:ItemId Id="{event_id}"/>
      </m:ItemIds>
    </m:DeleteItem>"""

        def _delete():
            self._soap_request(body_xml)
            return True

        return await asyncio.to_thread(_delete)

    async def list_calendars(self) -> list[str]:
        """List calendar folders via EWS FindFolder."""
        import asyncio

        body_xml = """<m:FindFolder Traversal="Deep">
      <m:FolderShape>
        <t:BaseShape>Default</t:BaseShape>
      </m:FolderShape>
      <m:Restriction>
        <t:IsEqualTo>
          <t:FieldURI FieldURI="folder:FolderClass"/>
          <t:FieldURIOrConstant>
            <t:Constant Value="IPF.Appointment"/>
          </t:FieldURIOrConstant>
        </t:IsEqualTo>
      </m:Restriction>
      <m:ParentFolderIds>
        <t:DistinguishedFolderId Id="msgfolderroot"/>
      </m:ParentFolderIds>
    </m:FindFolder>"""

        def _list():
            import xml.etree.ElementTree as ET
            xml_text = self._soap_request(body_xml)
            ns = {"t": "http://schemas.microsoft.com/exchange/services/2006/types"}
            root = ET.fromstring(xml_text)
            names = []
            for folder in root.findall(".//t:CalendarFolder", ns):
                name_el = folder.find("t:DisplayName", ns)
                if name_el is not None and name_el.text:
                    names.append(name_el.text)
            return names or ["Calendar"]

        return await asyncio.to_thread(_list)


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

    def _get_service(self, force_refresh: bool = False):
        """Lazy-init Google Calendar service with automatic token refresh.
        
        Args:
            force_refresh: If True, refresh the token even if it appears valid.
        """
        from pathlib import Path
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        SCOPES = [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/drive.file",
        ]

        token_path = Path(self._token_file)
        needs_rebuild = force_refresh or self._service is None

        if not needs_rebuild:
            return self._service

        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                print("[Google] Refreshing expired token...")
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
                print("[Google] Token refreshed and saved")
            elif not creds:
                raise RuntimeError(
                    "Google token not found. Re-authenticate via dashboard."
                )
            else:
                raise RuntimeError(
                    "Google token expired and no refresh token. Re-authenticate via dashboard."
                )

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    async def refresh_token(self) -> bool:
        """Proactively refresh the Google OAuth token to keep it alive."""
        try:
            self._service = None  # Force rebuild
            self._get_service(force_refresh=True)
            return True
        except Exception as exc:
            print(f"[Google] Token refresh failed: {exc}")
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def list_events(
        self, start: dt.datetime, end: dt.datetime, calendar_name: Optional[str] = None,
    ) -> list[CalendarEvent]:
        import asyncio

        service = self._get_service()

        def _fetch():
            # Convert to naive UTC for Google API (RFC3339 with Z suffix)
            start_utc = start.replace(tzinfo=None) if start.tzinfo else start
            end_utc = end.replace(tzinfo=None) if end.tzinfo else end
            time_min = start_utc.isoformat() + "Z"
            time_max = end_utc.isoformat() + "Z"

            # If a specific calendar is requested, use it; otherwise fetch from ALL calendars
            if calendar_name:
                cal_ids = [calendar_name]
            else:
                cal_list = service.calendarList().list().execute()
                cal_ids = [c["id"] for c in cal_list.get("items", [])]
                if not cal_ids:
                    cal_ids = ["primary"]

            all_events = []
            for cal_id in cal_ids:
                try:
                    # Get calendar display name
                    cal_summary = cal_id
                    try:
                        cal_info = service.calendarList().get(calendarId=cal_id).execute()
                        cal_summary = cal_info.get("summary", cal_id)
                    except Exception:
                        pass

                    result = service.events().list(
                        calendarId=cal_id,
                        timeMin=time_min,
                        timeMax=time_max,
                        singleEvents=True,
                        orderBy="startTime",
                    ).execute()
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
                        all_events.append(CalendarEvent(
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
                            calendar_name=cal_summary,
                        ))
                except Exception as exc:
                    print(f"[Google Calendar] Error fetching from {cal_id}: {exc}")
            return all_events

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
