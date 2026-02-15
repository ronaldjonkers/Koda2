"""API route definitions for Koda2."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, UploadFile, File
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from koda2.logging_config import get_logger

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
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    iterations: int = 0
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
    account_name: str = ""  # Target a specific calendar account by name


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
    cal_providers = await orch.calendar.active_providers()
    imap_configured = await orch.email.imap_configured()
    smtp_configured = await orch.email.smtp_configured()
    tg_configured = await orch.telegram.is_configured()
    return {
        "status": "healthy",
        "calendar_providers": [str(p) for p in cal_providers],
        "llm_providers": [str(p) for p in orch.llm.available_providers],
        "email_imap": imap_configured,
        "email_smtp": smtp_configured,
        "telegram": tg_configured,
        "whatsapp": orch.whatsapp.is_configured,
        "plugins_loaded": len(orch.self_improve.list_plugins()),
        "scheduled_tasks": len(orch.scheduler.list_tasks()),
    }


# ── Supervisor ───────────────────────────────────────────────────────

@router.get("/supervisor/status")
async def supervisor_status() -> dict[str, Any]:
    """Get self-healing supervisor status, repair state, and recent audit log."""
    import json as _json
    from koda2.supervisor.safety import AUDIT_LOG_FILE, REPAIR_STATE_FILE

    result: dict[str, Any] = {"supervisor": "available"}

    # Repair state
    if REPAIR_STATE_FILE.exists():
        try:
            state = _json.loads(REPAIR_STATE_FILE.read_text())
            result["repair_counts"] = state.get("repair_counts", {})
            result["last_updated"] = state.get("updated_at")
        except Exception:
            result["repair_counts"] = {}
    else:
        result["repair_counts"] = {}

    # Learner state
    from pathlib import Path as _Path
    learner_state_file = _Path("data/supervisor/learner_state.json")
    if learner_state_file.exists():
        try:
            ls = _json.loads(learner_state_file.read_text())
            result["learner"] = {
                "cycle_count": ls.get("cycle_count", 0),
                "improvements_applied": len(ls.get("improvements_applied", [])),
                "failed_ideas": len(ls.get("failed_ideas", [])),
                "recent_improvements": ls.get("improvements_applied", [])[-5:],
                "last_updated": ls.get("updated_at"),
            }
        except Exception:
            result["learner"] = {"cycle_count": 0}
    else:
        result["learner"] = {"cycle_count": 0}

    # Recent audit entries
    if AUDIT_LOG_FILE.exists():
        try:
            lines = AUDIT_LOG_FILE.read_text().strip().splitlines()
            recent = lines[-20:] if len(lines) > 20 else lines
            result["audit_total"] = len(lines)
            result["audit_recent"] = [_json.loads(l) for l in recent]
        except Exception:
            result["audit_total"] = 0
            result["audit_recent"] = []
    else:
        result["audit_total"] = 0
        result["audit_recent"] = []

    return result


@router.post("/supervisor/improve")
async def supervisor_improve(request: dict[str, Any]) -> dict[str, Any]:
    """Queue a self-improvement request. Processed chronologically in background."""
    description = request.get("request", request.get("description", ""))
    if not description:
        return {"error": "No improvement request provided"}

    from koda2.supervisor.improvement_queue import get_improvement_queue

    queue = get_improvement_queue()
    priority = request.get("priority", 5)
    item = queue.add(description, source="user", priority=priority)

    # Start worker if not running
    if not queue.is_running:
        queue.start_worker()

    return {
        "queued": True,
        "item": item,
        "position": queue.pending_count(),
        "message": f"Improvement queued (#{item['id']}). Processing in background.",
    }


@router.get("/supervisor/queue")
async def supervisor_queue(
    status: Optional[str] = Query(None),
    limit: int = Query(50),
) -> dict[str, Any]:
    """Get the improvement queue status and items."""
    from koda2.supervisor.improvement_queue import get_improvement_queue

    queue = get_improvement_queue()
    items = queue.list_items(status=status, limit=limit)
    return {
        "stats": queue.stats(),
        "worker_running": queue.is_running,
        "items": items,
    }


@router.get("/supervisor/queue/{item_id}")
async def supervisor_queue_item(item_id: str) -> dict[str, Any]:
    """Get full detail of a single queue item (including error_details, plan, etc.)."""
    from koda2.supervisor.improvement_queue import get_improvement_queue

    queue = get_improvement_queue()
    item = queue.get_item(item_id)
    if not item:
        raise HTTPException(404, "Queue item not found")
    return item


@router.post("/supervisor/queue/{item_id}/cancel")
async def supervisor_queue_cancel(item_id: str) -> dict[str, Any]:
    """Cancel a pending queue item."""
    from koda2.supervisor.improvement_queue import get_improvement_queue

    queue = get_improvement_queue()
    success = queue.cancel_item(item_id)
    if not success:
        raise HTTPException(404, "Item not found or not cancellable")
    return {"cancelled": True, "item_id": item_id}


@router.post("/supervisor/queue/start")
async def supervisor_queue_start(request: dict[str, Any] = {}) -> dict[str, Any]:
    """Start the improvement queue workers."""
    from koda2.supervisor.improvement_queue import get_improvement_queue

    queue = get_improvement_queue()
    if request.get("max_workers"):
        queue.max_workers = int(request["max_workers"])
    if queue.is_running:
        return {"status": "already_running", "workers": queue.max_workers}
    queue.start_worker()
    return {"status": "started", "workers": queue.max_workers}


@router.post("/supervisor/queue/stop")
async def supervisor_queue_stop() -> dict[str, Any]:
    """Stop all improvement queue workers."""
    from koda2.supervisor.improvement_queue import get_improvement_queue

    queue = get_improvement_queue()
    queue.stop_worker()
    return {"status": "stopped"}


@router.post("/supervisor/learn")
async def supervisor_learn() -> dict[str, Any]:
    """Trigger one learning cycle: analyze logs + conversations and auto-improve."""
    from koda2.supervisor.safety import SafetyGuard
    from koda2.supervisor.learner import ContinuousLearner

    safety = SafetyGuard()
    learner = ContinuousLearner(safety)
    summary = await learner.run_cycle()
    return summary


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
    start_dt = dt.datetime.fromisoformat(start) if start else dt.datetime.now(dt.UTC)
    end_dt = dt.datetime.fromisoformat(end) if end else start_dt + dt.timedelta(days=days)
    events = await orch.calendar.list_events(start_dt, end_dt)
    return [
        {
            "id": e.id, "title": e.title, "start": e.start.isoformat(),
            "end": e.end.isoformat(), "location": e.location,
            "description": e.description,
            "calendar_name": e.calendar_name,
            "organizer": e.organizer,
            "is_online": e.is_online,
            "meeting_url": e.meeting_url,
            "provider": str(e.provider) if e.provider else None,
            "attendees": [{"name": a.name, "email": a.email, "status": a.status} for a in e.attendees],
        }
        for e in events
    ]


@router.post("/calendar/sync")
async def sync_calendar() -> dict[str, Any]:
    """Trigger a manual calendar sync from remote providers to local cache."""
    orch = get_orchestrator()
    results = await orch.calendar.sync_all()
    total = sum(v for v in results.values() if v >= 0)
    return {"status": "ok", "total_events": total, "accounts": results}


@router.post("/calendar/events")
async def create_event(request: EventRequest) -> dict[str, Any]:
    """Create a calendar event with optional prep time."""
    orch = get_orchestrator()
    from koda2.modules.calendar.models import Attendee

    event = CalendarEvent(
        title=request.title,
        start=dt.datetime.fromisoformat(request.start),
        end=dt.datetime.fromisoformat(request.end),
        description=request.description,
        location=request.location,
        attendees=[Attendee(email=a) for a in request.attendees],
    )
    account_name = request.account_name or None
    created, prep = await orch.calendar.schedule_with_prep(event, request.prep_minutes, account_name=account_name)
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
    from koda2.modules.email.models import EmailFilter

    emails = await orch.email.fetch_all_emails(unread_only=unread_only, limit=limit)
    return [
        {
            "id": e.id, "subject": e.subject, "sender": e.sender,
            "date": e.date.isoformat() if e.date else "",
            "is_read": e.is_read,
            "has_attachments": e.has_attachments,
            "account": e.account_name or "",
            "provider": e.provider.value if e.provider else "unknown",
        }
        for e in emails
    ]


@router.post("/email/send")
async def send_email(request: EmailRequest) -> dict[str, bool]:
    """Send an email."""
    orch = get_orchestrator()
    from koda2.modules.email.models import EmailMessage as EM

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


@router.get("/memory/list")
async def list_memories(
    user_id: str = "default",
    category: Optional[str] = None,
    limit: int = Query(50),
) -> list[dict[str, Any]]:
    """List all stored memories for a user."""
    orch = get_orchestrator()
    entries = await orch.memory.list_memories(user_id, category=category, limit=limit)
    return [{
        "id": e.id,
        "category": e.category,
        "content": e.content,
        "importance": e.importance,
        "source": e.source,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    } for e in entries]


@router.get("/memory/stats")
async def memory_stats(user_id: str = "default") -> dict[str, Any]:
    """Get memory statistics."""
    orch = get_orchestrator()
    return await orch.memory.get_memory_stats(user_id)


@router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str) -> dict[str, Any]:
    """Delete a memory entry."""
    orch = get_orchestrator()
    success = await orch.memory.delete_memory(memory_id)
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": True, "id": memory_id}


# ── Webhooks ──────────────────────────────────────────────────────────

class WebhookPayload(BaseModel):
    """Incoming webhook payload."""
    event: str = ""
    source: str = ""
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    notify_channel: str = ""  # "whatsapp", "telegram", or "" for no notification
    notify_to: str = ""  # recipient for notification


@router.post("/webhook/{hook_id}")
async def receive_webhook(hook_id: str, payload: WebhookPayload) -> dict[str, Any]:
    """Receive an external webhook and optionally trigger the agent.

    Examples:
        POST /api/webhook/github  {"event": "push", "source": "github", "message": "New push to main by ronald"}
        POST /api/webhook/stripe  {"event": "payment", "data": {"amount": 100}, "notify_channel": "whatsapp", "notify_to": "me"}
    """
    orch = get_orchestrator()
    logger.info("webhook_received", hook_id=hook_id, event=payload.event, source=payload.source)

    # Store as memory
    content = f"Webhook [{hook_id}] {payload.event}: {payload.message}" if payload.message else f"Webhook [{hook_id}] {payload.event}"
    await orch.memory.store_memory(
        "default", "webhook", content, importance=0.6, source=f"webhook:{hook_id}",
    )

    result: dict[str, Any] = {"received": True, "hook_id": hook_id, "event": payload.event}

    # If a message is provided, process it through the agent
    if payload.message:
        agent_result = await orch.process_message(
            "default", f"[Webhook {hook_id}/{payload.event}] {payload.message}", channel="webhook",
        )
        result["agent_response"] = agent_result.get("response", "")

    # Optionally notify via a channel
    if payload.notify_channel and (payload.message or payload.event):
        notify_text = payload.message or f"Webhook: {payload.event} from {payload.source}"
        if result.get("agent_response"):
            notify_text = result["agent_response"]
        to = payload.notify_to or "me"
        try:
            if payload.notify_channel == "whatsapp" and orch.whatsapp.is_configured:
                await orch.whatsapp.send_message(to, notify_text)
                result["notified"] = "whatsapp"
            elif payload.notify_channel == "telegram" and orch.telegram.is_configured:
                await orch.telegram.send_message(to, notify_text)
                result["notified"] = "telegram"
        except Exception as exc:
            result["notify_error"] = str(exc)

    return result


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


# ── WhatsApp ─────────────────────────────────────────────────────────

@router.get("/whatsapp/status")
async def whatsapp_status() -> dict[str, Any]:
    """Get WhatsApp connection status."""
    orch = get_orchestrator()
    return await orch.whatsapp.get_status()


@router.get("/whatsapp/qr")
async def whatsapp_qr() -> dict[str, Any]:
    """Get QR code for WhatsApp pairing."""
    orch = get_orchestrator()
    return await orch.whatsapp.get_qr()


@router.post("/whatsapp/send")
async def whatsapp_send(to: str, message: str) -> dict[str, Any]:
    """Send a WhatsApp message to any number."""
    orch = get_orchestrator()
    return await orch.whatsapp.send_message(to, message)


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Receive incoming WhatsApp messages from the bridge."""
    from_me = payload.get("fromMe", False)
    is_self = payload.get("isToSelf", False)
    body = payload.get("body", "")
    sender = payload.get("from", "unknown")
    print(f"[WhatsApp webhook] from={sender} fromMe={from_me} isToSelf={is_self}: {body[:80]}")
    orch = get_orchestrator()
    response = await orch.handle_whatsapp_message(payload)
    return {"processed": response is not None, "response": response}


