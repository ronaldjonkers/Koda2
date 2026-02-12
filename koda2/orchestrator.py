"""Central orchestrator — the brain connecting all modules and processing user intent."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.account.service import AccountService
from koda2.modules.calendar import CalendarEvent, CalendarService
from koda2.modules.documents import DocumentService
from koda2.modules.email import EmailMessage, EmailService
from koda2.modules.images import ImageService
from koda2.modules.llm import LLMRouter
from koda2.modules.llm.models import ChatMessage, LLMRequest
from koda2.modules.macos import MacOSService
from koda2.modules.memory import MemoryService
from koda2.modules.expenses import ExpenseService
from koda2.modules.facilities import FacilityService
from koda2.modules.git_manager import GitManagerService
from koda2.modules.meetings import MeetingService
from koda2.modules.messaging import TelegramBot, WhatsAppBot
from koda2.modules.messaging.command_parser import create_command_parser
from koda2.modules.scheduler import SchedulerService
from koda2.modules.self_improve import SelfImproveService
from koda2.modules.travel import TravelService
from koda2.security.audit import log_action

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are Koda2, a professional AI executive assistant functioning as a 
director-level secretary. You help manage calendars, emails, tasks, documents, and communications.

Your capabilities include:
- Calendar management (Google Calendar, Exchange, Office 365, CalDAV)
- Email (Gmail, Exchange, IMAP/SMTP) — read, send, and manage emails
- File system access — read, write, list files and directories on the computer
- File sharing — send files via WhatsApp (media) or email (attachments)
- Document creation (DOCX, XLSX, PDF, presentations) — saved to data/generated/
- Image generation (DALL-E, Stability AI) and image analysis (vision)
- Messaging (WhatsApp, Telegram) — send messages and files
- Shell commands (macOS) — run terminal commands safely
- Task scheduling and reminders
- Contact lookup (macOS Contacts)
- Memory — you remember previous conversations and can search them

Available actions and their parameters:
- run_shell: {"command": "...", "cwd": "/optional/path", "timeout": 30}
- list_directory: {"path": "/some/path"}
- read_file: {"path": "/some/file.txt"}
- write_file: {"path": "/some/file.txt", "content": "..."}
- file_exists: {"path": "/some/path"}
- send_file: {"path": "/file.pdf", "channel": "whatsapp|email", "to": "recipient", "caption": "..."}
- send_email: {"to": ["email@example.com"], "subject": "...", "body": "..."}
- check_calendar: {"start": "ISO datetime", "end": "ISO datetime"}
- schedule_meeting: {"title": "...", "start": "...", "end": "...", "location": "..."}
- generate_document: {"type": "docx|xlsx|pdf", "filename": "...", "title": "...", "content": [...]}
- generate_image: {"prompt": "..."}
- search_memory: {"query": "..."}
- find_contact: {"name": "..."}
- create_reminder: {"title": "...", "notes": "..."}

When the user gives you a request, determine the intent and required actions. Respond in JSON format:
{
    "intent": "one of: schedule_meeting, send_email, read_email, check_calendar, create_document, 
              generate_image, analyze_image, create_reminder, find_contact, search_memory, 
              send_file, run_command, read_file, write_file, list_directory, general_chat, unknown",
    "entities": {
        "any extracted entities like names, dates, times, subjects, etc."
    },
    "response": "A natural language response to the user",
    "actions": [
        {"action": "action_name", "params": {"key": "value"}}
    ]
}

Be helpful, proactive, and concise. If you need clarification, ask in the response field.
Always try to extract as much information as possible from the user's message."""


