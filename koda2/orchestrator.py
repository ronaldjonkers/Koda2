"""Central orchestrator — the brain connecting all modules and processing user intent.

This module contains the Orchestrator class which coordinates all services.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.modules.account.service import AccountService
from koda2.modules.calendar import CalendarEvent, CalendarService
from koda2.modules.contacts import ContactSyncService
from koda2.modules.document_analyzer import DocumentAnalyzerService
from koda2.modules.documents import DocumentService
from koda2.modules.email import EmailMessage, EmailService
from koda2.modules.email.assistant_mail import AssistantMailService
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
from koda2.modules.proactive import ProactiveService
from koda2.modules.scheduler import SchedulerService
from koda2.modules.self_improve import SelfImproveService
from koda2.modules.task_queue import TaskQueueService
from koda2.modules.travel import TravelService
from koda2.modules.agent import AgentService
from koda2.modules.browser import BrowserService
from koda2.modules.commands import get_registry
from koda2.modules.video import VideoService
from koda2.security.audit import log_action
from koda2.supervisor.error_collector import record_error as _record_runtime_error

logger = get_logger(__name__)

# Fallback system prompt (used when workspace/SOUL.md is not found)
_DEFAULT_SYSTEM_PROMPT = """You are Koda2, a personal AI executive assistant. You help the user by executing actions using the available tools.

Available capabilities:
- Calendar: list events, create events, schedule meetings with prep
- Email: read inbox, send emails, search, reply, forward
- WhatsApp: send messages and files to contacts
- Scheduling: create recurring tasks, one-time tasks, interval tasks
- Shell: run any terminal command (ls, cat, find, grep, git, python, etc.)
- Documents: create DOCX, XLSX, PDF, PPTX; analyze PDF/DOCX/images
- Images: generate with AI, analyze with vision
- Video: generate with AI
- Contacts: find by name, search, sync from macOS/WhatsApp/Gmail/Exchange
- Memory: search conversation history
- Reminders: create macOS reminders
- Tasks: check task queue status