@router.post("/whatsapp/logout")
async def whatsapp_logout() -> dict[str, Any]:
    """Disconnect WhatsApp session."""
    orch = get_orchestrator()
    return await orch.whatsapp.logout()


# ── Agent Mode ───────────────────────────────────────────────────────

class AgentTaskRequest(BaseModel):
    """Request to create an agent task."""
    request: str
    auto_start: bool = True


class AgentClarificationRequest(BaseModel):
    """Request to provide clarification for an agent task."""
    answers: dict[str, str]


@router.post("/agent/tasks")
async def create_agent_task(
    req: AgentTaskRequest,
    user_id: str = "default",
) -> dict[str, Any]:
    """Create and start an autonomous agent task."""
    orch = get_orchestrator()
    task = await orch.agent.create_task(
        user_id=user_id,
        request=req.request,
        auto_start=req.auto_start,
    )
    return task.to_dict()


@router.get("/agent/tasks")
async def list_agent_tasks(
    user_id: str = "default",
    status: Optional[str] = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List agent tasks for a user."""
    orch = get_orchestrator()
    from koda2.modules.agent.models import AgentStatus
    
    task_status = AgentStatus(status) if status else None
    tasks = await orch.agent.list_tasks(
        user_id=user_id,
        status=task_status,
        limit=limit,
    )
    return {
        "tasks": [t.to_dict() for t in tasks],
        "total": len(tasks),
    }


@router.get("/agent/tasks/{task_id}")
async def get_agent_task(task_id: str) -> dict[str, Any]:
    """Get details of a specific agent task."""
    orch = get_orchestrator()
    task = await orch.agent.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Agent task not found")
    return task.to_dict()


@router.post("/agent/tasks/{task_id}/cancel")
async def cancel_agent_task(task_id: str) -> dict[str, Any]:
    """Cancel a running or pending agent task."""
    orch = get_orchestrator()
    try:
        task = await orch.agent.cancel_task(task_id)
        return {"cancelled": True, "task": task.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/agent/tasks/{task_id}/pause")
async def pause_agent_task(task_id: str) -> dict[str, Any]:
    """Pause a running agent task."""
    orch = get_orchestrator()
    try:
        task = await orch.agent.pause_task(task_id)
        return {"paused": True, "task": task.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agent/tasks/{task_id}/resume")
async def resume_agent_task(task_id: str) -> dict[str, Any]:
    """Resume a paused agent task."""
    orch = get_orchestrator()
    try:
        task = await orch.agent.resume_task(task_id)
        return {"resumed": True, "task": task.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/agent/tasks/{task_id}/clarify")
async def provide_clarification(
    task_id: str,
    req: AgentClarificationRequest,
) -> dict[str, Any]:
    """Provide clarification for a waiting agent task."""
    orch = get_orchestrator()
    try:
        task = await orch.agent.provide_clarification(task_id, req.answers)
        return {"clarified": True, "task": task.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Scheduler ────────────────────────────────────────────────────────

@router.get("/scheduler/tasks")
async def list_scheduled_tasks() -> list[dict[str, Any]]:
    """List scheduled tasks with next run time."""
    orch = get_orchestrator()
    results = []
    for t in orch.scheduler.list_tasks():
        # Try to get next run time from APScheduler
        next_run = None
        try:
            job = orch.scheduler._scheduler.get_job(t.task_id)
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()
        except Exception:
            pass
        results.append({
            "id": t.task_id, "name": t.name, "type": t.task_type,
            "schedule": t.schedule_info, "func_name": t.func_name,
            "run_count": t.run_count,
            "last_run": t.last_run.isoformat() if t.last_run else None,
            "next_run": next_run,
            "created_at": t.created_at.isoformat(),
        })
    return results


@router.post("/scheduler/tasks/{task_id}/trigger")
async def trigger_scheduled_task(task_id: str) -> dict[str, Any]:
    """Manually trigger a scheduled task immediately (keeps its regular schedule)."""
    orch = get_orchestrator()
    try:
        success = await orch.scheduler.run_now(task_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Task execution failed: {exc}")
    if not success:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"triggered": True, "task_id": task_id}


@router.delete("/scheduler/tasks/{task_id}")
async def cancel_scheduled_task(task_id: str) -> dict[str, Any]:
    """Cancel a scheduled task."""
    orch = get_orchestrator()
    success = orch.scheduler.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"cancelled": True, "task_id": task_id}


# ── Commands ─────────────────────────────────────────────────────────

@router.get("/commands")
async def list_commands(
    category: Optional[str] = None,
    search: Optional[str] = None,
) -> dict[str, Any]:
    """List all available assistant commands/actions."""
    orch = get_orchestrator()
    
    if search:
        commands = orch.commands.search(search)
    elif category:
        commands = orch.commands.list_by_category(category)
    else:
        commands = orch.commands.list_all()
    
    return {
        "commands": [c.to_dict() for c in commands],
        "total": len(commands),
        "categories": orch.commands.categories(),
    }


@router.get("/commands/{command_name}")
async def get_command(command_name: str) -> dict[str, Any]:
    """Get detailed info about a specific command."""
    orch = get_orchestrator()
    command = orch.commands.get(command_name)
    
    if not command:
        raise HTTPException(status_code=404, detail=f"Command '{command_name}' not found")
    
    return command.to_dict()


@router.get("/commands/categories")
async def list_command_categories() -> dict[str, Any]:
    """List all command categories."""
    orch = get_orchestrator()
    return {
        "categories": orch.commands.categories(),
    }


# ── Task Queue ───────────────────────────────────────────────────────

@router.get("/tasks")
async def list_queued_tasks(
    status: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List tasks from the async task queue."""
    orch = get_orchestrator()
    from koda2.modules.task_queue import TaskStatus
    task_status = TaskStatus(status) if status else None
    tasks = await orch.task_queue.list_tasks(status=task_status, limit=limit)
    return [t.to_dict() for t in tasks]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    """Get details of a specific task."""
    orch = get_orchestrator()
    task = await orch.task_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task.to_dict()


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, Any]:
    """Cancel a pending or running task."""
    orch = get_orchestrator()
    success = await orch.task_queue.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Task not found or cannot be cancelled")
    return {"cancelled": True, "task_id": task_id}


