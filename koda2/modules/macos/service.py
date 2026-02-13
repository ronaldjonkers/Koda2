"""macOS system integration — AppleScript, Contacts, shell commands."""

from __future__ import annotations

import asyncio
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Optional

from koda2.logging_config import get_logger

logger = get_logger(__name__)

# DANGEROUS_COMMANDS - commands that can cause system damage
# These are blocked entirely unless they are part of a safe pattern
DANGEROUS_COMMANDS = frozenset({
    "mkfs", "dd", "format", "fdisk",
    "shutdown", "reboot", "halt", "poweroff",
})

# DESTRUCTIVE_COMMANDS - commands that delete/modify files
# These require extra validation to ensure they're not deleting system files
DESTRUCTIVE_COMMANDS = frozenset({
    "rm", "rmdir", "chmod", "chown", "kill", "killall",
})

DANGEROUS_PATTERNS = re.compile(
    r"(rm\s+-rf\s+/\s*$|rm\s+-rf\s+/[^a-z]|:\(\)\{|fork\s*bomb|curl.*\|\s*sh|wget.*\|\s*sh|>\s*/dev/[sh]d|>\s*/dev/disk)",
    re.IGNORECASE,
)


class MacOSService:
    """macOS system integration via AppleScript and shell commands."""

    # ── AppleScript Execution ────────────────────────────────────────

    async def run_applescript(self, script: str) -> str:
        """Execute an AppleScript and return the result."""
        logger.debug("applescript_executing", script=script[:200])
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.error("applescript_error", stderr=result.stderr)
                raise RuntimeError(f"AppleScript error: {result.stderr}")
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            raise RuntimeError("AppleScript timed out after 30 seconds")

    # ── Apple Contacts ───────────────────────────────────────────────

    async def get_contacts(self, search: Optional[str] = None) -> list[dict[str, Any]]:
        """Retrieve contacts from Apple Contacts.app."""
        if search:
            script = f'''
            tell application "Contacts"
                set matchingPeople to (every person whose name contains "{search}")
                set results to {{}}
                repeat with p in matchingPeople
                    set pName to name of p
                    set pEmails to value of every email of p
                    set pPhones to value of every phone of p
                    set pBday to ""
                    try
                        set pBday to birth date of p as string
                    end try
                    set end of results to pName & "|" & (pEmails as string) & "|" & (pPhones as string) & "|" & pBday
                end repeat
                return results as string
            end tell
            '''
        else:
            script = '''
            tell application "Contacts"
                set results to {}
                repeat with p in (every person)
                    set pName to name of p
                    set pEmails to value of every email of p
                    set pPhones to value of every phone of p
                    set pBday to ""
                    try
                        set pBday to birth date of p as string
                    end try
                    set end of results to pName & "|" & (pEmails as string) & "|" & (pPhones as string) & "|" & pBday
                end repeat
                return results as string
            end tell
            '''
        raw = await self.run_applescript(script)
        contacts = []
        for line in raw.split(", "):
            parts = line.split("|")
            if len(parts) >= 1:
                contact: dict[str, Any] = {"name": parts[0].strip()}
                if len(parts) > 1:
                    contact["emails"] = [e.strip() for e in parts[1].split(",") if e.strip()]
                if len(parts) > 2:
                    contact["phones"] = [p.strip() for p in parts[2].split(",") if p.strip()]
                if len(parts) > 3 and parts[3].strip():
                    contact["birthday"] = parts[3].strip()
                contacts.append(contact)
        return contacts

    async def find_contact(self, name: str) -> Optional[dict[str, Any]]:
        """Find a single contact by name."""
        contacts = await self.get_contacts(search=name)
        return contacts[0] if contacts else None

    # ── Apple Calendar ───────────────────────────────────────────────

    async def get_apple_calendar_events(self, days_ahead: int = 7) -> str:
        """Get upcoming events from Apple Calendar.app."""
        script = f'''
        tell application "Calendar"
            set today to current date
            set endDate to today + ({days_ahead} * days)
            set results to ""
            repeat with cal in calendars
                set evts to (every event of cal whose start date >= today and start date <= endDate)
                repeat with e in evts
                    set results to results & summary of e & " | " & (start date of e as string) & " | " & (end date of e as string) & linefeed
                end repeat
            end repeat
            return results
        end tell
        '''
        return await self.run_applescript(script)

    # ── Apple Reminders ──────────────────────────────────────────────

    async def create_reminder(self, title: str, due_date: Optional[str] = None, notes: str = "") -> str:
        """Create a reminder in Apple Reminders.app."""
        parts = [f'make new reminder with properties {{name:"{title}"']
        if notes:
            parts[0] += f', body:"{notes}"'
        parts[0] += "}"

        script = f'''
        tell application "Reminders"
            tell list "Reminders"
                {parts[0]}
            end tell
        end tell
        '''
        await self.run_applescript(script)
        return f"Reminder created: {title}"

    # ── Secure Shell Execution ───────────────────────────────────────

    def _validate_command(self, command: str) -> bool:
        """Validate a shell command for safety.
        
        Allows most read-only commands (cat, ls, find, grep, etc.)
        Blocks destructive commands that can harm the system.
        """
        # Check for obviously dangerous patterns
        if DANGEROUS_PATTERNS.search(command):
            logger.warning("dangerous_pattern_blocked", command=command)
            return False

        # Allow empty commands
        if not command or not command.strip():
            return False

        # Extract the main command (before any pipes, redirects, etc.)
        # Split by common shell operators
        main_cmd = command
        for sep in ['|', '>', '<', ';', '&', '&&', '||']:
            if sep in main_cmd:
                main_cmd = main_cmd.split(sep)[0]
        
        main_cmd = main_cmd.strip()
        
        # Get the first token (the actual command)
        try:
            tokens = shlex.split(main_cmd)
        except ValueError:
            # If shlex fails, try simple split
            tokens = main_cmd.split()
        
        if not tokens:
            return False
            
        cmd = tokens[0]
        
        # Block truly dangerous commands
        if cmd in DANGEROUS_COMMANDS:
            logger.warning("dangerous_command_blocked", command=cmd)
            return False
        
        # Allow destructive commands only with safe arguments
        if cmd in DESTRUCTIVE_COMMANDS:
            # Check if it's trying to delete system directories
            command_lower = command.lower()
            system_paths = ['/system', '/bin', '/sbin', '/usr/bin', '/usr/sbin', '/etc', '/dev', '/var']
            for path in system_paths:
                if path in command_lower and 'rm' in command_lower:
                    logger.warning("system_deletion_blocked", command=command)
                    return False
            # Otherwise allow it - user wants full access
            return True

        # Block sudo (requires password anyway)
        if cmd == "sudo" or command.startswith("sudo "):
            logger.warning("sudo_blocked", command=command)
            return False

        # Everything else is allowed - user wants full computer access
        return True

    async def run_shell(
        self,
        command: str,
        cwd: Optional[str] = None,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Execute a shell command with security sanitization.

        Returns dict with 'stdout', 'stderr', 'returncode'.
        """
        if not self._validate_command(command):
            raise PermissionError(f"Command blocked by security policy: {command}")

        logger.info("shell_executing", command=command, cwd=cwd)
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                command, shell=True,
                capture_output=True, text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Command timed out after {timeout}s: {command}")

    # ── File System Access ───────────────────────────────────────────

    async def list_directory(self, path: str) -> list[dict[str, Any]]:
        """List files in a directory safely."""
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        if not p.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")

        entries = []
        for item in sorted(p.iterdir()):
            entry: dict[str, Any] = {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "path": str(item),
            }
            if item.is_file():
                stat = item.stat()
                entry["size"] = stat.st_size
                entry["modified"] = stat.st_mtime
            entries.append(entry)
        return entries

    async def read_file(self, path: str) -> str:
        """Read a text file safely."""
        p = Path(path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not p.is_file():
            raise IsADirectoryError(f"Not a file: {path}")
        if p.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("File too large (>10MB)")
        return p.read_text(encoding="utf-8", errors="replace")

    async def write_file(self, path: str, content: str, mkdir: bool = True) -> str:
        """Write content to a text file safely.

        Args:
            path: Target file path (~ expanded, resolved to absolute).
            content: Text content to write.
            mkdir: Create parent directories if they don't exist.

        Returns:
            Absolute path of the written file.
        """
        p = Path(path).expanduser().resolve()
        if mkdir:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        logger.info("file_written", path=str(p), size=len(content))
        return str(p)

    async def file_exists(self, path: str) -> dict[str, Any]:
        """Check if a file or directory exists and return info."""
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"exists": False, "path": str(p)}
        stat = p.stat()
        return {
            "exists": True,
            "path": str(p),
            "type": "directory" if p.is_dir() else "file",
            "size": stat.st_size if p.is_file() else None,
            "modified": stat.st_mtime,
        }
