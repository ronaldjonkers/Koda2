"""Safety guardrails for the self-development supervisor.

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

    # ── Package Management ─────────────────────────────────────────────

    def pip_install(self, *packages: str) -> tuple[bool, str]:
        """Install Python packages using pip in the project venv.

        Returns:
            (success, output)
        """
        if not packages:
            return False, "No packages specified"

        # Use the project venv python
        python = str(self._root / ".venv" / "bin" / "python")
        if not Path(python).exists():
            import sys
            python = sys.executable

        try:
            result = subprocess.run(
                [python, "-m", "pip", "install", *packages],
                cwd=str(self._root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                err = result.stderr.strip()
                logger.warning("pip_install_failed", packages=packages, error=err[:300])
                self.audit("pip_install_failed", {"packages": list(packages), "error": err[:300]})
                return False, err
            logger.info("pip_install_success", packages=packages)
            self.audit("pip_install_success", {"packages": list(packages), "output": output[:300]})
            return True, output
        except Exception as exc:
            logger.error("pip_install_exception", error=str(exc))
            return False, str(exc)

    # ── Remote Update Detection ────────────────────────────────────────

    def git_fetch(self) -> bool:
        """Fetch latest refs from remote without merging."""
        try:
            self._git("fetch", "--quiet", check=False)
            return True
        except Exception as exc:
            logger.warning("git_fetch_failed", error=str(exc))
            return False

    def check_remote_ahead(self) -> tuple[bool, str]:
        """Check if the remote has commits we don't have locally.

        Returns:
            (has_updates, summary) — True if remote is ahead, with a summary of new commits.
        """
        try:
            # Get current branch
            branch_result = self._git("rev-parse", "--abbrev-ref", "HEAD", check=False)
            branch = branch_result.stdout.strip() or "main"

            # Compare local HEAD with remote tracking branch
            local = self._git("rev-parse", "HEAD", check=False).stdout.strip()
            remote = self._git("rev-parse", f"origin/{branch}", check=False).stdout.strip()

            if not local or not remote or local == remote:
                return False, ""

            # Check if remote is actually ahead (not behind)
            merge_base = self._git("merge-base", local, remote, check=False).stdout.strip()
            if merge_base != local:
                # We have local commits not on remote — don't pull (would cause conflicts)
                return False, ""

            # Get commit summaries for the new commits
            log_result = self._git(
                "log", "--oneline", f"{local}..{remote}", "--max-count=10", check=False,
            )
            summary = log_result.stdout.strip()
            if summary:
                count = len(summary.splitlines())
                self.audit("remote_updates_detected", {
                    "branch": branch,
                    "new_commits": count,
                    "summary": summary[:500],
                })
                return True, summary

            return False, ""
        except Exception as exc:
            logger.warning("check_remote_ahead_failed", error=str(exc))
            return False, ""

    def git_pull(self) -> tuple[bool, str]:
        """Pull latest changes from remote.

        Returns:
            (success, output)
        """
        try:
            result = self._git("pull", "--ff-only", check=False)
            output = result.stdout.strip()
            if result.returncode != 0:
                err = result.stderr.strip()
                logger.warning("git_pull_failed", error=err)
                self.audit("git_pull_failed", {"error": err[:300]})
                return False, err
            self.audit("git_pull_success", {"output": output[:300]})
            return True, output
        except Exception as exc:
            logger.error("git_pull_exception", error=str(exc))
            return False, str(exc)

    # ── Restart Signal ─────────────────────────────────────────────────

    def request_restart(self, reason: str = "code updated") -> None:
        """Signal that the Koda2 process should be restarted.

        The ProcessMonitor checks for this signal and gracefully restarts.
        """
        restart_file = AUDIT_LOG_DIR / "restart_requested"
        restart_file.write_text(reason)
        self.audit("restart_requested", {"reason": reason})

    def check_restart_requested(self) -> str:
        """Check if a restart has been requested. Returns reason or empty string."""
        restart_file = AUDIT_LOG_DIR / "restart_requested"
        if restart_file.exists():
            reason = restart_file.read_text().strip()
            restart_file.unlink(missing_ok=True)
            return reason
        return ""

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
                # Step 4: Commit + push
                self.git_commit(commit_message)
                self.git_push()
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