# ── Travel ───────────────────────────────────────────────────────────

@router.get("/travel/search-flights")
async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: Optional[str] = None,
) -> dict[str, Any]:
    """Search for flights."""
    orch = get_orchestrator()
    dep = dt.datetime.strptime(departure_date, "%Y-%m-%d").date()
    ret = dt.datetime.strptime(return_date, "%Y-%m-%d").date() if return_date else None
    
    result = await orch.travel.search_flights(origin, destination, dep, ret)
    return {
        "success": result.success,
        "flights": [f.model_dump() for f in result.data] if result.success else [],
        "error": result.error,
    }


@router.get("/travel/search-hotels")
async def search_hotels(
    destination: str,
    check_in: str,
    check_out: str,
) -> dict[str, Any]:
    """Search for hotels."""
    orch = get_orchestrator()
    check_in_date = dt.datetime.strptime(check_in, "%Y-%m-%d").date()
    check_out_date = dt.datetime.strptime(check_out, "%Y-%m-%d").date()
    
    result = await orch.travel.search_hotels(destination, check_in_date, check_out_date)
    return {
        "success": result.success,
        "hotels": [h.model_dump() for h in result.data] if result.success else [],
        "error": result.error,
    }


# ── Meetings ─────────────────────────────────────────────────────────

