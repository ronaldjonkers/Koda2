"""Safety guardrails for the self-healing supervisor.

Provides git-based backup/rollback, retry limits, and audit logging
to ensure the supervisor never leaves the codebase in a broken state.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from koda2.logging_config import get_logger

logger = get_logger(__name__)

# Limits
MAX_REPAIR_ATTEMPTS = 3          # per unique crash signature
MAX_RESTARTS_PER_WINDOW = 5      # max restarts in RESTART_WINDOW_SECONDS
RESTART_WINDOW_SECONDS = 600     # 10 minutes
AUDIT_LOG_DIR = Path("data/supervisor")
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "audit_log.jsonl"
REPAIR_STATE_FILE = AUDIT_LOG_DIR / "repair_state.json"
PROJECT_ROOT = Path(__file__).parent.parent.parent


class SafetyGuard:
    """Git-based safety net for code modifications."""

    def __init__(self, project_root: Optional[Path] = None) -> None:
        self._root = project_root or PROJECT_ROOT
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._repair_counts: dict[str, int] = {}
        self._restart_times: list[float] = []
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted repair state."""
        if REPAIR_STATE_FILE.exists():
            try:
                data = json.loads(REPAIR_STATE_FILE.read_text())
                self._repair_counts = data.get("repair_counts", {})
            except Exception:
                self._repair_counts = {}

    def _save_state(self) -> None:
        """Persist repair state to disk."""
        REPAIR_STATE_FILE.write_text(json.dumps({
            "repair_counts": self._repair_counts,
            "updated_at": dt.datetime.now().isoformat(),
        }, indent=2))

    def audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        """Append an entry to the audit log."""
        entry = {
            "timestamp": dt.datetime.now().isoformat(),
            "action": action,
            **(details or {}),
        }
        try:
            with open(AUDIT_LOG_FILE, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.error("audit_log_write_failed", error=str(exc))
        logger.info("supervisor_audit", action=action, details=details)

    # ── Git Operations ────────────────────────────────────────────────

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command in the project root."""
        return subprocess.run(
            ["git", *args],
            cwd=str(self._root),
            capture_output=True,
            text=True,
            check=check,
        )

    def git_stash(self, message: str = "supervisor-backup") -> bool:
        """Stash current changes as a safety backup before patching."""
        try:
            result = self._git("stash", "push", "-m", message, check=False)
            stashed = "No local changes" not in result.stdout
            if stashed:
                self.audit("git_stash", {"message": message})
            return stashed
        except Exception as exc:
            logger.error("git_stash_failed", error=str(exc))
            return False

    def git_stash_pop(self) -> bool:
        """Restore stashed changes (rollback)."""
        try:
            self._git("stash", "pop")
            self.audit("git_stash_pop")
            return True
        except Exception as exc:
            logger.error("git_stash_pop_failed", error=str(exc))
            return False

    def git_commit(self, message: str) -> bool:
        """Stage all changes and commit."""
        try:
            self._git("add", ".")
            self._git("commit", "-m", message)
            self.audit("git_commit", {"message": message})
            return True
        except Exception as exc:
            logger.error("git_commit_failed", error=str(exc))
            return False

    def git_push(self) -> bool:
        """Push to remote."""
        try:
            self._git("push")
            self.audit("git_push")
            return True
        except Exception as exc:
            logger.error("git_push_failed", error=str(exc))
            return False

    def git_diff(self) -> str:
        """Get current uncommitted diff."""
        try:
            result = self._git("diff", check=False)
            return result.stdout
        except Exception:
            return ""

    def git_reset_hard(self) -> bool:
        """Hard reset to HEAD (nuclear rollback)."""
        try:
            self._git("checkout", ".")
            self.audit("git_reset_hard")
            return True
        except Exception as exc:
            logger.error("git_reset_hard_failed", error=str(exc))
            return False

    # ── Retry Limits ──────────────────────────────────────────────────

    def crash_signature(self, error: str) -> str:
        """Generate a signature from an error for deduplication.

        Extracts the last meaningful line (file + error type) to group
        identical crashes together.
        """
        lines = [l.strip() for l in error.strip().splitlines() if l.strip()]
        # Find the actual error line (usually last non-empty line)
        for line in reversed(lines):
            if "Error" in line or "Exception" in line:
                return line[:200]
        return lines[-1][:200] if lines else "unknown_crash"

    def can_attempt_repair(self, error: str) -> bool:
        """Check if we haven't exceeded repair attempts for this crash type."""
        sig = self.crash_signature(error)
        count = self._repair_counts.get(sig, 0)
        return count < MAX_REPAIR_ATTEMPTS

    def record_repair_attempt(self, error: str, success: bool) -> None:
        """Record a repair attempt for rate limiting."""
        sig = self.crash_signature(error)
        self._repair_counts[sig] = self._repair_counts.get(sig, 0) + 1
        self._save_state()
        self.audit("repair_attempt", {
            "signature": sig,
            "attempt": self._repair_counts[sig],
            "success": success,
        })

    def clear_repair_count(self, error: str) -> None:
        """Clear repair count after successful fix."""
        sig = self.crash_signature(error)
        self._repair_counts.pop(sig, None)
        self._save_state()

    # ── Restart Rate Limiting ─────────────────────────────────────────

    def can_restart(self) -> bool:
        """Check if we haven't exceeded restart rate limit."""
        import time
        now = time.monotonic()
        # Prune old entries
        self._restart_times = [
            t for t in self._restart_times
            if now - t < RESTART_WINDOW_SECONDS
        ]
        return len(self._restart_times) < MAX_RESTARTS_PER_WINDOW

    def record_restart(self) -> None:
        """Record a restart event."""
        import time
        self._restart_times.append(time.monotonic())
        self.audit("process_restart", {"count_in_window": len(self._restart_times)})

    # ── Test Runner ───────────────────────────────────────────────────

    def run_tests(self, timeout: int = 120) -> tuple[bool, str]:
        """Run the test suite. Returns (passed, output)."""
        try:
            result = subprocess.run(
                [str(self._root / ".venv" / "bin" / "python"), "-m", "pytest",
                 "tests/", "-x", "--tb=short", "-q"],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            passed = result.returncode == 0
            output = result.stdout + result.stderr
            self.audit("test_run", {"passed": passed, "returncode": result.returncode})
            return passed, output
        except subprocess.TimeoutExpired:
            self.audit("test_run", {"passed": False, "error": "timeout"})
            return False, "Tests timed out"
        except Exception as exc:
            self.audit("test_run", {"passed": False, "error": str(exc)})
            return False, str(exc)

    # ── Safe Patch Workflow ───────────────────────────────────────────

    def apply_patch_safely(
        self,
        file_path: str,
        original_content: str,
        patched_content: str,
        commit_message: str,
    ) -> tuple[bool, str]:
        """Apply a code patch with full safety net.

        1. Git stash current state
        2. Write patched file
        3. Run tests
        4. If tests pass → commit
        5. If tests fail → rollback
        """
        target = self._root / file_path
        if not target.exists():
            return False, f"File not found: {file_path}"

        # Verify file content matches expected
        current = target.read_text()
        if current != original_content:
            return False, "File content changed since analysis — aborting"

        self.audit("patch_start", {"file": file_path, "commit_msg": commit_message})

        # Step 1: Backup
        had_changes = self.git_stash("pre-repair-backup")

        try:
            # Step 2: Apply patch
            target.write_text(patched_content)
            self.audit("patch_applied", {"file": file_path, "diff_size": len(patched_content) - len(original_content)})

            # Step 3: Run tests
            passed, test_output = self.run_tests()

            if passed:
                # Step 4: Commit
                self.git_commit(commit_message)
                self.audit("patch_success", {"file": file_path})
                return True, "Patch applied and tests passed"
            else:
                # Step 5: Rollback
                target.write_text(original_content)
                self.audit("patch_rollback", {"file": file_path, "test_output": test_output[:500]})
                return False, f"Tests failed after patch — rolled back.\n{test_output[:500]}"

        except Exception as exc:
            # Emergency rollback
            try:
                target.write_text(original_content)
            except Exception:
                self.git_reset_hard()
            self.audit("patch_error", {"file": file_path, "error": str(exc)})
            return False, f"Patch failed: {exc}"

        finally:
            # Restore stashed changes if we had any
            if had_changes:
                self.git_stash_pop()
