"""API route definitions for ExecutiveAI."""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from executiveai.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


# ── Request / Response Models ────────────────────────────────────────

class ChatRequest(BaseModel):
    """Chat message request."""

    message: str
    user_id: str = "default"
    channel: str = "api"


class ChatResponse(BaseModel):
    """Chat message response."""

    response: str
    intent: str = ""
    entities: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    tokens_used: int = 0
    model: str = ""


class EventRequest(BaseModel):
    """Calendar event creation request."""

    title: str
    start: str
    end: str
    description: str = ""
    location: str = ""
    attendees: list[str] = Field(default_factory=list)
    prep_minutes: int = 15


class EmailRequest(BaseModel):
    """Email send request."""

    to: list[str]
    subject: str
    body_text: str = ""
    body_html: str = ""
    cc: list[str] = Field(default_factory=list)


class DocumentRequest(BaseModel):
    """Document generation request."""

    title: str
    doc_type: str = "docx"
    content: list[dict[str, Any]] = Field(default_factory=list)
    sheets: dict[str, list[list[Any]]] = Field(default_factory=dict)
    filename: str = "document"


class ImageRequest(BaseModel):
    """Image generation request."""

    prompt: str
    size: str = "1024x1024"
    quality: str = "standard"
    n: int = 1


class MemoryRequest(BaseModel):
    """Memory storage request."""

    user_id: str = "default"
    category: str
    content: str
    importance: float = 0.5


class PluginRequest(BaseModel):
    """Plugin generation request."""

    capability: str
    description: str


# ── Orchestrator accessor (set from main.py) ────────────────────────

_orchestrator = None


def set_orchestrator(orch: Any) -> None:
    """Inject the orchestrator instance."""
    global _orchestrator
    _orchestrator = orch


def get_orchestrator():
    """Get the orchestrator, raising if not initialized."""
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="System not initialized")
    return _orchestrator


# ── Health ───────────────────────────────────────────────────────────

@router.get("/health")
async def health_check() -> dict[str, Any]:
    """System health check."""
    orch = get_orchestrator()
    return {
        "status": "healthy",
        "calendar_providers": [str(p) for p in orch.calendar.active_providers],
        "llm_providers": [str(p) for p in orch.llm.available_providers],
        "email_imap": orch.email.imap_configured,
        "email_smtp": orch.email.smtp_configured,
        "telegram": orch.telegram.is_configured,
        "whatsapp": orch.whatsapp.is_configured,
        "plugins_loaded": len(orch.self_improve.list_plugins()),
        "scheduled_tasks": len(orch.scheduler.list_tasks()),
    }


# ── Chat ─────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a natural language message."""
    orch = get_orchestrator()
    result = await orch.process_message(request.user_id, request.message, request.channel)
    return ChatResponse(**result)


# ── Calendar ─────────────────────────────────────────────────────────

@router.get("/calendar/events")
async def list_events(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    days: int = Query(7),
) -> list[dict[str, Any]]:
    """List calendar events."""
    orch = get_orchestrator()
    start_dt = dt.datetime.fromisoformat(start) if start else dt.datetime.utcnow()
    end_dt = dt.datetime.fromisoformat(end) if end else start_dt + dt.timedelta(days=days)
    events = await orch.calendar.list_events(start_dt, end_dt)
    return [
        {
            "id": e.id, "title": e.title, "start": e.start.isoformat(),
            "end": e.end.isoformat(), "location": e.location,
            "provider": str(e.provider) if e.provider else None,
        }
        for e in events
    ]


@router.post("/calendar/events")
async def create_event(request: EventRequest) -> dict[str, Any]:
    """Create a calendar event with optional prep time."""
    orch = get_orchestrator()
    from executiveai.modules.calendar.models import Attendee

    event = CalendarEvent(
        title=request.title,
        start=dt.datetime.fromisoformat(request.start),
        end=dt.datetime.fromisoformat(request.end),
        description=request.description,
        location=request.location,
        attendees=[Attendee(email=a) for a in request.attendees],
    )
    created, prep = await orch.calendar.schedule_with_prep(event, request.prep_minutes)
    return {
        "event": {"id": created.id, "title": created.title, "provider_id": created.provider_id},
        "prep_event": {"id": prep.id, "title": prep.title} if prep else None,
    }


@router.get("/calendar/calendars")
async def list_calendars() -> dict[str, list[str]]:
    """List all available calendars."""
    orch = get_orchestrator()
    result = await orch.calendar.list_all_calendars()
    return {str(k): v for k, v in result.items()}