@router.post("/meetings/create")
async def create_meeting(
    title: str,
    scheduled_start: str,
    scheduled_end: str,
    organizer: str,
    description: str = "",
) -> dict[str, Any]:
    """Create a new meeting."""
    orch = get_orchestrator()
    start = dt.datetime.fromisoformat(scheduled_start)
    end = dt.datetime.fromisoformat(scheduled_end)
    
    meeting = await orch.meetings.create_meeting(
        title=title,
        scheduled_start=start,
        scheduled_end=end,
        organizer=organizer,
        description=description,
    )
    return {"meeting_id": meeting.id, "status": "created"}


@router.post("/meetings/transcribe")
async def transcribe_meeting(
    meeting_id: str,
    audio_path: str,
) -> dict[str, Any]:
    """Transcribe meeting audio."""
    orch = get_orchestrator()
    meeting = orch.meetings.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    
    result = await orch.meetings.transcribe_audio(audio_path)
    if result["success"]:
        await orch.meetings.process_transcript(meeting, result["transcript"], result.get("segments"))
    
    return result


@router.get("/meetings/{meeting_id}/minutes")
async def get_meeting_minutes(meeting_id: str) -> dict[str, Any]:
    """Generate meeting minutes PDF."""
    orch = get_orchestrator()
    meeting = orch.meetings.get_meeting(meeting_id)
    if not meeting:
        raise HTTPException(404, "Meeting not found")
    
    pdf_path = await orch.meetings.generate_minutes_pdf(meeting)
    return {"pdf_path": pdf_path}


