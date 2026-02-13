"""Command Registry - maintains knowledge of all available assistant actions.

This module provides a central registry of all commands/actions that the assistant
can perform. It's used for:
1. Documentation generation
2. Command discovery
3. LLM context enhancement
4. Validation

To add a new command:
1. Define it in the COMMANDS dictionary below
2. Implement the handler in orchestrator._execute_action()
3. Optionally add CLI support in cli/commands.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CommandParameter:
    """Parameter definition for a command."""
    name: str
    type: str
    required: bool = True
    default: Any = None
    description: str = ""


@dataclass
class Command:
    """Definition of an available command/action."""
    name: str
    description: str
    parameters: list[CommandParameter] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    notes: str = ""
    category: str = "general"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert command to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "required": p.required,
                    "default": p.default,
                    "description": p.description,
                }
                for p in self.parameters
            ],
            "examples": self.examples,
            "notes": self.notes,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# COMMAND DEFINITIONS - All available assistant actions
# ═══════════════════════════════════════════════════════════════════════════════

COMMANDS: dict[str, Command] = {
    # ── Messaging Commands ─────────────────────────────────────────────────────
    "send_whatsapp": Command(
        name="send_whatsapp",
        category="messaging",
        description="Send a WhatsApp message to a contact or phone number. Uses task queue for async processing.",
        parameters=[
            CommandParameter("to", "string", True, description="Phone number (+316...) or contact name (Jan)"),
            CommandParameter("message", "string", True, description="Message text to send"),
        ],
        examples=[
            '{"action": "send_whatsapp", "params": {"to": "+31612345678", "message": "Hello!"}}',
            '{"action": "send_whatsapp", "params": {"to": "Jan", "message": "See you tomorrow"}}',
        ],
        notes="Contact names are automatically resolved to phone numbers via the contacts database. Uses async task queue.",
    ),
    
    "send_file": Command(
        name="send_file",
        category="messaging",
        description="Send a file via WhatsApp or Email",
        parameters=[
            CommandParameter("path", "string", True, description="Path to the file"),
            CommandParameter("channel", "string", True, description="'whatsapp' or 'email'"),
            CommandParameter("to", "string", True, description="Recipient (phone, email, or contact name)"),
            CommandParameter("caption", "string", False, "", "Optional message/caption"),
        ],
        examples=[
            '{"action": "send_file", "params": {"path": "report.pdf", "channel": "whatsapp", "to": "Jan"}}',
            '{"action": "send_file", "params": {"path": "data.xlsx", "channel": "email", "to": "jan@example.com"}}',
        ],
    ),
    
    "send_email": Command(
        name="send_email",
        category="messaging",
        description="Send a simple email (no attachments)",
        parameters=[
            CommandParameter("to", "array", True, description="List of recipient email addresses"),
            CommandParameter("subject", "string", True, description="Email subject"),
            CommandParameter("body", "string", True, description="Plain text body"),
            CommandParameter("body_html", "string", False, None, "Optional HTML body"),
        ],
        examples=[
            '{"action": "send_email", "params": {"to": ["jan@example.com"], "subject": "Hello", "body": "Hi there"}}',
        ],
    ),
    
    "send_email_with_attachments": Command(
        name="send_email_with_attachments",
        category="messaging",
        description="Send email with file attachments",
        parameters=[
            CommandParameter("to", "array", True, description="List of recipient emails"),
            CommandParameter("subject", "string", True, description="Email subject"),
            CommandParameter("body", "string", True, description="Email body"),
            CommandParameter("attachments", "array", False, [], "List of file paths"),
            CommandParameter("cc", "array", False, None, "CC recipients"),
            CommandParameter("bcc", "array", False, None, "BCC recipients"),
        ],
        examples=[
            '{"action": "send_email_with_attachments", "params": {"to": ["jan@example.com"], "subject": "Report", "body": "See attached", "attachments": ["report.pdf"]}}',
        ],
    ),
    
    # ── Contact Commands ────────────────────────────────────────────────────────
    "find_contact": Command(
        name="find_contact",
        category="contacts",
        description="Find a contact by name (searches macOS, WhatsApp, Gmail, Exchange)",
        parameters=[
            CommandParameter("name", "string", True, description="Name to search for"),
        ],
        examples=[
            '{"action": "find_contact", "params": {"name": "Jan"}}',
        ],
        notes="Returns contact info including phone numbers, emails, company, etc.",
    ),
    
    "search_contacts": Command(
        name="search_contacts",
        category="contacts",
        description="Search contacts with optional query",
        parameters=[
            CommandParameter("query", "string", False, "", "Search query"),
            CommandParameter("limit", "integer", False, 10, "Max results"),
        ],
        examples=[
            '{"action": "search_contacts", "params": {"query": "john", "limit": 5}}',
        ],
    ),
    
    "sync_contacts": Command(
        name="sync_contacts",
        category="contacts",
        description="Sync contacts from all sources (macOS, WhatsApp, Gmail, Exchange)",
        parameters=[
            CommandParameter("force", "boolean", False, False, "Force full re-sync"),
        ],
        examples=[
            '{"action": "sync_contacts", "params": {"force": true}}',
        ],
    ),
    
    # ── Calendar Commands ───────────────────────────────────────────────────────
    "check_calendar": Command(
        name="check_calendar",
        category="calendar",
        description="Check calendar events for a date range",
        parameters=[
            CommandParameter("start", "string", True, description="ISO datetime (e.g., 2024-01-15T09:00:00)"),
            CommandParameter("end", "string", True, description="ISO datetime"),
        ],
        examples=[
            '{"action": "check_calendar", "params": {"start": "2024-01-15T00:00:00", "end": "2024-01-15T23:59:59"}}',
        ],
    ),
    
    "schedule_meeting": Command(
        name="schedule_meeting",
        category="calendar",
        description="Schedule a new meeting/event",
        parameters=[
            CommandParameter("title", "string", True, description="Meeting title"),
            CommandParameter("start", "string", True, description="ISO datetime"),
            CommandParameter("end", "string", True, description="ISO datetime"),
            CommandParameter("location", "string", False, "", "Meeting location"),
            CommandParameter("description", "string", False, "", "Meeting description"),
            CommandParameter("attendee_email", "string", False, None, "Primary attendee email"),
        ],
        examples=[
            '{"action": "schedule_meeting", "params": {"title": "Team Sync", "start": "2024-01-15T14:00:00", "end": "2024-01-15T15:00:00"}}',
        ],
    ),
    
    "create_reminder": Command(
        name="create_reminder",
        category="calendar",
        description="Create a reminder (uses macOS Reminders)",
        parameters=[
            CommandParameter("title", "string", True, description="Reminder title"),
            CommandParameter("notes", "string", False, "", "Additional notes"),
        ],
        examples=[
            '{"action": "create_reminder", "params": {"title": "Call John", "notes": "About the project"}}',
        ],
    ),
    
    # ── File System Commands ────────────────────────────────────────────────────
    "run_shell": Command(
        name="run_shell",
        category="files",
        description="Execute a shell command (FULL ACCESS - cat, ls, find, grep, etc.)",
        parameters=[
            CommandParameter("command", "string", True, description="Shell command to execute"),
            CommandParameter("cwd", "string", False, None, "Working directory"),
            CommandParameter("timeout", "integer", False, 30, "Timeout in seconds"),
        ],
        examples=[
            '{"action": "run_shell", "params": {"command": "ls -la ~/Documents"}}',
            '{"action": "run_shell", "params": {"command": "find . -name *.pdf"}}',
        ],
        notes="Safe commands: cat, ls, find, grep, ps, etc. Blocked: sudo, rm on system paths, mkfs, dd, shutdown",
    ),
    
    "list_directory": Command(
        name="list_directory",
        category="files",
        description="List contents of a directory",
        parameters=[
            CommandParameter("path", "string", True, description="Directory path"),
        ],
        examples=[
            '{"action": "list_directory", "params": {"path": "."}}',
            '{"action": "list_directory", "params": {"path": "~/Documents"}}',
        ],
    ),
    
    "read_file": Command(
        name="read_file",
        category="files",
        description="Read contents of a file",
        parameters=[
            CommandParameter("path", "string", True, description="File path"),
        ],
        examples=[
            '{"action": "read_file", "params": {"path": "document.txt"}}',
        ],
    ),
    
    "write_file": Command(
        name="write_file",
        category="files",
        description="Write content to a file",
        parameters=[
            CommandParameter("path", "string", True, description="File path"),
            CommandParameter("content", "string", True, description="Content to write"),
        ],
        examples=[
            '{"action": "write_file", "params": {"path": "notes.txt", "content": "Hello world"}}',
        ],
    ),
    
    "file_exists": Command(
        name="file_exists",
        category="files",
        description="Check if a file or directory exists",
        parameters=[
            CommandParameter("path", "string", True, description="Path to check"),
        ],
        examples=[
            '{"action": "file_exists", "params": {"path": "document.pdf"}}',
        ],
    ),
    
    # ── Document Generation Commands ────────────────────────────────────────────
    "generate_document": Command(
        name="generate_document",
        category="documents",
        description="Generate a document (DOCX, XLSX, PDF, PPTX)",
        parameters=[
            CommandParameter("type", "string", True, description="'docx', 'xlsx', 'pdf', or 'pptx'"),
            CommandParameter("filename", "string", True, description="Output filename"),
            CommandParameter("title", "string", True, description="Document title"),
            CommandParameter("content", "array", True, description="Content items (see docs)"),
        ],
        examples=[
            '{"action": "generate_document", "params": {"type": "docx", "filename": "report.docx", "title": "Report", "content": [{"type": "heading", "text": "Summary"}]}}',
        ],
    ),
    
    "analyze_document": Command(
        name="analyze_document",
        category="documents",
        description="Analyze content of PDF, DOCX, XLSX, PPTX, or images",
        parameters=[
            CommandParameter("file_path", "string", True, description="Path to file"),
            CommandParameter("message", "string", False, "", "Specific question about the document"),
        ],
        examples=[
            '{"action": "analyze_document", "params": {"file_path": "contract.pdf"}}',
            '{"action": "analyze_document", "params": {"file_path": "chart.png", "message": "What does this chart show?"}}',
        ],
    ),
    
    # ── AI Generation Commands ──────────────────────────────────────────────────
    "generate_image": Command(
        name="generate_image",
        category="ai",
        description="Generate an image using AI",
        parameters=[
            CommandParameter("prompt", "string", True, description="Image description"),
            CommandParameter("size", "string", False, "1024x1024", "Image size"),
        ],
        examples=[
            '{"action": "generate_image", "params": {"prompt": "A cat in space", "size": "1024x1024"}}',
        ],
    ),
    
    "analyze_image": Command(
        name="analyze_image",
        category="ai",
        description="Analyze an image using AI vision",
        parameters=[
            CommandParameter("image_url", "string", True, description="URL or path to image"),
            CommandParameter("prompt", "string", False, "", "Specific question about the image"),
        ],
        examples=[
            '{"action": "analyze_image", "params": {"image_url": "photo.jpg", "prompt": "What is in this image?"}}',
        ],
    ),
    
    "generate_video": Command(
        name="generate_video",
        category="ai",
        description="Generate a video using AI",
        parameters=[
            CommandParameter("prompt", "string", True, description="Video description"),
            CommandParameter("duration", "integer", False, 4, "Duration in seconds"),
            CommandParameter("aspect_ratio", "string", False, "16:9", "Aspect ratio"),
        ],
        examples=[
            '{"action": "generate_video", "params": {"prompt": "A robot dancing", "duration": 4}}',
        ],
    ),
    
    # ── Email Commands ──────────────────────────────────────────────────────────
    "read_email": Command(
        name="read_email",
        category="email",
        description="Fetch emails from inbox",
        parameters=[
            CommandParameter("unread_only", "boolean", False, True, "Only show unread"),
            CommandParameter("limit", "integer", False, 10, "Max emails to fetch"),
        ],
        examples=[
            '{"action": "read_email", "params": {"unread_only": true, "limit": 5}}',
        ],
    ),
    
    "download_email_attachment": Command(
        name="download_email_attachment",
        category="email",
        description="Download an attachment from an email",
        parameters=[
            CommandParameter("message_id", "string", True, description="Email message ID"),
            CommandParameter("filename", "string", True, description="Attachment filename"),
        ],
        examples=[
            '{"action": "download_email_attachment", "params": {"message_id": "abc123", "filename": "report.pdf"}}',
        ],
    ),
    
    # ── Memory Commands ─────────────────────────────────────────────────────────
    "search_memory": Command(
        name="search_memory",
        category="memory",
        description="Search conversation history and stored memories",
        parameters=[
            CommandParameter("query", "string", True, description="Search query"),
        ],
        examples=[
            '{"action": "search_memory", "params": {"query": "meeting with John"}}',
        ],
    ),
    
    # ── Task Queue Commands ─────────────────────────────────────────────────────
    "get_task_status": Command(
        name="get_task_status",
        category="tasks",
        description="Get status of a queued task",
        parameters=[
            CommandParameter("task_id", "string", True, description="Task ID"),
        ],
        examples=[
            '{"action": "get_task_status", "params": {"task_id": "abc-123"}}',
        ],
    ),
    
    "list_tasks": Command(
        name="list_tasks",
        category="tasks",
        description="List all tasks in the queue",
        parameters=[
            CommandParameter("status", "string", False, None, "Filter: pending|running|completed|failed"),
            CommandParameter("limit", "integer", False, 10, "Max results"),
        ],
        examples=[
            '{"action": "list_tasks", "params": {"status": "running"}}',
        ],
    ),
    
    # ── Proactive Commands ──────────────────────────────────────────────────────
    "get_proactive_alerts": Command(
        name="get_proactive_alerts",
        category="proactive",
        description="Get current proactive alerts and suggestions",
        parameters=[],
        examples=[
            '{"action": "get_proactive_alerts", "params": {}}',
        ],
    ),
    
    "start_proactive_monitoring": Command(
        name="start_proactive_monitoring",
        category="proactive",
        description="Start proactive monitoring daemon",
        parameters=[],
        examples=[
            '{"action": "start_proactive_monitoring", "params": {}}',
        ],
    ),
    
    "stop_proactive_monitoring": Command(
        name="stop_proactive_monitoring",
        category="proactive",
        description="Stop proactive monitoring daemon",
        parameters=[],
        examples=[
            '{"action": "stop_proactive_monitoring", "params": {}}',
        ],
    ),
    
    # ── WhatsApp Media Commands ─────────────────────────────────────────────────
    "download_whatsapp_media": Command(
        name="download_whatsapp_media",
        category="whatsapp",
        description="Download media from a WhatsApp message",
        parameters=[
            CommandParameter("message_id", "string", True, description="WhatsApp message ID"),
            CommandParameter("filename", "string", False, None, "Custom filename"),
        ],
        examples=[
            '{"action": "download_whatsapp_media", "params": {"message_id": "abc123"}}',
        ],
    ),
    
    # ── Scheduler Commands ──────────────────────────────────────────────────────
    "schedule_recurring_task": Command(
        name="schedule_recurring_task",
        category="scheduler",
        description="Schedule a recurring task using a cron expression (minute hour day month weekday). The task will run a shell command or send a message at the specified schedule.",
        parameters=[
            CommandParameter("name", "string", True, description="Human-readable name for the task"),
            CommandParameter("cron", "string", True, description="Cron expression: minute hour day month weekday (e.g. '0 9 * * 1-5' for weekdays at 9am)"),
            CommandParameter("command", "string", False, None, "Shell command to run"),
            CommandParameter("message", "string", False, None, "Message to send via WhatsApp (alternative to command)"),
        ],
        examples=[
            '{"action": "schedule_recurring_task", "params": {"name": "Daily backup", "cron": "0 2 * * *", "command": "tar -czf /tmp/backup.tar.gz ~/Documents"}}',
            '{"action": "schedule_recurring_task", "params": {"name": "Weekly report reminder", "cron": "0 9 * * 1", "message": "Reminder: weekly report is due today"}}',
        ],
    ),

    "schedule_once_task": Command(
        name="schedule_once_task",
        category="scheduler",
        description="Schedule a one-time task at a specific date/time. The task will run a shell command or send a message.",
        parameters=[
            CommandParameter("name", "string", True, description="Human-readable name for the task"),
            CommandParameter("run_at", "string", True, description="ISO datetime when to run (e.g. '2026-02-14T09:00:00')"),
            CommandParameter("command", "string", False, None, "Shell command to run"),
            CommandParameter("message", "string", False, None, "Message to send via WhatsApp (alternative to command)"),
        ],
        examples=[
            '{"action": "schedule_once_task", "params": {"name": "Deploy release", "run_at": "2026-02-14T09:00:00", "command": "cd /app && ./deploy.sh"}}',
        ],
    ),

    "schedule_interval_task": Command(
        name="schedule_interval_task",
        category="scheduler",
        description="Schedule a task that repeats at a fixed interval (hours/minutes). The task will run a shell command or send a message.",
        parameters=[
            CommandParameter("name", "string", True, description="Human-readable name for the task"),
            CommandParameter("hours", "integer", False, 0, "Repeat every N hours"),
            CommandParameter("minutes", "integer", False, 0, "Repeat every N minutes"),
            CommandParameter("command", "string", False, None, "Shell command to run"),
            CommandParameter("message", "string", False, None, "Message to send via WhatsApp (alternative to command)"),
        ],
        examples=[
            '{"action": "schedule_interval_task", "params": {"name": "Health check", "minutes": 5, "command": "curl -s http://localhost:8000/api/health"}}',
        ],
    ),

    "list_scheduled_tasks": Command(
        name="list_scheduled_tasks",
        category="scheduler",
        description="List all scheduled tasks with their schedule, last run time, and next run time",
        parameters=[],
        examples=[
            '{"action": "list_scheduled_tasks", "params": {}}',
        ],
    ),

    "cancel_scheduled_task": Command(
        name="cancel_scheduled_task",
        category="scheduler",
        description="Cancel a scheduled task by its ID",
        parameters=[
            CommandParameter("task_id", "string", True, description="ID of the scheduled task to cancel"),
        ],
        examples=[
            '{"action": "cancel_scheduled_task", "params": {"task_id": "abc-123"}}',
        ],
    ),

    # ── System Commands ─────────────────────────────────────────────────────────
    "build_capability": Command(
        name="build_capability",
        category="system",
        description="Generate a new plugin/capability",
        parameters=[
            CommandParameter("capability", "string", True, description="What to build"),
            CommandParameter("description", "string", True, description="Detailed description"),
        ],
        examples=[
            '{"action": "build_capability", "params": {"capability": "weather_check", "description": "Check weather for a city"}}',
        ],
    ),
}


class CommandRegistry:
    """Registry of all available commands."""
    
    def __init__(self, commands: Optional[dict[str, Command]] = None):
        self._commands = commands or COMMANDS
    
    def get(self, name: str) -> Optional[Command]:
        """Get a command by name."""
        return self._commands.get(name)
    
    def list_all(self) -> list[Command]:
        """List all commands."""
        return list(self._commands.values())
    
    def list_by_category(self, category: str) -> list[Command]:
        """List commands in a category."""
        return [c for c in self._commands.values() if c.category == category]
    
    def categories(self) -> list[str]:
        """Get all categories."""
        return sorted(set(c.category for c in self._commands.values()))
    
    def search(self, query: str) -> list[Command]:
        """Search commands by name or description."""
        query = query.lower()
        return [
            c for c in self._commands.values()
            if query in c.name.lower() or query in c.description.lower()
        ]
    
    def to_dict(self) -> dict[str, Any]:
        """Export all commands as dictionary."""
        return {
            "commands": {name: cmd.to_dict() for name, cmd in self._commands.items()},
            "categories": self.categories(),
            "total": len(self._commands),
        }
    
    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Convert all commands to OpenAI function-calling tool definitions.
        
        This format is also used by OpenRouter and converted for Anthropic.
        """
        tools = []
        for cmd in self._commands.values():
            properties: dict[str, Any] = {}
            required: list[str] = []
            for p in cmd.parameters:
                prop: dict[str, Any] = {"description": p.description}
                # Map our types to JSON Schema types
                type_map = {
                    "string": "string",
                    "integer": "integer",
                    "boolean": "boolean",
                    "array": "array",
                    "number": "number",
                }
                prop["type"] = type_map.get(p.type, "string")
                if p.type == "array":
                    prop["items"] = {"type": "string"}
                if p.default is not None and p.default != "":
                    prop["default"] = p.default
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)
            
            tools.append({
                "type": "function",
                "function": {
                    "name": cmd.name,
                    "description": cmd.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            })
        return tools

    def get_system_prompt_addition(self) -> str:
        """Get formatted command reference for system prompt."""
        lines = [
            "",
            "═" * 60,
            "AVAILABLE COMMANDS REFERENCE",
            "═" * 60,
            "",
            f"Total commands available: {len(self._commands)}",
            f"Categories: {', '.join(self.categories())}",
            "",
            "QUICK REFERENCE BY CATEGORY:",
        ]
        
        for category in self.categories():
            cmds = self.list_by_category(category)
            lines.append(f"\n{category.upper()}:")
            for cmd in cmds:
                lines.append(f"  • {cmd.name}: {cmd.description}")
        
        lines.extend([
            "",
            "For detailed info on any command, use the 'describe_command' function",
            "or reference: koda2/modules/commands/registry.py",
            "",
            "IMPORTANT NOTES:",
            "• Contact names are automatically resolved to phone/email",
            "• send_whatsapp uses task queue for reliability",
            "• Shell commands have full access except dangerous system operations",
            "",
        ])
        
        return "\n".join(lines)


# Global registry instance
_registry: Optional[CommandRegistry] = None


def get_registry() -> CommandRegistry:
    """Get the global command registry."""
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry
