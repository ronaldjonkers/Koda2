"""Process Monitor — spawns, watches, and restarts the Koda2 application.

The monitor is the outer shell that keeps Koda2 running. It:
- Starts koda2 as a subprocess
- Captures stdout/stderr
- Detects crashes (non-zero exit, health check failures)
- Triggers restart with optional self-repair
- Rate-limits restarts to prevent infinite loops
"""

from __future__ import annotations

import asyncio
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

from koda2.logging_config import get_logger
from koda2.supervisor.safety import SafetyGuard

logger = get_logger(__name__)

HEALTH_CHECK_INTERVAL = 30       # seconds between health checks
HEALTH_CHECK_URL = "http://localhost:8000/api/health"
STARTUP_GRACE_PERIOD = 15        # seconds to wait before first health check
STDERR_BUFFER_LINES = 200        # last N lines of stderr to keep for crash analysis
GIT_POLL_INTERVAL = 120          # seconds between git remote checks (2 minutes)


class ProcessMonitor:
    """Spawns and monitors the Koda2 process."""

    def __init__(
        self,
        safety: SafetyGuard,
        on_crash: Optional[Callable[[str, int], Any]] = None,
        project_root: Optional[Path] = None,
    ) -> None:
        self._safety = safety
        self._on_crash = on_crash  # callback(stderr, exit_code) -> None
        self._root = project_root or Path(__file__).parent.parent.parent
        self._process: Optional[subprocess.Popen] = None
        self._stderr_buffer: list[str] = []
        self._running = False
        self._start_time: float = 0
        self._last_git_check: float = 0

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def uptime(self) -> float:
        if not self._start_time:
            return 0
        return time.monotonic() - self._start_time

    @property
    def last_stderr(self) -> str:
        return "\n".join(self._stderr_buffer[-STDERR_BUFFER_LINES:])

    def start_process(self) -> bool:
        """Start the Koda2 application as a subprocess."""
        if self.is_running:
            logger.warning("process_already_running", pid=self._process.pid)
            return True

        if not self._safety.can_restart():
            logger.error("restart_rate_limit_exceeded")
            self._safety.audit("restart_blocked", {"reason": "rate_limit"})
            return False

        try:
            python = str(self._root / ".venv" / "bin" / "python")
            if not Path(python).exists():
                python = sys.executable

            self._process = subprocess.Popen(
                [python, "-m", "koda2.main"],
                cwd=str(self._root),
                stdout=None,  # pass through to terminal so user sees output
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line-buffered
            )
            self._start_time = time.monotonic()
            self._stderr_buffer.clear()
            self._safety.record_restart()

            logger.info("process_started", pid=self._process.pid)
            self._safety.audit("process_start", {"pid": self._process.pid})
            return True

        except Exception as exc:
            logger.error("process_start_failed", error=str(exc))
            self._safety.audit("process_start_failed", {"error": str(exc)})
            return False

    def stop_process(self, timeout: int = 10) -> None:
        """Gracefully stop the Koda2 process."""
        if not self._process:
            return

        pid = self._process.pid
        logger.info("stopping_process", pid=pid)

        try:
            self._process.send_signal(signal.SIGTERM)
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.warning("process_kill_timeout", pid=pid)
            self._process.kill()
            self._process.wait(timeout=5)
        except Exception as exc:
            logger.error("process_stop_failed", error=str(exc))

        self._safety.audit("process_stop", {"pid": pid})
        self._process = None

    async def _read_stderr(self) -> None:
        """Read stderr in background to capture crash output."""
        if not self._process or not self._process.stderr:
            return
        loop = asyncio.get_event_loop()
        while self.is_running:
            try:
                line = await loop.run_in_executor(
                    None, self._process.stderr.readline
                )
                if line:
                    self._stderr_buffer.append(line.rstrip())
                    # Keep buffer bounded
                    if len(self._stderr_buffer) > STDERR_BUFFER_LINES * 2:
                        self._stderr_buffer = self._stderr_buffer[-STDERR_BUFFER_LINES:]
                else:
                    break
            except Exception:
                break

    async def _health_check(self) -> bool:
        """Check if the Koda2 API is responding."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(HEALTH_CHECK_URL)
                return resp.status_code == 200
        except Exception:
            return False

    def _rebuild_npm_packages(self) -> None:
        """Run npm install for all package.json files in the project.

        Called after git pull to ensure Node.js dependencies (WhatsApp bridge
        etc.) are up to date with any changes pulled from remote.
        """
        project_root = self._safety._root
        for pkg_json in project_root.rglob("package.json"):
            # Skip node_modules directories
            if "node_modules" in pkg_json.parts:
                continue
            pkg_dir = pkg_json.parent
            logger.info("npm_install_after_pull", directory=str(pkg_dir.relative_to(project_root)))
            try:
                result = subprocess.run(
                    ["npm", "install", "--production"],
                    cwd=str(pkg_dir),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0:
                    logger.info("npm_install_success", directory=str(pkg_dir.relative_to(project_root)))
                else:
                    logger.warning("npm_install_failed", directory=str(pkg_dir.relative_to(project_root)),
                                   error=result.stderr[:200])
            except FileNotFoundError:
                logger.warning("npm_not_found_skipping")
                break  # npm not installed, skip all
            except Exception as exc:
                logger.warning("npm_install_error", error=str(exc))

    def _check_remote_updates(self) -> bool:
        """Check for new commits on the remote and auto-pull if found.

        Runs git fetch + compare + pull --ff-only. If new commits are
        pulled, a restart signal is written so the process picks up
        the new code on the next loop iteration.

        Returns True if a pull was performed (restart needed).
        """
        now = time.monotonic()
        if now - self._last_git_check < GIT_POLL_INTERVAL:
            return False
        self._last_git_check = now

        if not self._safety.git_fetch():
            return False

        has_updates, summary = self._safety.check_remote_ahead()
        if not has_updates:
            return False

        commit_count = len(summary.splitlines())
        logger.info("remote_updates_found", commits=commit_count, summary=summary[:200])

        success, output = self._safety.git_pull()
        if success:
            logger.info("auto_pull_complete", output=output[:200])
            # Rebuild npm packages after pull (WhatsApp bridge etc.)
            self._rebuild_npm_packages()
            self._safety.request_restart(f"auto-pull: {commit_count} new commit(s)")
            return True

        logger.warning("auto_pull_failed", output=output[:200])
        return False

    async def run(self) -> None:
        """Main supervisor loop — start, monitor, restart on crash."""
        self._running = True
        logger.info("supervisor_starting")
        self._safety.audit("supervisor_start")

        while self._running:
            # Start the process
            if not self.start_process():
                logger.error("supervisor_cannot_start_process")
                # Wait before retrying
                await asyncio.sleep(30)
                continue

            # Read stderr in background
            stderr_task = asyncio.create_task(self._read_stderr())

            # Wait for startup
            await asyncio.sleep(STARTUP_GRACE_PERIOD)

            # Monitor loop
            while self._running and self.is_running:
                # Check if a code update requested a restart
                restart_reason = self._safety.check_restart_requested()
                if restart_reason:
                    logger.info("restart_signal_received", reason=restart_reason)
                    self._safety.audit("graceful_restart", {"reason": restart_reason})
                    self.stop_process()
                    break  # Will restart in the outer while loop

                # Check for new commits on remote (non-blocking, runs in-process)
                self._check_remote_updates()

                # Periodic health check
                healthy = await self._health_check()
                if not healthy and self.uptime > STARTUP_GRACE_PERIOD:
                    consecutive_failures = 0
                    for _ in range(3):
                        await asyncio.sleep(5)
                        if await self._health_check():
                            break
                        consecutive_failures += 1

                    if consecutive_failures >= 3:
                        logger.error("health_check_failed_3x")
                        self._safety.audit("health_check_failed", {"consecutive": 3})
                        self.stop_process()
                        break

                await asyncio.sleep(HEALTH_CHECK_INTERVAL)

            # Process has exited
            stderr_task.cancel()
            exit_code = self._process.returncode if self._process else -1
            stderr_output = self.last_stderr

            if exit_code != 0 and self._running:
                logger.error("process_crashed", exit_code=exit_code)
                self._safety.audit("process_crash", {
                    "exit_code": exit_code,
                    "stderr_tail": stderr_output[-500:],
                })

                # Trigger crash handler (self-repair)
                if self._on_crash:
                    try:
                        result = self._on_crash(stderr_output, exit_code)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as exc:
                        logger.error("crash_handler_failed", error=str(exc))

            elif not self._running:
                logger.info("supervisor_shutdown_requested")
                break

            # Brief pause before restart
            await asyncio.sleep(2)

        self._safety.audit("supervisor_stop")
        logger.info("supervisor_stopped")

    def shutdown(self) -> None:
        """Signal the supervisor to stop."""
        self._running = False
        self.stop_process()