@router.get("/meetings/action-items")
async def get_action_items() -> list[dict[str, Any]]:
    """Get all pending action items."""
    orch = get_orchestrator()
    items = orch.meetings.get_pending_action_items()
    return [
        {
            "id": item.id,
            "description": item.description,
            "assignee": item.assignee,
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "status": item.status.value,
            "priority": item.priority,
        }
        for item in items
    ]


# ── Expenses ─────────────────────────────────────────────────────────

@router.post("/expenses/process-receipt")
async def process_receipt(
    image_path: str,
    submitted_by: str,
    project_code: Optional[str] = None,
) -> dict[str, Any]:
    """Process a receipt image."""
    orch = get_orchestrator()
    expense = await orch.expenses.process_receipt(image_path, submitted_by, project_code)
    return expense.model_dump()


@router.post("/expenses/create-report")
async def create_expense_report(
    title: str,
    employee_name: str,
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
    """Create expense report."""
    orch = get_orchestrator()
    start = dt.datetime.strptime(period_start, "%Y-%m-%d").date()
    end = dt.datetime.strptime(period_end, "%Y-%m-%d").date()
    
    report = await orch.expenses.create_report(title, employee_name, start, end)
    return {"report_id": report.id, "status": "created"}


@router.post("/expenses/{report_id}/export")
async def export_expense_report(report_id: str) -> dict[str, str]:
    """Export expense report to Excel."""
    orch = get_orchestrator()
    report = orch.expenses.get_report(report_id)
    if not report:
        raise HTTPException(404, "Report not found")
    
    excel_path = await orch.expenses.export_to_excel(report)
    return {"excel_path": excel_path}


# ── Facilities ───────────────────────────────────────────────────────

@router.get("/facilities/venues")
async def list_venues(
    min_capacity: int = 0,
    internal_only: bool = False,
) -> list[dict[str, Any]]:
    """List available venues."""
    orch = get_orchestrator()
    venues = orch.facilities.list_venues(min_capacity=min_capacity, internal_only=internal_only)
    return [
        {
            "id": v.id,
            "name": v.name,
            "type": v.venue_type.value,
            "capacity": v.max_capacity,
            "equipment": [e.value for e in v.equipment],
        }
        for v in venues
    ]


@router.post("/facilities/book-room")
async def book_room(
    venue_id: str,
    meeting_title: str,
    organizer_name: str,
    organizer_email: str,
    start_time: str,
    end_time: str,
    expected_attendees: int,
) -> dict[str, Any]:
    """Book a meeting room."""
    orch = get_orchestrator()
    start = dt.datetime.fromisoformat(start_time)
    end = dt.datetime.fromisoformat(end_time)
    
    booking = await orch.facilities.book_room(
        venue_id=venue_id,
        meeting_title=meeting_title,
        organizer_name=organizer_name,
        organizer_email=organizer_email,
        start_time=start,
        end_time=end,
        expected_attendees=expected_attendees,
    )
    return {"booking_id": booking.id, "status": "confirmed"}


@router.post("/facilities/catering")
async def create_catering_order(
    catering_type: str,
    event_name: str,
    event_date: str,
    delivery_time: str,
    number_of_people: int,
) -> dict[str, Any]:
    """Create catering order."""
    from koda2.modules.facilities.models import CateringType
    
    orch = get_orchestrator()
    date = dt.datetime.strptime(event_date, "%Y-%m-%d").date()
    time = dt.datetime.strptime(delivery_time, "%H:%M").time()
    
    order = await orch.facilities.create_catering_order(
        catering_type=CateringType(catering_type),
        event_name=event_name,
        event_date=date,
        delivery_time=time,
        number_of_people=number_of_people,
    )
    return {"order_id": order.id, "status": "pending"}


# ── Presentations ────────────────────────────────────────────────────

@router.post("/documents/presentation")
async def create_presentation(
    title: str,
    outline: str,
    author: str = "",
) -> dict[str, str]:
    """Create PowerPoint presentation from outline."""
    from koda2.modules.documents.presentations import PresentationGenerator
    
    gen = PresentationGenerator()
    output_path = gen.generate_from_outline(
        outline=outline,
        title=title,
        author=author,
    )
    return {"pptx_path": output_path}


# Import needed for type reference
from koda2.modules.calendar.models import CalendarEvent
from koda2.modules.email.models import EmailMessage


# ── Account Management ───────────────────────────────────────────────

class AccountCreateRequest(BaseModel):
    """Request to create a new account."""
    name: str
    account_type: str  # calendar, email, messaging
    provider: str  # ews, google, msgraph, caldav, imap, smtp, telegram
    credentials: dict[str, Any]
    is_default: bool = False


class AccountUpdateRequest(BaseModel):
    """Request to update an account."""
    name: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    credentials: Optional[dict[str, Any]] = None


class AccountResponse(BaseModel):
    """Account response model."""
    id: str
    name: str
    account_type: str
    provider: str
    is_active: bool
    is_default: bool
    created_at: str


@router.get("/accounts")
async def list_accounts(
    account_type: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    active_only: bool = Query(True),
) -> list[AccountResponse]:
    """List all accounts with optional filtering."""
    from koda2.modules.account.models import AccountType, ProviderType
    from koda2.modules.account.service import AccountService
    
    service = AccountService()
    
    # Parse filters
    acc_type = None
    if account_type:
        try:
            acc_type = AccountType(account_type)
        except ValueError:
            raise HTTPException(400, f"Invalid account_type: {account_type}")
    
    prov = None
    if provider:
        try:
            prov = ProviderType(provider)
        except ValueError:
            raise HTTPException(400, f"Invalid provider: {provider}")
    
    accounts = await service.get_accounts(
        account_type=acc_type,
        provider=prov,
        active_only=active_only,
    )
    
    return [
        AccountResponse(
            id=acc.id,
            name=acc.name,
            account_type=acc.account_type,
            provider=acc.provider,
            is_active=acc.is_active,
            is_default=acc.is_default,
            created_at=acc.created_at.isoformat() if acc.created_at else "",
        )
        for acc in accounts
    ]


@router.get("/accounts/{account_id}")
async def get_account(account_id: str) -> AccountResponse:
    """Get a specific account by ID."""
    from koda2.modules.account.service import AccountService
    
    service = AccountService()
    account = await service.get_account(account_id)
    
    if not account:
        raise HTTPException(404, "Account not found")
    
    return AccountResponse(
        id=account.id,
        name=account.name,
        account_type=account.account_type,
        provider=account.provider,
        is_active=account.is_active,
        is_default=account.is_default,
        created_at=account.created_at.isoformat() if account.created_at else "",
    )


@router.post("/accounts")
async def create_account(request: AccountCreateRequest) -> AccountResponse:
    """Create a new account."""
    from koda2.modules.account.models import AccountType, ProviderType
    from koda2.modules.account.service import AccountService
    
    service = AccountService()
    
    try:
        acc_type = AccountType(request.account_type)
        provider = ProviderType(request.provider)
    except ValueError as e:
        raise HTTPException(400, f"Invalid type or provider: {e}")
    
    # Validate credentials first
    valid, error = await service.validate_account_credentials(
        acc_type, provider, request.credentials
    )
    if not valid:
        raise HTTPException(400, f"Credential validation failed: {error}")
    
    account = await service.create_account(
        name=request.name,
        account_type=acc_type,
        provider=provider,
        credentials=request.credentials,
        is_default=request.is_default,
    )
    
    return AccountResponse(
        id=account.id,
        name=account.name,
        account_type=account.account_type,
        provider=account.provider,
        is_active=account.is_active,
        is_default=account.is_default,
        created_at=account.created_at.isoformat() if account.created_at else "",
    )


# ── Combined Exchange Account (Calendar + Email) ─────────────────────


class ExchangeAccountRequest(BaseModel):
    """Request to create combined Exchange calendar + email accounts."""
    name: str
    server: str
    username: str
    password: str
    email: str
    is_default: bool = True


@router.post("/accounts/exchange")
async def create_exchange_accounts(request: ExchangeAccountRequest) -> dict[str, Any]:
    """Create both calendar and email accounts for Exchange in one step."""
    from koda2.modules.account.models import AccountType, ProviderType
    from koda2.modules.account.service import AccountService
    from koda2.modules.account.validators import validate_ews_credentials

    # Validate credentials once
    valid, error = await validate_ews_credentials(
        request.server, request.username, request.password, request.email,
    )
    if not valid:
        raise HTTPException(400, f"Exchange connection failed: {error}")

    service = AccountService()
    creds = {
        "server": request.server,
        "username": request.username,
        "password": request.password,
        "email": request.email,
    }
    created = []

    # Create calendar account
    cal = await service.create_account(
        name=f"{request.name} (Calendar)",
        account_type=AccountType.CALENDAR,
        provider=ProviderType.EWS,
        credentials=creds,
        is_default=request.is_default,
    )
    created.append({"id": cal.id, "name": cal.name, "type": "calendar"})

    # Create email account
    mail = await service.create_account(
        name=f"{request.name} (Email)",
        account_type=AccountType.EMAIL,
        provider=ProviderType.EWS,
        credentials=creds,
        is_default=request.is_default,
    )
    created.append({"id": mail.id, "name": mail.name, "type": "email"})

    return {"status": "ok", "accounts": created}


@router.patch("/accounts/{account_id}")
async def update_account(account_id: str, request: AccountUpdateRequest) -> AccountResponse:
    """Update an existing account."""
    from koda2.modules.account.service import AccountService
    
    service = AccountService()
    
    # Build update dict
    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.is_active is not None:
        updates["is_active"] = request.is_active
    if request.is_default is not None:
        updates["is_default"] = request.is_default
    if request.credentials is not None:
        updates["credentials"] = request.credentials
    
    account = await service.update_account(account_id, **updates)
    
    if not account:
        raise HTTPException(404, "Account not found")
    
    return AccountResponse(
        id=account.id,
        name=account.name,
        account_type=account.account_type,
        provider=account.provider,
        is_active=account.is_active,
        is_default=account.is_default,
        created_at=account.created_at.isoformat() if account.created_at else "",
    )


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str) -> dict[str, str]:
    """Delete an account."""
    from koda2.modules.account.service import AccountService
    
    service = AccountService()
    success = await service.delete_account(account_id)
    
    if not success:
        raise HTTPException(404, "Account not found")
    
    return {"status": "deleted", "account_id": account_id}


