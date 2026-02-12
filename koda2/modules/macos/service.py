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

DANGEROUS_COMMANDS = frozenset({
    "rm", "rmdir", "mkfs", "dd", "format", "fdisk",
    "shutdown", "reboot", "halt", "poweroff",
    "chmod", "chown", "kill", "killall",
})

DANGEROUS_PATTERNS = re.compile(
    r"(rm\s+-rf|>\s*/dev/|sudo\s+rm|:\(\)\{|fork\s*bomb|curl.*\|\s*sh|wget.*\|\s*sh)",
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
        """Validate a shell command for safety."""
        if DANGEROUS_PATTERNS.search(command):
            logger.warning("dangerous_command_blocked", command=command)
            return False

        try:
            tokens = shlex.split(command)
        except ValueError:
            return False

        if tokens and tokens[0] in DANGEROUS_COMMANDS:
            logger.warning("dangerous_command_blocked", command=tokens[0])
            return False

        if any(t.startswith("sudo") for t in tokens):
            logger.warning("sudo_blocked", command=command)
            return False

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