IMPORTANT RULES:
1. ALWAYS use tools to fulfill requests. Never just say "I'll do that" without calling a tool.
2. If you need info first (e.g., a contact's phone number), call the tool to look it up, then use the result.
3. Contact names are auto-resolved to phone/email — you can pass names directly to send_whatsapp or send_file.
4. For WhatsApp files: use send_file with channel="whatsapp".
5. For email attachments: use send_email_with_attachments.
6. Shell commands have full access except sudo and dangerous system operations.
7. Be concise and helpful. Respond in the user's language.
8. Today's date/time context will be provided when available."""

# Maximum tool-calling loop iterations to prevent runaway
MAX_TOOL_ITERATIONS = 8

# If the first LLM response has more than this many tool calls, offload to background agent
AGENT_AUTO_THRESHOLD = 4

# Context window guard — rough token estimate (1 token ≈ 4 chars)
# Keep total context under this to avoid overflow errors
CONTEXT_MAX_TOKENS = 100_000
CONTEXT_HISTORY_SHARE = 0.4  # max 40% of context for history
CHARS_PER_TOKEN = 4

# WhatsApp/Telegram message chunk limit
MESSAGE_CHUNK_LIMIT = 4000

# Inbound message debounce — batch rapid-fire messages (seconds)
DEBOUNCE_SECONDS = 1.5

# Workspace directory for personality/tool files
_WORKSPACE_DIR = Path("workspace")


def _load_workspace_file(name: str) -> str:
    """Load a markdown file from the workspace directory."""
    path = _WORKSPACE_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


class Orchestrator:
    """Central brain that processes user requests and coordinates module actions."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self.llm = LLMRouter()
        self.memory = MemoryService()
        self.account_service = AccountService()
        self.calendar = CalendarService(self.account_service)
        self.email = EmailService(self.account_service)
        self.assistant_mail = AssistantMailService(self.account_service)
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
        
        # New services for complete coverage
        self.contacts = ContactSyncService(
            macos_service=self.macos,
            whatsapp_bot=self.whatsapp,
            account_service=self.account_service,
            memory_service=self.memory,
        )
        self.video = VideoService()
        self.browser = BrowserService()
        self.proactive = ProactiveService(
            calendar_service=self.calendar,
            email_service=self.email,
            contact_service=self.contacts,
            memory_service=self.memory,
            whatsapp_bot=self.whatsapp,
        )
        self.document_analyzer = DocumentAnalyzerService(self.llm)
        
        # Task queue for async operations (messaging, long-running tasks)
        self.task_queue = TaskQueueService(max_workers=5)
        
        # Command registry for action documentation
        self.commands = get_registry()
        
        # Agent service for autonomous task execution
        self.agent = AgentService(
            llm_router=self.llm,
            orchestrator=self,
        )
        
        # Create unified command parser and inject into messaging bots
        self.command_parser = create_command_parser(self)
        self.telegram.set_command_parser(self.command_parser)
        self.whatsapp.set_command_parser(self.command_parser)
        self.whatsapp.set_message_handler(self.process_message)

        # Inbound message debounce — batch rapid-fire messages per user
        self._debounce_buffers: dict[str, list[str]] = {}
        self._debounce_tasks: dict[str, asyncio.Task] = {}

    def _get_system_prompt(self) -> str:
        """Generate the full system prompt from workspace files + date/time context."""
        soul = _load_workspace_file("SOUL.md")
        tools_md = _load_workspace_file("TOOLS.md")
        base = soul if soul else _DEFAULT_SYSTEM_PROMPT
        if tools_md:
            base += f"\n\n{tools_md}"
        from koda2.config import get_local_tz
        local_tz = get_local_tz()
        tz_name = self._settings.koda2_timezone
        now = dt.datetime.now(local_tz)
        base += f"\n\nCurrent date/time: {now.strftime('%A %d %B %Y, %H:%M')} ({tz_name})"
        base += f"\nTimezone: {tz_name}. ALL datetimes in tool calls (start, end) must be in ISO format with this local timezone, e.g. {now.strftime('%Y-%m-%dT%H:%M:%S')}. Never use UTC for user-facing times."
        if self._settings.user_name:
            base += f"\nUser: {self._settings.user_name}"
        return base

    @staticmethod
    def _chunk_message(text: str, limit: int = MESSAGE_CHUNK_LIMIT) -> list[str]:
        """Split a long message into chunks at paragraph boundaries.

        Inspired by OpenClaw's chunk.ts — respects markdown fences and
        prefers splitting on blank lines so messages stay readable.
        """
        if not text or len(text) <= limit:
            return [text] if text else []

        chunks: list[str] = []
        paragraphs = text.split("\n\n")
        current = ""

        for para in paragraphs:
            candidate = f"{current}\n\n{para}" if current else para
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    chunks.append(current.strip())
                # If single paragraph exceeds limit, hard-split it
                if len(para) > limit:
                    while para:
                        chunks.append(para[:limit].strip())
                        para = para[limit:]
                    current = ""
                else:
                    current = para

        if current.strip():
            chunks.append(current.strip())

        return chunks if chunks else [text]

    async def _send_chunked(self, user_id: str, text: str, channel: str) -> None:
        """Send a response, splitting into chunks if it exceeds the platform limit."""
        chunks = self._chunk_message(text)
        for chunk in chunks:
            try:
                if channel == "whatsapp" and self.whatsapp.is_configured:
                    await self.whatsapp.send_message(user_id, chunk)
                elif channel == "telegram" and self.telegram.is_configured:
                    await self.telegram.send_message(user_id, chunk)
            except Exception as exc:
                logger.error("send_chunked_failed", channel=channel, error=str(exc))

    async def _send_typing(self, user_id: str, channel: str) -> None:
        """Send typing indicator on the originating channel (best-effort)."""
        try:
            if channel == "whatsapp" and self.whatsapp.is_configured:
                await self.whatsapp.send_typing(user_id)
            elif channel == "telegram" and self.telegram.is_configured:
                await self.telegram.send_typing(user_id)
        except Exception:
            pass  # typing indicators are best-effort

    async def _auto_learn(self, user_id: str, user_msg: str, assistant_msg: str) -> None:
        """Extract learnable facts/preferences from a conversation turn.

        Runs as a background task after each response. Uses a cheap/fast LLM
        call to identify facts worth remembering long-term.
        """
        # Skip very short or system messages
        if len(user_msg) < 15 or not assistant_msg:
            return
        try:
            extract_prompt = (
                "Analyze this conversation snippet and extract any personal facts, preferences, "
                "habits, or important information the user revealed about themselves. "
                "Return a JSON array of objects with 'category' (one of: preference, fact, "
                "contact_info, habit, important) and 'content' (concise statement). "
                "Return an EMPTY array [] if nothing worth remembering. "
                "Only extract EXPLICIT information, never infer.\n\n"
                f"User: {user_msg[:500]}\nAssistant: {assistant_msg[:500]}"
            )
            resp = await self.llm.complete(LLMRequest(
                messages=[ChatMessage(role="user", content=extract_prompt)],
                system_prompt="You are a memory extraction engine. Return ONLY valid JSON.",
                temperature=0.0,
                max_tokens=512,
            ))
            raw = (resp.content or "").strip()
            # Parse JSON from response (handle markdown fences)
            if "```" in raw:
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()
            items = json.loads(raw) if raw.startswith("[") else []
            if not isinstance(items, list):
                items = []

            for item in items[:3]:  # max 3 facts per message
                cat = item.get("category", "fact")
                content = item.get("content", "").strip()
                if not content or len(content) < 5:
                    continue
                # Dedup: skip if we already have a very similar memory
                existing = self.memory.recall(content, user_id=user_id, n=1, max_distance=0.15)
                if existing:
                    continue
                await self.memory.store_memory(
                    user_id, cat, content, importance=0.6, source="auto-learn",
                )
                logger.info("auto_learn_stored", user_id=user_id, category=cat, content=content[:80])
        except Exception as exc:
            logger.debug("auto_learn_failed", error=str(exc))

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get OpenAI-format tool definitions from the command registry."""
        return self.commands.to_openai_tools()

    async def process_message(
        self,
        user_id: str,
        message: str,
        channel: str = "api",
    ) -> dict[str, Any]:
        """Process a user message with an agent tool-calling loop.

        Flow:
        1. Store message in memory
        2. Build conversation with context
        3. Call LLM with tool definitions
        4. If LLM returns tool_calls → execute them → feed results back → repeat
        5. When LLM returns text (no tool_calls) → that's the final response
        6. Store and return
        """
        await self.memory.add_conversation(user_id, "user", message, channel=channel)
        await log_action(user_id, "message_received", "orchestrator", {"channel": channel, "length": len(message)})

        # Send typing indicator on the originating channel
        await self._send_typing(user_id, channel)

        # Build context with token-aware pruning (inspired by OpenClaw context-window-guard)
        # 1) Semantic recall — find memories relevant to this specific message
        context = self.memory.recall(message, user_id=user_id, n=5, max_distance=0.45)
        recall_str = "\n".join(f"- {c['content']}" for c in context) if context else ""

        # 2) Structured memories — load user preferences, facts, and habits
        structured_parts: list[str] = []
        try:
            for cat in ("preference", "fact", "contact_info", "habit", "important"):
                entries = await self.memory.list_memories(user_id, category=cat, limit=10)
                for e in entries:
                    structured_parts.append(f"[{e.category}] {e.content}")
        except Exception:
            pass
        structured_str = "\n".join(structured_parts) if structured_parts else ""

        system = self._get_system_prompt()
        if structured_str:
            system += f"\n\nUser knowledge (always consider this):\n{structured_str}"
        if recall_str:
            system += f"\n\nRelevant context from memory:\n{recall_str}"

        # Estimate system prompt tokens
        system_tokens = len(system) // CHARS_PER_TOKEN
        history_budget = int((CONTEXT_MAX_TOKENS - system_tokens) * CONTEXT_HISTORY_SHARE)

        # Load recent conversations and prune to fit budget
        recent = await self.memory.get_recent_conversations(user_id, limit=20, max_age_hours=4)
        history_messages: list[ChatMessage] = []
        history_tokens = 0
        for c in reversed(recent):
            msg_tokens = len(c.content) // CHARS_PER_TOKEN
            if history_tokens + msg_tokens > history_budget:
                break
            history_messages.insert(0, ChatMessage(role=c.role, content=c.content))
            history_tokens += msg_tokens

        history_messages.append(ChatMessage(role="user", content=message))

        tools = self._get_tool_definitions()
        total_tokens = 0
        model_used = ""
        action_log: list[dict[str, Any]] = []
        iteration = 0

        # ── Agent Loop ────────────────────────────────────────────────
        while iteration < MAX_TOOL_ITERATIONS:
            iteration += 1

            # Refresh typing indicator each iteration so user sees activity
            if iteration > 1:
                await self._send_typing(user_id, channel)

            request = LLMRequest(
                messages=history_messages,
                system_prompt=system,
                temperature=0.3,
                tools=tools if iteration <= MAX_TOOL_ITERATIONS - 1 else None,
            )

            try:
                llm_response = await self.llm.complete(request)
            except RuntimeError as exc:
                logger.error("orchestrator_llm_failed", error=str(exc), iteration=iteration)
                return {
                    "response": "I'm having trouble processing your request. Please try again.",
                    "error": str(exc),
                }

            total_tokens += llm_response.total_tokens
            model_used = llm_response.model

            # If no tool calls → LLM is done, return the text response
            if not llm_response.tool_calls:
                response_text = llm_response.content or ""
                # Clean any accidental JSON from the response
                response_text = self._clean_response_for_user(response_text)
                if not response_text.strip():
                    # Last-resort: force a summary LLM call with all tool results
                    logger.warning("empty_response_forcing_summary", iteration=iteration)
                    try:
                        summary_req = LLMRequest(
                            messages=history_messages + [
                                ChatMessage(role="user", content="Summarise what you've found and respond to the user concisely. Do NOT call any more tools."),
                            ],
                            system_prompt=system,
                            temperature=0.3,
                        )
                        summary_resp = await self.llm.complete(summary_req)
                        total_tokens += summary_resp.total_tokens
                        response_text = self._clean_response_for_user(summary_resp.content or "")
                    except Exception:
                        pass
                    if not response_text.strip():
                        response_text = "I've reached the limit for this request. Could you try rephrasing or simplifying your question?"
                break

            # ── Auto-detect complex tasks → offload to background agent ──
            if iteration == 1 and len(llm_response.tool_calls) >= AGENT_AUTO_THRESHOLD:
                logger.info(
                    "auto_offload_to_agent",
                    tool_count=len(llm_response.tool_calls),
                    threshold=AGENT_AUTO_THRESHOLD,
                )
                try:
                    agent_task = await self.agent.create_task(
                        user_id=user_id,
                        request=message,
                        auto_start=True,
                    )
                    response_text = (
                        f"This looks like a complex task ({len(llm_response.tool_calls)} steps detected). "
                        f"I've started it as a background agent task (ID: {agent_task.id[:8]}...). "
                        f"You'll be notified when it's complete — you can check status with /status."
                    )
                    action_log.append({"tool": "run_agent_task", "status": "auto_offloaded", "task_id": agent_task.id})
                    break
                except Exception as exc:
                    logger.error("auto_offload_failed", error=str(exc))
                    # Fall through to normal inline execution

            # LLM wants to call tools — add assistant message with tool_calls to history
            logger.info(
                "tool_calls_requested",
                iteration=iteration,
                tools=[tc["function"]["name"] for tc in llm_response.tool_calls],
            )
            history_messages.append(ChatMessage(
                role="assistant",
                content=llm_response.content or "",
                tool_calls=llm_response.tool_calls,
            ))

            # Execute each tool call and add results to history
            for tc in llm_response.tool_calls:
                func_name = tc["function"]["name"]
                try:
                    args_str = tc["function"]["arguments"]
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except (json.JSONDecodeError, TypeError):
                    args = {}

                logger.info("executing_tool", tool=func_name, args_preview=str(args)[:200])

                try:
                    result = await self._execute_action(
                        user_id=user_id,
                        action={"action": func_name, "params": args},
                        entities={},
                    )
                    result_str = json.dumps(result, default=str, ensure_ascii=False)
                    # Truncate very large results to avoid context overflow
                    if len(result_str) > 4000:
                        result_str = result_str[:4000] + "... (truncated)"
                    action_log.append({"tool": func_name, "status": "success"})
                except Exception as exc:
                    result_str = json.dumps({"error": str(exc)}, ensure_ascii=False)
                    action_log.append({"tool": func_name, "status": "error", "error": str(exc)})
                    logger.error("tool_execution_failed", tool=func_name, error=str(exc))
                    _record_runtime_error(
                        func_name, str(exc),
                        args_preview=str(args)[:200],
                        user_id=user_id, channel=channel,
                    )

                # Add tool result to conversation so LLM sees it
                history_messages.append(ChatMessage(
                    role="tool",
                    content=result_str,
                    tool_call_id=tc["id"],
                ))

        else:
            # Hit max iterations — force a final text-only LLM call to summarise
            logger.warning("max_tool_iterations_reached", user_id=user_id, iterations=MAX_TOOL_ITERATIONS)
            try:
                summary_req = LLMRequest(
                    messages=history_messages + [
                        ChatMessage(role="user", content="Summarise what you've found and respond to the user. Do NOT call any more tools."),
                    ],
                    system_prompt=system,
                    temperature=0.3,
                )
                summary_resp = await self.llm.complete(summary_req)
                response_text = self._clean_response_for_user(summary_resp.content or "")
            except Exception:
                response_text = ""
            if not response_text.strip():
                response_text = "I've reached the maximum number of steps for this request. Could you try rephrasing or simplifying your question?"

        # Store response in memory
        await self.memory.add_conversation(
            user_id, "assistant", response_text, channel=channel,
            model=model_used, tokens_used=total_tokens,
        )
        await log_action(user_id, "message_processed", "orchestrator", {
            "tool_calls": len(action_log), "iterations": iteration, "tokens": total_tokens,
        })

        # Auto-learn: extract facts/preferences in the background
        asyncio.create_task(self._auto_learn(user_id, message, response_text))

        return {
            "response": response_text,
            "tool_calls": action_log,
            "iterations": iteration,
            "tokens_used": total_tokens,
            "model": model_used,
        }

    def _parse_llm_response(self, content: str) -> dict[str, Any]:
        """Parse the LLM's JSON response, with fallback for plain text."""
        import re
        
        content = content.strip()
        
        # Case 1: Content is wrapped in code blocks - extract JSON from inside
        if content.startswith("```"):
            # Extract content between code block markers
            lines = content.split("\n")
            if len(lines) > 2:
                # Remove first line (```json or ```) and last line (```)
                inner_content = "\n".join(lines[1:-1])
            else:
                inner_content = content.replace("```json", "").replace("```", "").strip()
            
            try:
                return json.loads(inner_content)
            except json.JSONDecodeError:
                pass
        
        # Case 2: Content starts with JSON object - extract just the JSON part
        if content.startswith("{"):
            # Find the end of the JSON object by counting braces
            brace_count = 0
            json_end = 0
            for i, char in enumerate(content):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break
            
            if json_end > 0:
                json_part = content[:json_end]
                remaining_text = content[json_end:].strip()
                
                try:
                    data = json.loads(json_part)
                    # If there's text after the JSON, append it to the response
                    if remaining_text and isinstance(data, dict):
                        original_response = data.get("response", "")
                        data["response"] = original_response + "\n\n" + remaining_text
                    return data
                except json.JSONDecodeError:
                    pass
        
        # Case 3: Plain text fallback
        return {
            "intent": "general_chat",
            "entities": {},
            "response": content,
            "actions": [],
        }

    def _clean_response_for_user(self, text: str) -> str:
        """Clean LLM response for user display by removing JSON artifacts.
        
        This removes:
        - JSON code blocks (```json {...}```)
        - Standalone JSON objects that appear in the text
        - Extracts just the 'response' field if the entire text is JSON
        
        Returns clean human-readable text.
        """
        if not text:
            return text
        
        import re
        
        original_text = text.strip()
        
        # Case 1: Check if text starts with JSON code block
        # Pattern: ```json followed by JSON and ending with ```
        json_code_block_pattern = r'^```(?:json)?\s*\n*(\{[\s\S]*?\})\s*\n*```'
        match = re.search(json_code_block_pattern, original_text)
        if match:
            try:
                json_str = match.group(1)
                data = json.loads(json_str)
                if isinstance(data, dict) and "response" in data:
                    # Return the response field + any text after the code block
                    remaining = original_text[match.end():].strip()
                    result = data["response"].strip()
                    if remaining:
                        result += "\n\n" + remaining
                    return result
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Case 2: Entire text is a JSON object (no code block markers)
        if original_text.startswith("{") and original_text.endswith("}"):
            try:
                data = json.loads(original_text)
                if isinstance(data, dict) and "response" in data:
                    return data["response"].strip()
            except json.JSONDecodeError:
                pass
        
        # Case 3: Text starts with JSON and has text after it
        # Try to find a complete JSON object at the start
        if original_text.startswith("{"):
            # Find the matching closing brace
            brace_count = 0
            json_end = 0
            for i, char in enumerate(original_text):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break
            
            if json_end > 0:
                json_part = original_text[:json_end]
                remaining_text = original_text[json_end:].strip()
                try:
                    data = json.loads(json_part)
                    if isinstance(data, dict) and "response" in data:
                        result = data["response"].strip()
                        if remaining_text:
                            result += "\n\n" + remaining_text
                        return result
                except json.JSONDecodeError:
                    pass
        
        # Case 4: Text contains JSON code blocks in the middle - remove them
        # Remove JSON markdown code blocks and replace with their response
        def replace_json_block(match):
            try:
                json_str = match.group(1) if match.group(1) else match.group(0)
                # Clean up the json string
                json_str = json_str.strip()
                if json_str.startswith('```'):
                    # Extract content between backticks
                    lines = json_str.split('\n')
                    if len(lines) > 2:
                        json_str = '\n'.join(lines[1:-1])
                    else:
                        json_str = json_str.replace('```json', '').replace('```', '').strip()
                
                data = json.loads(json_str)
                if isinstance(data, dict) and "response" in data:
                    return data["response"]
            except:
                pass
            return ''
        
        # Pattern to match JSON code blocks anywhere in text
        text = re.sub(r'```json\s*\n([\s\S]*?)\n\s*```', replace_json_block, text, flags=re.MULTILINE)
        text = re.sub(r'```\s*\n([\s\S]*?)\n\s*```', replace_json_block, text, flags=re.MULTILINE)
        
        # Clean up excessive whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()
        
        return text

    async def _send_whatsapp_task(
        self,
        recipient: str,
        message: str,
        progress_callback: Optional[Callable] = None,
    ) -> dict[str, Any]:
        """Task function for sending WhatsApp messages via task queue.
        
        This runs async and updates progress as it goes.
        """
        try:
            if progress_callback:
                await progress_callback(10, "Connecting to WhatsApp...")
            
            # Send the message
            result = await self.whatsapp.send_message(recipient, message)
            
            if progress_callback:
                await progress_callback(100, "Message sent!")
            
            return {"sent": True, "result": result}
            
        except Exception as exc:
            logger.error("whatsapp_task_failed", recipient=recipient, error=str(exc))
            if progress_callback:
                await progress_callback(100, f"Failed: {str(exc)}")
            return {"sent": False, "error": str(exc)}

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
            from koda2.config import ensure_local_tz
            start = ensure_local_tz(dt.datetime.fromisoformat(
                params.get("start", dt.datetime.now(dt.UTC).isoformat())
            ))
            end = ensure_local_tz(dt.datetime.fromisoformat(
                params.get("end", (dt.datetime.now(dt.UTC) + dt.timedelta(days=1)).isoformat())
            ))
            events = await self.calendar.list_events(start, end)
            return [{"title": e.title, "start": e.start.isoformat(), "end": e.end.isoformat()} for e in events]

        elif action_name == "schedule_meeting":
            from koda2.config import ensure_local_tz
            event = CalendarEvent(
                title=params.get("title", entities.get("subject", "Meeting")),
                description=params.get("description", ""),
                start=ensure_local_tz(dt.datetime.fromisoformat(params.get("start", ""))),
                end=ensure_local_tz(dt.datetime.fromisoformat(params.get("end", ""))),
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
                cc=params.get("cc", []),
                body_text=params.get("body", ""),
                body_html=params.get("body_html", ""),
            )
            account_name = params.get("account", "")
            if account_name:
                accounts = await self.email._get_email_accounts()
                match = next((a for a in accounts if a.name.lower() == account_name.lower()), None)
                if match:
                    success = await self.email.send_email(msg, account_id=match.id)
                else:
                    success = await self.email.send_email(msg)
            else:
                success = await self.email.send_email(msg)
            return {"sent": success}

        elif action_name == "send_assistant_email":
            ok = await self.assistant_mail.send_email(
                to=params.get("to", []),
                subject=params.get("subject", ""),
                body_text=params.get("body", ""),
                body_html=params.get("body_html", ""),
                cc=params.get("cc"),
            )
            return {"sent": ok}

        elif action_name == "reply_email":
            original_id = params.get("email_id", "")
            reply_body = params.get("body", "")
            reply_all = params.get("reply_all", False)
            # Fetch the original email to get context
            all_emails = await self.email.fetch_all_emails(unread_only=False, limit=50)
            original = next((e for e in all_emails if e.id == original_id or e.provider_id == original_id), None)
            if not original:
                return {"error": f"Email not found: {original_id}"}
            recipients = [original.sender]
            if reply_all:
                recipients.extend(original.recipients)
                recipients = list(set(recipients))
            msg = EmailMessage(
                subject=f"Re: {original.subject}" if not original.subject.startswith("Re:") else original.subject,
                recipients=recipients,
                body_text=reply_body,
                in_reply_to=original.provider_id,
                references=original.references or original.provider_id,
            )
            success = await self.email.send_email(msg)
            return {"sent": success, "replied_to": original.subject}

        elif action_name == "search_email":
            query = params.get("query", "")
            limit = params.get("limit", 20)
            # Use Gmail search if available, otherwise fetch all and filter
            emails = await self.email.fetch_all_emails(unread_only=False, limit=limit)
            if query:
                q = query.lower()
                emails = [e for e in emails if q in e.subject.lower() or q in e.sender.lower() or q in (e.body_text or "").lower()]
            return [{
                "id": e.id,
                "provider_id": e.provider_id,
                "account": e.account_name,
                "subject": e.subject,
                "sender": e.sender,
                "date": e.date.isoformat(),
                "is_read": e.is_read,
                "body_preview": (e.body_text or "")[:300],
            } for e in emails[:limit]]

        elif action_name == "get_email_detail":
            email_id = params.get("email_id", "")
            all_emails = await self.email.fetch_all_emails(unread_only=False, limit=100)
            email = next((e for e in all_emails if e.id == email_id or e.provider_id == email_id), None)
            if not email:
                return {"error": f"Email not found: {email_id}"}
            return {
                "id": email.id,
                "provider_id": email.provider_id,
                "account": email.account_name,
                "provider": email.provider.value if email.provider else "unknown",
                "subject": email.subject,
                "sender": email.sender,
                "sender_name": email.sender_name,
                "recipients": email.recipients,
                "cc": email.cc,
                "date": email.date.isoformat(),
                "is_read": email.is_read,
                "has_attachments": email.has_attachments,
                "body_text": email.body_text,
                "body_html": email.body_html[:2000] if email.body_html else "",
                "in_reply_to": email.in_reply_to,
            }

        elif action_name == "send_whatsapp":
            to = params.get("to", "")
            message = params.get("message", "")
            
            # Resolve contact name to phone number if needed
            recipient = to
            if to and not to.startswith("+") and not to.isdigit():
                # Try to find contact by name
                contact = await self.contacts.find_by_name(to)
                if contact and contact.get_primary_phone():
                    recipient = contact.get_primary_phone()
                    logger.info("resolved_contact_for_whatsapp", name=to, phone=recipient)
                else:
                    return {"status": "error", "error": f"Could not find phone number for contact: {to}"}
            
            # Submit to task queue for async processing
            task = await self.task_queue.submit(
                name=f"send_whatsapp_to_{recipient}",
                func=self._send_whatsapp_task,
                recipient=recipient,
                message=message,
                priority=3,  # High priority for messaging
            )
            
            return {
                "status": "queued",
                "task_id": task.id,
                "recipient": recipient,
                "message_preview": message[:50] + "..." if len(message) > 50 else message,
            }

        elif action_name == "read_email":
            emails = await self.email.fetch_all_emails(
                unread_only=params.get("unread_only", True),
                limit=params.get("limit", 10),
            )
            return [{
                "id": e.id,
                "provider_id": e.provider_id,
                "account": e.account_name,
                "provider": e.provider.value if e.provider else "unknown",
                "subject": e.subject,
                "sender": e.sender,
                "recipients": e.recipients[:3],
                "date": e.date.isoformat(),
                "is_read": e.is_read,
                "has_attachments": e.has_attachments,
                "body_preview": (e.body_text or "")[:500],
            } for e in emails]

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

        elif action_name == "store_memory":
            entry = await self.memory.store_memory(
                user_id=user_id,
                category=params.get("category", "note"),
                content=params.get("content", ""),
                importance=float(params.get("importance", 0.5)),
                source="user",
            )
            return {"id": entry.id, "category": entry.category, "stored": True}

        elif action_name == "list_memories":
            entries = await self.memory.list_memories(
                user_id=user_id,
                category=params.get("category"),
                limit=int(params.get("limit", 20)),
            )
            return [{
                "id": e.id,
                "category": e.category,
                "content": e.content,
                "importance": e.importance,
                "source": e.source,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            } for e in entries]

        elif action_name == "delete_memory":
            success = await self.memory.delete_memory(params.get("memory_id", ""))
            if success:
                return {"deleted": True}
            return {"error": "Memory not found"}

        elif action_name == "browse_url":
            result = await self.browser.browse_url(
                url=params.get("url", ""),
                wait_for=params.get("wait_for", "load"),
            )
            return result

        elif action_name == "browser_action":
            result = await self.browser.browser_action(
                action=params.get("action", ""),
                selector=params.get("selector", ""),
                text=params.get("text", ""),
                url=params.get("url", ""),
            )
            return result

        elif action_name == "install_package":
            """Install a Python package using pip."""
            packages = params.get("packages", [])
            if isinstance(packages, str):
                packages = [packages]
            if not packages:
                return {"error": "No packages specified"}

            # Safety: block obviously dangerous packages
            blocked = {"os", "sys", "subprocess", "shutil"}
            for pkg in packages:
                if pkg.lower().split("==")[0].split(">=")[0] in blocked:
                    return {"error": f"Package '{pkg}' is blocked for safety"}

            import subprocess as _sp
            python = sys.executable
            try:
                result = _sp.run(
                    [python, "-m", "pip", "install", *packages],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode != 0:
                    return {"error": result.stderr.strip()[:500], "packages": packages}

                # For playwright, also install browsers
                if any("playwright" in p.lower() for p in packages):
                    _sp.run([python, "-m", "playwright", "install", "chromium"],
                            capture_output=True, text=True, timeout=120)

                logger.info("package_installed", packages=packages)
                return {"installed": packages, "output": result.stdout.strip()[:300]}
            except Exception as exc:
                return {"error": str(exc), "packages": packages}

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
            
            # If 'to' looks like a name rather than a phone/email, try to find contact
            recipient = to
            contact_lookup_error = None
            
            if to and channel == "whatsapp" and not to.startswith("+") and not to.isdigit():
                # Try to find contact by name
                contact = await self.contacts.find_by_name(to)
                if contact and contact.get_primary_phone():
                    recipient = contact.get_primary_phone()
                    logger.info("resolved_contact_to_phone", name=to, phone=recipient)
                else:
                    # Contact not found - provide helpful error
                    all_contacts = await self.contacts.search("", limit=10)
                    contact_names = [c.name for c in all_contacts[:5]]
                    contact_list = ", ".join(contact_names) if contact_names else "(none found)"
                    return {"status": "error", "message": f"Could not find phone number for '{to}'. Available contacts: {contact_list}. Please use a full phone number like +31612345678."}
                    
            elif to and channel == "email" and "@" not in to:
                # Try to find contact by name for email
                contact = await self.contacts.find_by_name(to)
                if contact and contact.get_primary_email():
                    recipient = contact.get_primary_email()
                    logger.info("resolved_contact_to_email", name=to, email=recipient)
                else:
                    return {"status": "error", "message": f"Could not find email address for contact: {to}"}
            
            if channel == "whatsapp" and recipient:
                # Use send_file for local files (more reliable than file:// URLs)
                result = await self.whatsapp.send_file(
                    recipient, file_path, caption=caption,
                )
                return result
            elif channel == "email":
                success = await self.email.send_email_with_attachments(
                    to=[recipient] if recipient else [],
                    subject=params.get("subject", "File from Koda2"),
                    body_text=caption or "See attached file.",
                    attachment_paths=[file_path],
                )
                return {"sent": success}
            return {"status": "no_channel", "path": file_path}

        elif action_name == "build_capability":
            capability = params.get("capability", "")
            description = params.get("description", "")
            path = await self.self_improve.generate_plugin(capability, description)
            return {"plugin_path": path, "status": "generated"}

        elif action_name == "self_improve_code":
            request = params.get("request", "")
            if not request:
                return {"error": "No improvement request provided"}
            from koda2.supervisor.safety import SafetyGuard
            from koda2.supervisor.evolution import EvolutionEngine
            safety = SafetyGuard()
            engine = EvolutionEngine(safety)
            success, message = await engine.implement_improvement(request)
            return {"success": success, "message": message}

        # New Actions for Gaps
        elif action_name == "send_email_with_attachments":
            success = await self.email.send_email_with_attachments(
                to=params.get("to", []),
                subject=params.get("subject", ""),
                body_text=params.get("body", ""),
                body_html=params.get("body_html", ""),
                attachment_paths=params.get("attachments", []),
                cc=params.get("cc"),
                bcc=params.get("bcc"),
            )
            return {"sent": success}

        elif action_name == "download_email_attachment":
            path = await self.email.download_attachment(
                message_id=params.get("message_id", ""),
                attachment_filename=params.get("filename", ""),
                output_dir=params.get("output_dir", "data/attachments"),
            )
            return {"path": path}

        elif action_name == "sync_contacts":
            counts = await self.contacts.sync_all(force=params.get("force", False))
            summary = await self.contacts.get_contact_summary()
            return {"synced": counts, "summary": summary}

        elif action_name == "search_contacts":
            results = await self.contacts.search(
                query=params.get("query", ""),
                limit=params.get("limit", 10),
            )
            return [{"name": c.name, "phones": [p.number for p in c.phones],
                     "emails": [e.address for e in c.emails], "sources": [s.value for s in c.sources]}
                    for c in results]

        elif action_name == "find_contact_unified":
            name = params.get("name", entities.get("name", ""))
            contact = await self.contacts.find_by_name(name)
            if contact:
                return {
                    "name": contact.name,
                    "phone": contact.get_primary_phone(),
                    "email": contact.get_primary_email(),
                    "company": contact.company,
                    "has_whatsapp": contact.has_whatsapp(),
                }
            return None

        elif action_name == "generate_video":
            result = await self.video.generate(
                prompt=params.get("prompt", ""),
                image_path=params.get("image_path"),
                provider=params.get("provider"),
                duration=params.get("duration", 4),
                aspect_ratio=params.get("aspect_ratio", "16:9"),
                motion=params.get("motion", "medium"),
            )
            return {
                "status": result.status.value,
                "video_url": result.video_url,
                "video_path": result.video_path,
                "error": result.error_message,
            }

        elif action_name == "download_whatsapp_media":
            path = await self.whatsapp.download_media(
                message_id=params.get("message_id"),
                media_url=params.get("media_url"),
                output_dir=params.get("output_dir", "data/whatsapp_media"),
                filename=params.get("filename"),
            )
            return {"path": path}

        elif action_name == "get_proactive_alerts":
            alerts = await self.proactive.get_active_alerts()
            return [{"id": a.id, "type": a.type.value, "title": a.title,
                     "message": a.message, "priority": a.priority.value} for a in alerts]

        elif action_name == "start_proactive_monitoring":
            await self.proactive.start()
            return {"status": "started"}

        elif action_name == "stop_proactive_monitoring":
            await self.proactive.stop()
            return {"status": "stopped"}

        elif action_name == "get_task_status":
            task_id = params.get("task_id", "")
            task = await self.task_queue.get_task(task_id)
            if task:
                return task.to_dict()
            return {"status": "not_found", "task_id": task_id}

        elif action_name == "list_tasks":
            tasks = await self.task_queue.list_tasks(
                status=params.get("status"),
                limit=params.get("limit", 10),
            )
            return [t.to_dict() for t in tasks]

        elif action_name == "describe_command":
            """Get detailed info about a command - used by LLM for self-discovery."""
            cmd_name = params.get("command", "")
            cmd = self.commands.get(cmd_name)
            if cmd:
                return cmd.to_dict()
            return {"error": f"Command '{cmd_name}' not found", "available": [c.name for c in self.commands.list_all()[:20]]}

        elif action_name == "list_command_categories":
            """List all command categories."""
            return {
                "categories": self.commands.categories(),
                "command_counts": {
                    cat: len(self.commands.list_by_category(cat))
                    for cat in self.commands.categories()
                },
            }

        elif action_name == "run_agent_task":
            """Create and start an autonomous agent task."""
            request = params.get("request", "")
            auto_start = params.get("auto_start", True)
            
            task = await self.agent.create_task(
                user_id=user_id,
                request=request,
                auto_start=auto_start,
            )
            
            # If waiting for clarification, return questions
            if task.status.value == "waiting":
                return {
                    "task_id": task.id,
                    "status": task.status.value,
                    "questions": task.context.get("clarification_questions", []),
                    "message": "I need some clarification before I can proceed.",
                }
            
            return {
                "task_id": task.id,
                "status": task.status.value,
                "plan_steps": len(task.plan),
                "message": f"Started autonomous task with {len(task.plan)} steps. You'll be notified when complete.",
            }

        elif action_name == "get_agent_task":
            """Get status of an agent task."""
            task_id = params.get("task_id", "")
            task = await self.agent.get_task(task_id)
            if task:
                return task.to_dict()
            return {"error": "Task not found", "task_id": task_id}

        elif action_name == "list_agent_tasks":
            """List agent tasks for user."""
            tasks = await self.agent.list_tasks(
                user_id=user_id,
                status=params.get("status"),
                limit=params.get("limit", 10),
            )
            return {
                "tasks": [t.to_dict() for t in tasks],
                "total": len(tasks),
            }

        elif action_name == "cancel_agent_task":
            """Cancel a running agent task."""
            task_id = params.get("task_id", "")
            task = await self.agent.cancel_task(task_id)
            return {
                "task_id": task.id,
                "status": task.status.value,
                "message": "Task cancelled",
            }

        elif action_name == "provide_clarification":
            """Provide clarification for a waiting agent task."""
            task_id = params.get("task_id", "")
            answers = params.get("answers", {})
            task = await self.agent.provide_clarification(task_id, answers)
            return {
                "task_id": task.id,
                "status": task.status.value,
                "message": "Clarification received, continuing execution",
            }

        elif action_name == "analyze_document":
            file_path = params.get("file_path", "")
            user_message = params.get("message", "")
            analysis = await self.document_analyzer.analyze_with_context(
                file_path=file_path,
                user_message=user_message,
            )
            return {
                "file_type": analysis.file_type.value,
                "summary": analysis.summary,
                "text_content": analysis.text_content[:1000] if analysis.text_content else None,
                "image_description": analysis.image_description,
                "detected_text": analysis.detected_text,
                "key_topics": analysis.key_topics,
                "action_items": analysis.action_items,
                "title": analysis.title,
                "author": analysis.author,
                "success": analysis.is_successful(),
                "error": analysis.analysis_error,
            }

        # ── Scheduler Actions ────────────────────────────────────────────

        elif action_name == "schedule_recurring_task":
            """Schedule a recurring task via cron expression."""
            name = params.get("name", "Unnamed task")
            cron = params.get("cron", "")
            command = params.get("command", "")
            message = params.get("message", "")
            chat = params.get("chat", "")

            if command:
                async def _run_cmd():
                    return await self.macos.run_shell(command)
                task_id = self.scheduler.schedule_recurring(name=name, func=_run_cmd, cron_expression=cron)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="cron",
                    schedule_info=cron, action_type="command", action_payload=command,
                    created_by=user_id,
                )
            elif chat:
                async def _run_chat():
                    result = await self.process_message(user_id, chat, channel="scheduler")
                    response = result.get("response", "")
                    if self.whatsapp.is_configured and response:
                        try:
                            await self.whatsapp.send_message(user_id, response)
                        except Exception as exc:
                            logger.warning("scheduled_chat_send_failed", error=str(exc))
                task_id = self.scheduler.schedule_recurring(name=name, func=_run_chat, cron_expression=cron)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="cron",
                    schedule_info=cron, action_type="chat", action_payload=chat,
                    created_by=user_id,
                )
            elif message:
                async def _send_msg():
                    if self.whatsapp.is_configured:
                        await self.whatsapp.send_message("me", message)
                    else:
                        logger.warning("scheduled_message_skipped_no_whatsapp", message=message[:100])
                task_id = self.scheduler.schedule_recurring(name=name, func=_send_msg, cron_expression=cron)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="cron",
                    schedule_info=cron, action_type="message", action_payload=message,
                    created_by=user_id,
                )
            else:
                return {"error": "Provide 'command', 'message', or 'chat' for the task"}

            return {"task_id": task_id, "name": name, "schedule": cron, "type": "recurring", "status": "scheduled"}

        elif action_name == "schedule_once_task":
            """Schedule a one-time task."""
            name = params.get("name", "Unnamed task")
            run_at_str = params.get("run_at", "")
            command = params.get("command", "")
            message = params.get("message", "")
            chat = params.get("chat", "")

            try:
                run_at = dt.datetime.fromisoformat(run_at_str)
            except (ValueError, TypeError):
                return {"error": f"Invalid datetime: {run_at_str}"}

            if command:
                async def _run_cmd():
                    return await self.macos.run_shell(command)
                task_id = self.scheduler.schedule_once(name=name, func=_run_cmd, run_at=run_at)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="once",
                    schedule_info=run_at_str, action_type="command", action_payload=command,
                    created_by=user_id,
                )
            elif chat:
                async def _run_chat():
                    result = await self.process_message(user_id, chat, channel="scheduler")
                    response = result.get("response", "")
                    if self.whatsapp.is_configured and response:
                        try:
                            await self.whatsapp.send_message(user_id, response)
                        except Exception as exc:
                            logger.warning("scheduled_chat_send_failed", error=str(exc))
                task_id = self.scheduler.schedule_once(name=name, func=_run_chat, run_at=run_at)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="once",
                    schedule_info=run_at_str, action_type="chat", action_payload=chat,
                    created_by=user_id,
                )
            elif message:
                async def _send_msg():
                    if self.whatsapp.is_configured:
                        await self.whatsapp.send_message("me", message)
                    else:
                        logger.warning("scheduled_message_skipped_no_whatsapp", message=message[:100])
                task_id = self.scheduler.schedule_once(name=name, func=_send_msg, run_at=run_at)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="once",
                    schedule_info=run_at_str, action_type="message", action_payload=message,
                    created_by=user_id,
                )
            else:
                return {"error": "Provide 'command', 'message', or 'chat' for the task"}

            return {"task_id": task_id, "name": name, "run_at": run_at_str, "type": "once", "status": "scheduled"}

        elif action_name == "schedule_interval_task":
            """Schedule a task at a fixed interval."""
            name = params.get("name", "Unnamed task")
            hours = int(params.get("hours", 0))
            minutes = int(params.get("minutes", 0))
            command = params.get("command", "")
            message = params.get("message", "")
            chat = params.get("chat", "")

            if not hours and not minutes:
                return {"error": "Specify hours and/or minutes for the interval"}

            if command:
                async def _run_cmd():
                    return await self.macos.run_shell(command)
                task_id = self.scheduler.schedule_interval(name=name, func=_run_cmd, hours=hours, minutes=minutes)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="interval",
                    schedule_info=f"{hours}h{minutes}m", action_type="command", action_payload=command,
                    created_by=user_id, interval_hours=hours, interval_minutes=minutes,
                )
            elif chat:
                async def _run_chat():
                    result = await self.process_message(user_id, chat, channel="scheduler")
                    response = result.get("response", "")
                    if self.whatsapp.is_configured and response:
                        try:
                            await self.whatsapp.send_message(user_id, response)
                        except Exception as exc:
                            logger.warning("scheduled_chat_send_failed", error=str(exc))
                task_id = self.scheduler.schedule_interval(name=name, func=_run_chat, hours=hours, minutes=minutes)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="interval",
                    schedule_info=f"{hours}h{minutes}m", action_type="chat", action_payload=chat,
                    created_by=user_id, interval_hours=hours, interval_minutes=minutes,
                )
            elif message:
                async def _send_msg():
                    if self.whatsapp.is_configured:
                        await self.whatsapp.send_message("me", message)
                    else:
                        logger.warning("scheduled_message_skipped_no_whatsapp", message=message[:100])
                task_id = self.scheduler.schedule_interval(name=name, func=_send_msg, hours=hours, minutes=minutes)
                await self.scheduler.persist_task(
                    task_id=task_id, name=name, task_type="interval",
                    schedule_info=f"{hours}h{minutes}m", action_type="message", action_payload=message,
                    created_by=user_id, interval_hours=hours, interval_minutes=minutes,
                )
            else:
                return {"error": "Provide 'command', 'message', or 'chat' for the task"}

            interval = f"{hours}h{minutes}m" if hours else f"{minutes}m"
            return {"task_id": task_id, "name": name, "interval": interval, "type": "interval", "status": "scheduled"}

        elif action_name == "list_scheduled_tasks":
            """List all scheduled tasks."""
            tasks = self.scheduler.list_tasks()
            result = []
            for t in tasks:
                next_run = None
                try:
                    job = self.scheduler._scheduler.get_job(t.task_id)
                    if job and job.next_run_time:
                        next_run = job.next_run_time.isoformat()
                except Exception:
                    pass
                result.append({
                    "id": t.task_id,
                    "name": t.name,
                    "type": t.task_type,
                    "schedule": t.schedule_info,
                    "run_count": t.run_count,
                    "last_run": t.last_run.isoformat() if t.last_run else None,
                    "next_run": next_run,
                })
            return {"tasks": result, "total": len(result)}

        elif action_name == "cancel_scheduled_task":
            """Cancel a scheduled task."""
            task_id = params.get("task_id", "")
            success = self.scheduler.cancel_task(task_id)
            if success:
                return {"cancelled": True, "task_id": task_id}
            return {"error": f"Task not found: {task_id}"}

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

    async def startup(self) -> None:
        """Run startup tasks - sync contacts, start proactive monitoring, etc."""
        logger.info("orchestrator_startup_begin")
        
        # Sync contacts from all sources (including macOS Contacts.app)
        try:
            logger.info("syncing_contacts_on_startup")
            counts = await self.contacts.sync_all(force=False, persist_to_db=True)
            if counts:
                logger.info("contacts_synced_on_startup", counts=counts)
        except Exception as exc:
            logger.error("contact_sync_on_startup_failed", error=str(exc))
        
        # Start proactive monitoring
        try:
            await self.proactive.start()
            logger.info("proactive_monitoring_started")
        except Exception as exc:
            logger.error("proactive_start_failed", error=str(exc))
        
        # Start task queue for async operations
        try:
            await self.task_queue.start()
            # Register callback to notify on task completion
            async def on_task_update(task):
                if task.status.value in ("completed", "failed"):
                    logger.info(
                        "task_completed_notification",
                        task_name=task.name,
                        status=task.status.value,
                        has_result=task.result is not None,
                        error=task.error,
                    )
            self.task_queue.register_callback(on_task_update)
            logger.info("task_queue_started")
        except Exception as exc:
            logger.error("task_queue_start_failed", error=str(exc))
        
        # Register agent callbacks for notifications
        try:
            async def on_agent_update(task):
                # Notify user of agent task completion via WhatsApp
                if task.status.value in ("completed", "failed"):
                    message = f"🤖 Agent Task {task.status.value.upper()}\n\n"
                    message += f"Request: {task.original_request[:100]}...\n"
                    message += f"Progress: {task._calculate_progress()}%\n"
                    if task.result_summary:
                        message += f"\nResult: {task.result_summary}"
                    if task.error_message:
                        message += f"\nError: {task.error_message[:200]}"
                    
                    # Send to user's WhatsApp if available
                    try:
                        if self.whatsapp.is_configured:
                            await self.whatsapp.send_message(task.user_id, message)
                    except Exception as e:
                        logger.error("agent_notification_failed", error=str(e))
            
            self.agent.register_callback(on_agent_update)
            logger.info("agent_callbacks_registered")
        except Exception as exc:
            logger.error("agent_callback_registration_failed", error=str(exc))
        
        # ── Start scheduler, restore persisted tasks, register system tasks ──
        try:
            self.scheduler.set_executor(self)
            await self.scheduler.start()

            # Self-test: prove the scheduler actually fires jobs
            ok = await self.scheduler.verify()
            if not ok:
                logger.error("scheduler_BROKEN_jobs_will_not_fire")

            restored = await self.scheduler.restore_persisted_tasks()
            self._register_scheduled_tasks()
            logger.info("scheduler_ready", restored=restored, total=len(self.scheduler.list_tasks()), selftest=ok)

            # Log every job's next_run_time for diagnostics
            self.scheduler.log_job_schedule()
        except Exception as exc:
            logger.error("scheduler_start_failed", error=str(exc))
        
        # Load self-improvement plugins
        try:
            self.self_improve.load_all_plugins()
            logger.info("self_improve_plugins_loaded")
        except Exception as exc:
            logger.warning("self_improve_plugins_load_failed", error=str(exc))

        # Start improvement queue workers for self-improvement
        try:
            from koda2.supervisor.improvement_queue import get_improvement_queue
            queue = get_improvement_queue()
            if not queue.is_running:
                queue.start_worker()
                logger.info("improvement_queue_workers_started", workers=queue.max_workers)
        except Exception as exc:
            logger.warning("improvement_queue_start_failed", error=str(exc))

        logger.info("orchestrator_startup_complete")

    def _register_scheduled_tasks(self) -> None:
        """Register all recurring background tasks in the scheduler.

        System tasks are always needed, but we skip registration if a task
        with the same name already exists (e.g. restored from DB) to avoid
        duplicates.
        """
        existing_names = {t.name for t in self.scheduler.list_tasks()}

        def _already_exists(name: str) -> bool:
            if name in existing_names:
                logger.debug("system_task_already_exists", name=name)
                return True
            return False

        # ── Contact sync — every 6 hours ──
        async def _sync_contacts():
            try:
                counts = await self.contacts.sync_all(force=False, persist_to_db=True)
                logger.info("scheduled_contact_sync_done", counts=counts)
            except Exception as exc:
                logger.error("scheduled_contact_sync_failed", error=str(exc))

        if not _already_exists("Contact Sync"):
            self.scheduler.schedule_interval(
                name="Contact Sync",
                func=_sync_contacts,
                hours=6,
                # Not run_immediately — startup() already calls contacts.sync_all()
            )

        # ── Email check — every 15 minutes ──
        async def _check_email():
            try:
                from koda2.modules.email.models import EmailFilter
                emails = await self.email.fetch_emails(EmailFilter(unread_only=True, limit=5))
                if emails:
                    logger.info("scheduled_email_check", unread=len(emails))
            except Exception as exc:
                logger.error("scheduled_email_check_failed", error=str(exc))

        if not _already_exists("Email Check (unread)"):
            self.scheduler.schedule_interval(
                name="Email Check (unread)",
                func=_check_email,
                minutes=15,
                run_immediately=True,
            )

        # ── Calendar sync — every 30 minutes ──
        async def _sync_calendar():
            try:
                now = dt.datetime.now(dt.UTC)
                end = now + dt.timedelta(days=1)
                events = await self.calendar.list_events(now, end)
                logger.info("scheduled_calendar_sync", events_today=len(events))
            except Exception as exc:
                logger.error("scheduled_calendar_sync_failed", error=str(exc))

        if not _already_exists("Calendar Sync"):
            self.scheduler.schedule_interval(
                name="Calendar Sync",
                func=_sync_calendar,
                minutes=30,
                run_immediately=True,
            )

        # ── Daily morning summary — every day at 07:00 ──
        async def _daily_summary():
            try:
                now = dt.datetime.now(dt.UTC)
                end = now + dt.timedelta(days=1)
                events = await self.calendar.list_events(now, end)
                from koda2.modules.email.models import EmailFilter
                emails = await self.email.fetch_emails(EmailFilter(unread_only=True, limit=20))

                summary = f"🌅 *Goedemorgen — Koda2 Daily Summary*\n\n"
                summary += f"📅 *Agenda vandaag:* {len(events)} events\n"
                for e in events[:5]:
                    time_str = e.start.strftime("%H:%M") if e.start else "?"
                    summary += f"  • {time_str} — {e.title}\n"
                if len(events) > 5:
                    summary += f"  ... en {len(events) - 5} meer\n"
                summary += f"\n📧 *Ongelezen email:* {len(emails)}\n"
                for e in emails[:3]:
                    summary += f"  • {e.sender[:30]} — {e.subject[:40]}\n"

                tasks = self.scheduler.list_tasks()
                summary += f"\n⏰ *Actieve schedules:* {len(tasks)}"

                # Send via WhatsApp if available
                if self.whatsapp.is_configured:
                    try:
                        await self.whatsapp.send_message("me", summary)
                    except Exception:
                        pass
                logger.info("daily_summary_generated")
            except Exception as exc:
                logger.error("daily_summary_failed", error=str(exc))

        if not _already_exists("Daily Morning Summary"):
            self.scheduler.schedule_recurring(
                name="Daily Morning Summary",
                func=_daily_summary,
                cron_expression="0 7 * * *",
            )

        # ── Proactive alerts check — every 10 minutes ──
        async def _proactive_check():
            try:
                alerts = await self.proactive.get_active_alerts()
                if alerts:
                    logger.info("scheduled_proactive_alerts", count=len(alerts))
            except Exception as exc:
                logger.error("scheduled_proactive_check_failed", error=str(exc))

        if not _already_exists("Proactive Alerts Check"):
            self.scheduler.schedule_interval(
                name="Proactive Alerts Check",
                func=_proactive_check,
                minutes=10,
                run_immediately=True,
            )

        logger.info("scheduled_tasks_registered", count=len(self.scheduler.list_tasks()))

    async def shutdown(self) -> None:
        """Gracefully shutdown all services."""
        logger.info("orchestrator_shutdown_begin")
        
        # Stop agent service (pauses running tasks)
        try:
            await self.agent.shutdown()
            logger.info("agent_service_stopped")
        except Exception as exc:
            logger.error("agent_shutdown_failed", error=str(exc))
        
        # Stop task queue
        try:
            await self.task_queue.stop()
            logger.info("task_queue_stopped")
        except Exception as exc:
            logger.error("task_queue_stop_failed", error=str(exc))
        
        # Stop proactive monitoring
        try:
            await self.proactive.stop()
            logger.info("proactive_monitoring_stopped")
        except Exception as exc:
            logger.error("proactive_stop_failed", error=str(exc))
        
        # Stop scheduler
        try:
            await self.scheduler.stop()
            logger.info("scheduler_stopped")
        except Exception as exc:
            logger.error("scheduler_stop_failed", error=str(exc))
        
        logger.info("orchestrator_shutdown_complete")

    async def handle_whatsapp_message(self, payload: dict[str, Any]) -> Optional[str]:
        """Handle an incoming WhatsApp self-message with automatic document analysis.

        Only processes messages the user sends to themselves.
        Automatically detects and analyzes attached files (PDF, DOCX, XLSX, PPTX, images).
        Can send replies to anyone on the user's behalf.
        """
        logger.info("orchestrator_whatsapp_message_received", payload_preview=str(payload)[:200])
        print(f"[Koda2] WhatsApp message received: {payload.get('body', '')[:50]}...")
        
        # Check if message has media that needs analysis
        has_media = payload.get("hasMedia", False)
        
        if has_media:
            logger.info("whatsapp_message_has_media", has_media=True)
            print("[Koda2] Media detected, starting document analysis flow...")
            
            # Use the enhanced processing with document analysis
            result = await self.whatsapp.process_message_with_document_analysis(
                payload=payload,
                document_analyzer=self.document_analyzer,
                message_handler=self._handle_whatsapp_message_with_context,
            )
            
            if result and result.get("response"):
                user_id = result.get("from", "whatsapp_user")
                response = result["response"]
                
                # Clean response - remove any JSON artifacts
                response = self._clean_response_for_user(response)
                
                # Send response
                await self.whatsapp.send_typing(user_id)
                logger.info("orchestrator_sending_whatsapp_reply_with_analysis", 
                          to=user_id, response_preview=response[:100])
                print(f"[Koda2] Sending analysis reply: {response[:100]}...")
                await self._send_chunked(user_id, response, "whatsapp")
                return response
            
            return result.get("response") if result else None
        
        # No media - process as regular text message
        parsed = await self.whatsapp.process_webhook(payload)
        if parsed is None:
            logger.debug("orchestrator_whatsapp_message_ignored_not_parsed")
            return None

        text = parsed.get("text", "")
        if not text:
            logger.debug("orchestrator_whatsapp_message_empty_text")
            return None

        user_id = parsed.get("from", "whatsapp_user")

        # Commands bypass debounce — process immediately
        if text.startswith("/"):
            return await self._process_whatsapp_text(user_id, text)

        # Debounce: buffer rapid-fire messages and process as one
        # Inspired by OpenClaw's inbound-debounce.ts
        if user_id not in self._debounce_buffers:
            self._debounce_buffers[user_id] = []
        self._debounce_buffers[user_id].append(text)

        # Cancel any pending debounce task for this user
        existing_task = self._debounce_tasks.get(user_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()

        # Show typing immediately so user knows we're working
        await self.whatsapp.send_typing(user_id)

        # Schedule processing after debounce delay
        async def _debounced_process():
            await asyncio.sleep(DEBOUNCE_SECONDS)
            messages = self._debounce_buffers.pop(user_id, [])
            self._debounce_tasks.pop(user_id, None)
            if not messages:
                return
            combined = "\n".join(messages) if len(messages) > 1 else messages[0]
            if len(messages) > 1:
                logger.info("debounce_batched", user_id=user_id, count=len(messages))
            await self._process_whatsapp_text(user_id, combined)

        self._debounce_tasks[user_id] = asyncio.create_task(_debounced_process())
        return None  # Response is sent asynchronously after debounce

    async def _process_whatsapp_text(self, user_id: str, text: str) -> Optional[str]:
        """Process a WhatsApp text message (after debounce) and send the reply."""
        logger.info("orchestrator_processing_whatsapp_message", user_id=user_id, text_preview=text[:100])
        print(f"[Koda2] Processing message from {user_id}: {text[:50]}...")

        # Show typing indicator while AI is thinking
        await self.whatsapp.send_typing(user_id)

        # Route through command parser first (handles /help, /meet, /accounts, wizards, etc.)
        response = await self.whatsapp.handle_message(user_id, text)

        # Clean response - remove any JSON artifacts before sending
        response = self._clean_response_for_user(response)

        # Send the response back to the user's own chat
        if response:
            logger.info("orchestrator_sending_whatsapp_reply", to=user_id, response_preview=response[:100])
            print(f"[Koda2] Sending reply: {response[:100]}...")
            await self._send_chunked(user_id, response, "whatsapp")
        else:
            logger.warning("orchestrator_no_response_for_whatsapp_message")
            print("[Koda2] No response generated for message")

        return response
    
    async def _handle_whatsapp_message_with_context(
        self,
        user_id: str,
        text: str,
        platform: str = "whatsapp",
        original_message: str = "",
        document_analysis = None,
        **kwargs: Any,
    ) -> str:
        """Handle WhatsApp message that includes document analysis context.
        
        This is called by process_message_with_document_analysis when a file
        has been analyzed. The 'text' parameter contains the enriched prompt
        with document content, while 'original_message' is what the user actually
        sent.
        """
        logger.info("processing_message_with_document_context", 
                   user_id=user_id, 
                   has_analysis=document_analysis is not None)
        
        # Store the original message
        await self.memory.add_conversation(user_id, "user", original_message or text, channel=platform)
        
        # Create a special system prompt for document analysis
        # Note: We don't use SYSTEM_PROMPT here because it asks for JSON format
        # For document analysis, we want natural language responses
        doc_system_prompt = """You are Koda2, a professional AI executive assistant.

You have just received a document from the user via WhatsApp along with their question about it.
The document content has been analyzed and provided to you below.

Your task is to respond to the user's question about the document in a natural, helpful way.
Do NOT use JSON format. Just write a normal text response.

Guidelines:
- Answer the user's specific question about the document
- Summarize key points if asked for a summary
- Suggest action items if relevant
- If it's an image, describe what you see and any text in it
- If the document requires a response (like an invitation), draft a polite reply
- Be concise but thorough
- Write in the same language as the user's message
"""
        
        # Retrieve context
        context = self.memory.recall(text, user_id=user_id, n=3)
        context_str = "\n".join(f"- {c['content']}" for c in context) if context else "No prior context."
        
        recent = await self.memory.get_recent_conversations(user_id, limit=10)
        history_messages = [
            ChatMessage(role=c.role, content=c.content) for c in recent[-8:]
        ]
        
        system = doc_system_prompt + f"\n\nRelevant context:\n{context_str}"
        history_messages.append(ChatMessage(role="user", content=text))
        
        request = LLMRequest(
            messages=history_messages,
            system_prompt=system,
            temperature=0.3,
        )
        
        try:
            llm_response = await self.llm.complete(request)
            response_text = llm_response.content
            
            # Clean response - remove any JSON artifacts
            response_text = self._clean_response_for_user(response_text)
            
            # Store the response
            await self.memory.add_conversation(
                user_id, "assistant", response_text, channel=platform,
                model=llm_response.model, tokens_used=llm_response.total_tokens,
            )
            
            # If there was a document, store a reference to it
            if document_analysis:
                await self.memory.store_memory(
                    user_id,
                    category="document_received",
                    content=f"Analyzed {document_analysis.filename}: {document_analysis.summary or 'No summary'}"[:500],
                    importance=0.7,
                    source="whatsapp_document",
                )
            
            return response_text
            
        except RuntimeError as exc:
            logger.error("whatsapp_document_processing_failed", error=str(exc))
            return "I'm having trouble analyzing this document. Please try again or send a clearer version."