@router.post("/accounts/{account_id}/test")
async def test_account(account_id: str) -> dict[str, Any]:
    """Test account credentials."""
    from koda2.modules.account.models import AccountType, ProviderType
    from koda2.modules.account.service import AccountService
    
    service = AccountService()
    account = await service.get_account(account_id)
    
    if not account:
        raise HTTPException(404, "Account not found")
    
    credentials = service.decrypt_credentials(account)
    success, message = await service.validate_account_credentials(
        AccountType(account.account_type),
        ProviderType(account.provider),
        credentials,
    )
    
    return {
        "account_id": account_id,
        "name": account.name,
        "valid": success,
        "message": message,
    }


@router.post("/accounts/{account_id}/set-default")
async def set_default_account(account_id: str) -> AccountResponse:
    """Set an account as default for its type."""
    from koda2.modules.account.service import AccountService
    
    service = AccountService()
    account = await service.set_default(account_id)
    
    if not account:
        raise HTTPException(404, "Account not found")
    
    return AccountResponse(
        id=account.id,
        name=account.name,
        account_type=account.account_type,
        provider=account.provider,
        is_active=account.is_active,
        is_default=account.is_default,
        created_at=account.created_at.isoformat() if account.created_at else "",
    )


# ── Google Workspace OAuth ────────────────────────────────────────────

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
GOOGLE_CREDS_PATH = Path("config/google_credentials.json")
GOOGLE_TOKEN_PATH = Path("config/google_token.json")