class Orchestrator:
    """Central brain that processes user requests and coordinates module actions."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self.llm = LLMRouter()
        self.memory = MemoryService()
        self.account_service = AccountService()
        self.calendar = CalendarService(self.account_service)
        self.email = EmailService(self.account_service)
        self.telegram = TelegramBot(self.account_service)
        self.whatsapp = WhatsAppBot()
        self.images = ImageService()
        self.documents = DocumentService()
        self.scheduler = SchedulerService()
        self.macos = MacOSService()
        self.self_improve = SelfImproveService()
        self.self_improve.set_llm_router(self.llm)
        self.git_manager = GitManagerService(self.llm)
        
        # New modules for director-level secretary features
        self.travel = TravelService()
        self.meetings = MeetingService(self.llm)
        self.expenses = ExpenseService(self.llm)
        self.facilities = FacilityService()
        
        # Create unified command parser and inject into messaging bots
        self.command_parser = create_command_parser(self)
        self.telegram.set_command_parser(self.command_parser)
        self.whatsapp.set_command_parser(self.command_parser)
        self.whatsapp.set_message_handler(self.process_message)

    async def process_message(
        self,
        user_id: str,
        message: str,
        channel: str = "api",
    ) -> dict[str, Any]:
        """Process a user message end-to-end.

        1. Store the message in memory
        2. Retrieve relevant context
        3. Parse intent via LLM
        4. Execute required actions
        5. Store the response
        6. Return the result
        """
        await self.memory.add_conversation(user_id, "user", message, channel=channel)
        await log_action(user_id, "message_received", "orchestrator", {"channel": channel, "length": len(message)})

        context = self.memory.recall(message, user_id=user_id, n=3)
        context_str = "\n".join(f"- {c['content']}" for c in context) if context else "No prior context."

        recent = await self.memory.get_recent_conversations(user_id, limit=10)
        history_messages = [
            ChatMessage(role=c.role, content=c.content) for c in recent[-8:]
        ]

        system = SYSTEM_PROMPT + f"\n\nRelevant context:\n{context_str}"
        history_messages.append(ChatMessage(role="user", content=message))

        request = LLMRequest(
            messages=history_messages,
            system_prompt=system,
            temperature=0.3,
        )

        try:
            llm_response = await self.llm.complete(request)
        except RuntimeError as exc:
            logger.error("orchestrator_llm_failed", error=str(exc))
            return {
                "response": "I'm having trouble processing your request. Please try again.",
                "error": str(exc),
            }

        parsed = self._parse_llm_response(llm_response.content)
        intent = parsed.get("intent", "general_chat")
        entities = parsed.get("entities", {})
        response_text = parsed.get("response", "")
        actions = parsed.get("actions", [])

        # If the LLM returned raw JSON without a "response" field, or the
        # response itself looks like JSON, extract just the human-readable part.
        if not response_text:
            response_text = llm_response.content
        if response_text.strip().startswith("{"):
            try:
                inner = json.loads(response_text)
                if isinstance(inner, dict) and "response" in inner:
                    response_text = inner["response"]
            except (json.JSONDecodeError, TypeError):
                pass

        action_results = []
        for action in actions:
            try:
                result = await self._execute_action(user_id, action, entities)
                action_results.append({"action": action.get("action"), "status": "success", "result": result})
            except Exception as exc:
                logger.error("action_failed", action=action, error=str(exc))
                action_results.append({"action": action.get("action"), "status": "error", "error": str(exc)})

        if intent != "general_chat":
            missing = self.self_improve.detect_missing(intent)
            if missing:
                response_text += f"\n\n(Note: I don't have the '{missing}' capability yet. I can build it if you'd like.)"

        await self.memory.add_conversation(
            user_id, "assistant", response_text, channel=channel,
            model=llm_response.model, tokens_used=llm_response.total_tokens,
        )
        await log_action(user_id, "message_processed", "orchestrator", {
            "intent": intent, "actions_count": len(actions), "tokens": llm_response.total_tokens,
        })

        return {
            "response": response_text,
            "intent": intent,
            "entities": entities,
            "actions": action_results,
            "tokens_used": llm_response.total_tokens,
            "model": llm_response.model,
        }

    def _parse_llm_response(self, content: str) -> dict[str, Any]:
        """Parse the LLM's JSON response, with fallback for plain text."""
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "intent": "general_chat",
                "entities": {},
                "response": content,
                "actions": [],
            }

    async def _execute_action(
        self,
        user_id: str,
        action: dict[str, Any],
        entities: dict[str, Any],
    ) -> Any:
        """Execute a single parsed action."""
        action_name = action.get("action", "")
        params = action.get("params", {})

        if action_name == "check_calendar":
            start = dt.datetime.fromisoformat(params.get("start", dt.datetime.now(dt.UTC).isoformat()))
            end = dt.datetime.fromisoformat(
                params.get("end", (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat())
            )
            events = await self.calendar.list_events(start, end)
            return [{"title": e.title, "start": e.start.isoformat(), "end": e.end.isoformat()} for e in events]

        elif action_name == "schedule_meeting":
            event = CalendarEvent(
                title=params.get("title", entities.get("subject", "Meeting")),
                description=params.get("description", ""),
                start=dt.datetime.fromisoformat(params.get("start", "")),
                end=dt.datetime.fromisoformat(params.get("end", "")),
                location=params.get("location", ""),
            )
            if params.get("attendee_email"):
                from koda2.modules.calendar.models import Attendee
                event.attendees.append(Attendee(email=params["attendee_email"]))
            created, prep = await self.calendar.schedule_with_prep(event)
            await self.memory.store_memory(
                user_id, "meeting", f"Scheduled: {event.title} at {event.start}",
                importance=0.8, source="calendar",
            )
            return {"event_id": created.provider_id, "prep_scheduled": prep is not None}

        elif action_name == "send_email":
            msg = EmailMessage(
                subject=params.get("subject", ""),
                recipients=params.get("to", []),
                body_text=params.get("body", ""),
                body_html=params.get("body_html", ""),
            )
            success = await self.email.send_email(msg)
            return {"sent": success}

        elif action_name == "read_email":
            from koda2.modules.email.models import EmailFilter
            emails = await self.email.fetch_emails(EmailFilter(
                unread_only=params.get("unread_only", True),
                limit=params.get("limit", 10),
            ))
            return [{"subject": e.subject, "sender": e.sender, "date": e.date.isoformat()} for e in emails]

        elif action_name == "find_contact":
            name = params.get("name", entities.get("name", ""))
            contact = await self.macos.find_contact(name)
            if contact:
                await self.memory.store_memory(
                    user_id, "contact", f"Looked up: {name} -> {contact}",
                    source="contacts",
                )
            return contact

        elif action_name == "create_reminder":
            result = await self.macos.create_reminder(
                title=params.get("title", ""),
                notes=params.get("notes", ""),
            )
            return result

        elif action_name == "generate_image":
            urls = await self.images.generate(params.get("prompt", ""))
            return {"images": urls}

        elif action_name == "analyze_image":
            analysis = await self.images.analyze(
                params.get("image_url", ""),
                params.get("prompt", "Describe this image."),
            )
            return {"analysis": analysis}

        elif action_name == "generate_document":
            doc_type = params.get("type", "docx")
            output = f"data/generated/{params.get('filename', 'document')}.{doc_type}"
            if doc_type == "docx":
                self.documents.generate_docx(
                    params.get("title", "Document"),
                    params.get("content", []),
                    output,
                )
            elif doc_type == "xlsx":
                self.documents.generate_xlsx(
                    params.get("title", "Spreadsheet"),
                    params.get("sheets", {}),
                    output,
                )
            elif doc_type == "pdf":
                self.documents.generate_pdf(
                    params.get("title", "Document"),
                    params.get("content", []),
                    output,
                )
            return {"path": output}

        elif action_name == "search_memory":
            results = self.memory.recall(params.get("query", ""), user_id=user_id)
            return results

        elif action_name == "run_shell":
            result = await self.macos.run_shell(
                params.get("command", ""),
                cwd=params.get("cwd"),
                timeout=params.get("timeout", 30),
            )
            return result

        elif action_name == "list_directory":
            entries = await self.macos.list_directory(params.get("path", "."))
            return entries

        elif action_name == "read_file":
            content = await self.macos.read_file(params.get("path", ""))
            return {"content": content}

        elif action_name == "write_file":
            written_path = await self.macos.write_file(
                params.get("path", ""),
                params.get("content", ""),
            )
            return {"path": written_path, "status": "written"}

        elif action_name == "file_exists":
            info = await self.macos.file_exists(params.get("path", ""))
            return info

        elif action_name == "send_file":
            file_path = params.get("path", "")
            channel = params.get("channel", "whatsapp")
            to = params.get("to", "")
            caption = params.get("caption", "")
            if channel == "whatsapp" and to:
                result = await self.whatsapp.send_media(
                    to, f"file://{file_path}", caption=caption,
                )
                return result
            elif channel == "email":
                msg = EmailMessage(
                    subject=params.get("subject", "File from Koda2"),
                    recipients=params.get("to_email", [to]) if to else [],
                    body_text=caption or "See attached file.",
                    attachments=[file_path],
                )
                success = await self.email.send_email(msg)
                return {"sent": success}
            return {"status": "no_channel", "path": file_path}

        elif action_name == "build_capability":
            capability = params.get("capability", "")
            description = params.get("description", "")
            path = await self.self_improve.generate_plugin(capability, description)
            return {"plugin_path": path, "status": "generated"}

        else:
            logger.warning("unknown_action", action=action_name)
            return {"status": "unknown_action", "action": action_name}

    # ── Messaging Integration ────────────────────────────────────────

    async def setup_telegram(self) -> None:
        """Configure and start the Telegram bot with command routing."""
        if not await self.telegram.is_configured():
            logger.info("telegram_not_configured_skipping")
            return

        async def handle_message(user_id: str, text: str, **kwargs: Any) -> str:
            result = await self.process_message(user_id, text, channel="telegram")
            return result["response"]

        async def handle_schedule(user_id: str, args: str, **kwargs: Any) -> str:
            result = await self.process_message(user_id, f"Schedule: {args}", channel="telegram")
            return result["response"]

        async def handle_email(user_id: str, args: str, **kwargs: Any) -> str:
            result = await self.process_message(user_id, f"Email: {args}", channel="telegram")
            return result["response"]

        async def handle_remind(user_id: str, args: str, **kwargs: Any) -> str:
            result = await self.process_message(user_id, f"Remind me: {args}", channel="telegram")
            return result["response"]

        async def handle_status(user_id: str, args: str, **kwargs: Any) -> str:
            providers = await self.calendar.active_providers()
            plugins = self.self_improve.list_plugins()
            tasks = self.scheduler.list_tasks()
            imap = await self.email.imap_configured()
            smtp = await self.email.smtp_configured()
            return (
                f"*Koda2 Status*\n"
                f"Calendar providers: {', '.join(str(p) for p in providers) or 'none'}\n"
                f"Email: {'IMAP ✓' if imap else 'IMAP ✗'} / "
                f"{'SMTP ✓' if smtp else 'SMTP ✗'}\n"
                f"LLM providers: {', '.join(str(p) for p in self.llm.available_providers) or 'none'}\n"
                f"Plugins loaded: {len(plugins)}\n"
                f"Scheduled tasks: {len(tasks)}"
            )

        self.telegram.register_command("schedule", handle_schedule)
        self.telegram.register_command("email", handle_email)
        self.telegram.register_command("remind", handle_remind)
        self.telegram.register_command("status", handle_status)
        self.telegram.set_message_handler(handle_message)

        await self.telegram.start()
        logger.info("telegram_integration_ready")

    async def setup_whatsapp(self) -> None:
        """Start the WhatsApp Web bridge and configure message handling."""
        if not self.whatsapp.is_configured:
            logger.info("whatsapp_not_configured_skipping")
            return

        await self.whatsapp.start_bridge()
        logger.info("whatsapp_integration_ready")

    async def handle_whatsapp_message(self, payload: dict[str, Any]) -> Optional[str]:
        """Handle an incoming WhatsApp self-message.

        Only processes messages the user sends to themselves.
        Can send replies to anyone on the user's behalf.
        """
        logger.info("orchestrator_whatsapp_message_received", payload_preview=str(payload)[:200])
        print(f"[Koda2] WhatsApp message received: {payload.get('body', '')[:50]}...")
        
        parsed = await self.whatsapp.process_webhook(payload)
        if parsed is None:
            logger.debug("orchestrator_whatsapp_message_ignored_not_parsed")
            return None

        text = parsed.get("text", "")
        if not text:
            logger.debug("orchestrator_whatsapp_message_empty_text")
            return None

        user_id = parsed.get("from", "whatsapp_user")
        logger.info("orchestrator_processing_whatsapp_message", user_id=user_id, text_preview=text[:100])
        print(f"[Koda2] Processing message from {user_id}: {text[:50]}...")

        # Show typing indicator while AI is thinking
        await self.whatsapp.send_typing(user_id)
        
        result = await self.process_message(user_id, text, channel="whatsapp")
        response = result.get("response", "")

        # Send the response back to the user's own chat
        if response:
            logger.info("orchestrator_sending_whatsapp_reply", to=user_id, response_preview=response[:100])
            print(f"[Koda2] Sending reply: {response[:100]}...")
            await self.whatsapp.send_message(user_id, response)
        else:
            logger.warning("orchestrator_no_response_for_whatsapp_message")
            print("[Koda2] No response generated for message")

        return response