# ── Email ────────────────────────────────────────────────────────────

@router.get("/email/inbox")
async def get_inbox(
    unread_only: bool = Query(False),
    limit: int = Query(20),
) -> list[dict[str, Any]]:
    """Fetch inbox emails."""
    orch = get_orchestrator()
    from executiveai.modules.email.models import EmailFilter

    emails = await orch.email.fetch_emails(EmailFilter(unread_only=unread_only, limit=limit))
    return [
        {
            "id": e.id, "subject": e.subject, "sender": e.sender,
            "date": e.date.isoformat(), "is_read": e.is_read,
            "has_attachments": e.has_attachments,
        }
        for e in emails
    ]


@router.post("/email/send")
async def send_email(request: EmailRequest) -> dict[str, bool]:
    """Send an email."""
    orch = get_orchestrator()
    from executiveai.modules.email.models import EmailMessage as EM

    msg = EM(
        subject=request.subject,
        recipients=request.to,
        cc=request.cc,
        body_text=request.body_text,
        body_html=request.body_html,
    )
    success = await orch.email.send_email(msg)
    return {"sent": success}


# ── Documents ────────────────────────────────────────────────────────

@router.post("/documents/generate")
async def generate_document(request: DocumentRequest) -> dict[str, str]:
    """Generate a document (DOCX, XLSX, PDF)."""
    orch = get_orchestrator()
    output = f"data/generated/{request.filename}.{request.doc_type}"

    if request.doc_type == "docx":
        path = orch.documents.generate_docx(request.title, request.content, output)
    elif request.doc_type == "xlsx":
        path = orch.documents.generate_xlsx(request.title, request.sheets, output)
    elif request.doc_type == "pdf":
        path = orch.documents.generate_pdf(request.title, request.content, output)
    else:
        raise HTTPException(400, f"Unsupported doc type: {request.doc_type}")

    return {"path": path}


# ── Images ───────────────────────────────────────────────────────────

@router.post("/images/generate")
async def generate_image(request: ImageRequest) -> dict[str, list[str]]:
    """Generate images from a prompt."""
    orch = get_orchestrator()
    urls = await orch.images.generate(
        request.prompt, request.size, request.quality, request.n,
    )
    return {"images": urls}


@router.post("/images/analyze")
async def analyze_image(image_url: str, prompt: str = "Describe this image.") -> dict[str, str]:
    """Analyze an image using vision AI."""
    orch = get_orchestrator()
    result = await orch.images.analyze(image_url, prompt)
    return {"analysis": result}


# ── Memory ───────────────────────────────────────────────────────────

@router.post("/memory/store")
async def store_memory(request: MemoryRequest) -> dict[str, str]:
    """Store a memory entry."""
    orch = get_orchestrator()
    entry = await orch.memory.store_memory(
        request.user_id, request.category, request.content, request.importance,
    )
    return {"id": entry.id, "status": "stored"}


@router.get("/memory/search")
async def search_memory(
    query: str,
    user_id: str = "default",
    n: int = Query(5),
) -> list[dict[str, Any]]:
    """Search memory using semantic search."""
    orch = get_orchestrator()
    return orch.memory.recall(query, user_id=user_id, n=n)


# ── Plugins / Self-Improvement ───────────────────────────────────────

@router.get("/plugins")
async def list_plugins() -> list[dict[str, Any]]:
    """List loaded plugins."""
    orch = get_orchestrator()
    return orch.self_improve.list_plugins()


@router.get("/capabilities")
async def list_capabilities() -> dict[str, str]:
    """List all known capabilities."""
    orch = get_orchestrator()
    return orch.self_improve.list_capabilities()


@router.post("/plugins/generate")
async def generate_plugin(request: PluginRequest) -> dict[str, Any]:
    """Generate a new plugin for a missing capability."""
    orch = get_orchestrator()
    path = await orch.self_improve.generate_plugin(request.capability, request.description)
    return {"path": path, "status": "generated_and_loaded"}


# ── Scheduler ────────────────────────────────────────────────────────

@router.get("/scheduler/tasks")
async def list_tasks() -> list[dict[str, Any]]:
    """List scheduled tasks."""
    orch = get_orchestrator()
    return [
        {
            "id": t.task_id, "name": t.name, "type": t.task_type,
            "schedule": t.schedule_info, "run_count": t.run_count,
            "last_run": t.last_run.isoformat() if t.last_run else None,
        }
        for t in orch.scheduler.list_tasks()
    ]


# Import needed for type reference in create_event
from executiveai.modules.calendar.models import CalendarEvent