@router.get("/google/credentials-status")
async def google_credentials_status() -> dict[str, Any]:
    """Check if Google credentials and token files exist."""
    has_creds = GOOGLE_CREDS_PATH.exists()
    has_token = GOOGLE_TOKEN_PATH.exists()
    return {
        "has_credentials": has_creds,
        "has_token": has_token,
        "ready": has_creds and has_token,
    }


@router.post("/google/upload-credentials")
async def upload_google_credentials(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload Google OAuth2 credentials JSON file."""
    content = await file.read()

    # Validate JSON
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON file")

    if "installed" not in data and "web" not in data:
        raise HTTPException(400, "Invalid credentials file: missing 'installed' or 'web' section")

    client_config = data.get("installed") or data.get("web")
    required = ["client_id", "client_secret", "auth_uri", "token_uri"]
    missing = [f for f in required if f not in client_config]
    if missing:
        raise HTTPException(400, f"Missing required fields: {', '.join(missing)}")

    # Save to config directory
    GOOGLE_CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOOGLE_CREDS_PATH.write_bytes(content)

    return {"status": "ok", "message": "Credentials file saved", "path": str(GOOGLE_CREDS_PATH)}


@router.get("/google/auth-url")
async def get_google_auth_url() -> dict[str, Any]:
    """Generate Google OAuth2 authorization URL for web-based login."""
    if not GOOGLE_CREDS_PATH.exists():
        raise HTTPException(400, "Upload Google credentials JSON first")

    try:
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_secrets_file(
            str(GOOGLE_CREDS_PATH),
            scopes=GOOGLE_SCOPES,
            redirect_uri="http://localhost:8000/api/google/oauth-callback",
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
        )
        return {"auth_url": auth_url, "state": state}
    except ImportError:
        raise HTTPException(500, "Google auth libraries not installed (pip install google-auth-oauthlib)")
    except Exception as e:
        raise HTTPException(500, f"Failed to generate auth URL: {e}")


@router.get("/google/oauth-callback")
async def google_oauth_callback(
    code: str = Query(...),
    state: str = Query(None),
    scope: str = Query(None),
    error: str = Query(None),
):
    """Handle Google OAuth2 callback — exchange code for token and save."""
    # Google may redirect with an error instead of a code
    if error:
        raise HTTPException(400, f"Google authorization denied: {error}")

    if not GOOGLE_CREDS_PATH.exists():
        raise HTTPException(400, "Credentials file not found")

    REDIRECT_URI = "http://localhost:8000/api/google/oauth-callback"

    # ── Step 1: Read client config ────────────────────────────────────
    try:
        creds_data = json.loads(GOOGLE_CREDS_PATH.read_text())
    except Exception as e:
        raise HTTPException(500, f"Step 1 failed - cannot read credentials file: {e}")

    client_config = creds_data.get("web") or creds_data.get("installed")
    if not client_config:
        raise HTTPException(500, "Step 1 failed - no 'web' or 'installed' section in credentials")

    client_id = client_config.get("client_id", "")
    client_secret = client_config.get("client_secret", "")
    token_uri = client_config.get("token_uri", "https://oauth2.googleapis.com/token")

    # ── Step 2: Exchange code for tokens via direct HTTP POST ─────────
    try:
        async with httpx.AsyncClient() as http_client:
            resp = await http_client.post(token_uri, data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            }, timeout=30)
    except Exception as e:
        raise HTTPException(500, f"Step 2 failed - token request error: {e}")

    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error_description", err.get("error", "unknown"))
        except Exception:
            msg = resp.text[:200]
        raise HTTPException(400, f"Step 2 failed - token exchange: {msg}")

    try:
        token_data = resp.json()
    except Exception as e:
        raise HTTPException(500, f"Step 2 failed - invalid token response: {e}")

    # ── Step 3: Save token to disk ────────────────────────────────────
    try:
        token_json = {
            "token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token"),
            "token_uri": token_uri,
            "client_id": client_id,
            "client_secret": client_secret,
            "scopes": (scope or " ".join(GOOGLE_SCOPES)).split(),
            "expiry": None,
        }
        GOOGLE_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOOGLE_TOKEN_PATH.write_text(json.dumps(token_json, indent=2))
    except Exception as e:
        raise HTTPException(500, f"Step 3 failed - saving token: {e}")

    # ── Step 4: Create accounts in DB (bypass encryption) ─────────────
    try:
        from koda2.database import get_session
        from koda2.modules.account.models import AccountType, ProviderType, Account
        from sqlalchemy import select

        google_creds_json = json.dumps({
            "credentials_file": str(GOOGLE_CREDS_PATH),
            "token_file": str(GOOGLE_TOKEN_PATH),
        })

        async with get_session() as session:
            existing = (await session.execute(
                select(Account).where(Account.provider == ProviderType.GOOGLE.value)
            )).scalars().all()

            if not existing:
                session.add(Account(
                    name="Google (Calendar)",
                    account_type=AccountType.CALENDAR.value,
                    provider=ProviderType.GOOGLE.value,
                    credentials=google_creds_json,
                    is_active=True,
                    is_default=True,
                ))
                session.add(Account(
                    name="Google (Email)",
                    account_type=AccountType.EMAIL.value,
                    provider=ProviderType.GOOGLE.value,
                    credentials=google_creds_json,
                    is_active=True,
                    is_default=True,
                ))
                await session.commit()
    except Exception as e:
        # Token is already saved — accounts can be created later
        import traceback
        traceback.print_exc()
        # Still redirect — token is saved, that's the important part
        pass

    # Redirect back to dashboard
    return RedirectResponse(url="/dashboard?section=accounts&google=connected")


# ── Contacts ──────────────────────────────────────────────────────────


@router.get("/contacts")
async def list_contacts(
    query: str = Query("", description="Search query"),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Search or list contacts from all sources (macOS, WhatsApp, etc)."""
    orch = get_orchestrator()
    contacts = await orch.contacts.search(query, limit=limit)
    return [
        {
            "name": c.name,
            "phones": [{"number": p.number, "type": p.type, "whatsapp": p.whatsapp_available} for p in c.phones],
            "emails": [{"address": e.address, "type": e.type} for e in c.emails],
            "company": c.company,
            "job_title": c.job_title,
            "birthday": c.birthday.isoformat() if c.birthday else None,
            "sources": [s.value for s in c.sources],
            "has_whatsapp": c.has_whatsapp(),
        }
        for c in contacts
    ]


@router.post("/contacts/sync")
async def sync_contacts() -> dict[str, Any]:
    """Trigger a manual contact sync from all sources."""
    orch = get_orchestrator()
    counts = await orch.contacts.sync_all(force=True)
    summary = await orch.contacts.get_contact_summary()
    return {"status": "ok", "counts": counts, "summary": summary}


@router.get("/contacts/summary")
async def contacts_summary() -> dict[str, Any]:
    """Get contact sync summary."""
    orch = get_orchestrator()
    return await orch.contacts.get_contact_summary()


# ── Google Meet ───────────────────────────────────────────────────────


@router.post("/meet/create")
async def create_meet_link(
    title: str = Query("Koda2 Meeting", description="Meeting title"),
) -> dict[str, Any]:
    """Create a Google Meet link for ad-hoc use."""
    from pathlib import Path
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_path = Path("config/google_token.json")
    if not token_path.exists():
        raise HTTPException(400, "Google not connected. Set up Google OAuth first.")

    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
        else:
            raise HTTPException(400, "Google token expired. Re-authenticate via dashboard.")

    service = build("calendar", "v3", credentials=creds)

    import datetime as _dt
    now = _dt.datetime.now(_dt.UTC)
    event_body = {
        "summary": title,
        "start": {"dateTime": now.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (now + _dt.timedelta(hours=1)).isoformat(), "timeZone": "UTC"},
        "conferenceData": {
            "createRequest": {
                "requestId": f"koda2-meet-{now.strftime('%Y%m%d%H%M%S')}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    result = service.events().insert(
        calendarId="primary",
        body=event_body,
        conferenceDataVersion=1,
    ).execute()

    meet_url = result.get("hangoutLink", "")
    event_id = result.get("id", "")

    # Delete the placeholder event — we only wanted the Meet link
    if event_id:
        try:
            service.events().delete(calendarId="primary", eventId=event_id).execute()
        except Exception:
            pass

    if not meet_url:
        raise HTTPException(500, "Google Meet link was not generated")

    return {"meet_url": meet_url, "title": title}
