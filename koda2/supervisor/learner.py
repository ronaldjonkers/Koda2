"""Continuous Learning Loop — proactive self-improvement for Koda2.

Runs as a background task alongside the supervisor. Periodically:
1. Reads conversation history for recurring complaints/wishes
2. Analyzes audit logs for error patterns
3. Checks application logs for warnings/errors
4. Proposes and implements improvements autonomously
5. Updates documentation, bumps version, notifies user
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.supervisor.safety import SafetyGuard, AUDIT_LOG_FILE

logger = get_logger(__name__)

# ── Configuration ─────────────────────────────────────────────────────
LEARNING_INTERVAL_SECONDS = 14400     # analyze every 4 hours
CONVERSATION_LOOKBACK = 200           # last N conversation turns to analyze
MIN_COMPLAINT_OCCURRENCES = 2         # minimum times a pattern must appear
MAX_AUTO_IMPROVEMENTS_PER_CYCLE = 1   # conservative: 1 at a time
MAX_PENDING_QUEUE_ITEMS = 3           # don't queue more if this many are pending
CHANGELOG_PATH = "CHANGELOG.md"
README_PATH = "README.md"
PYPROJECT_PATH = "pyproject.toml"


class ContinuousLearner:
    """Proactive learning loop that reads logs and conversations to improve Koda2.

    Architecture:
        ┌─────────────────────────────────────────────┐
        │            ContinuousLearner                │
        │                                             │
        │  1. Gather signals:                         │
        │     - Conversation history (complaints,     │
        │       wishes, confusion patterns)           │
        │     - Audit log (crashes, repair failures)  │
        │     - App logs (warnings, errors)           │
        │                                             │
        │  2. Analyze via LLM:                        │
        │     - Classify signals                      │
        │     - Prioritize by impact                  │
        │     - Generate improvement plan             │
        │                                             │
        │  3. Execute improvements:                   │
        │     - Code changes via EvolutionEngine      │
        │     - Auto-update docs (README, CHANGELOG)  │
        │     - Auto-bump version                     │
        │     - Auto-notify user via WhatsApp         │
        │                                             │
        │  4. Learn from results:                     │
        │     - Track what worked/failed              │
        │     - Avoid repeating failed improvements   │
        └─────────────────────────────────────────────┘
    """

    def __init__(
        self,
        safety: SafetyGuard,
        project_root: Optional[Path] = None,
        notify_user_id: Optional[str] = None,
    ) -> None:
        self._safety = safety
        self._root = project_root or Path(__file__).parent.parent.parent
        self._settings = get_settings()
        self._notify_user_id = notify_user_id
        self._running = False
        self._cycle_count = 0
        self._improvements_applied: list[dict[str, Any]] = []
        self._failed_ideas: set[str] = set()  # fingerprints of failed request texts
        self._state_file = self._root / "data" / "supervisor" / "learner_state.json"
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted learner state."""
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text())
                self._cycle_count = data.get("cycle_count", 0)
                self._failed_ideas = set(data.get("failed_ideas", []))
                self._improvements_applied = data.get("improvements_applied", [])[-50:]
            except Exception:
                pass

    def _save_state(self) -> None:
        """Persist learner state."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps({
            "cycle_count": self._cycle_count,
            "failed_ideas": list(self._failed_ideas)[-100:],
            "improvements_applied": self._improvements_applied[-50:],
            "updated_at": dt.datetime.now().isoformat(),
        }, indent=2))

    @staticmethod
    def _request_fingerprint(request: str) -> str:
        """Create a short fingerprint from a request for dedup.

        Normalises the text (lowercase, sorted key words) so semantically
        identical requests that differ only in wording still match.
        """
        import hashlib
        # Extract meaningful words, ignore stop words / filler
        words = sorted(set(
            w for w in re.sub(r"[^a-z0-9 ]", "", request.lower()).split()
            if len(w) > 3
        ))
        key = " ".join(words[:30])  # cap to avoid huge hashes
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    # ── Signal Gathering ──────────────────────────────────────────────

    async def _gather_conversation_signals(self) -> list[dict[str, Any]]:
        """Read recent conversations and extract complaints, wishes, confusion."""
        signals = []
        try:
            from koda2.database import get_session
            from koda2.modules.memory.models import Conversation
            from sqlalchemy import select

            async with get_session() as session:
                result = await session.execute(
                    select(Conversation)
                    .order_by(Conversation.created_at.desc())
                    .limit(CONVERSATION_LOOKBACK)
                )
                conversations = result.scalars().all()

            # Extract user messages (truncated to keep payload small)
            user_messages = [
                {"content": c.content[:150], "channel": c.channel, "created_at": str(c.created_at)[:19]}
                for c in conversations
                if c.role == "user" and len(c.content) > 10
            ]

            if user_messages:
                signals.append({
                    "type": "conversations",
                    "count": len(user_messages),
                    "messages": user_messages[-20:],  # last 20, truncated
                })

        except Exception as exc:
            logger.warning("gather_conversations_failed", error=str(exc))

        return signals

    def _gather_audit_signals(self) -> list[dict[str, Any]]:
        """Read audit log for error patterns, crashes, failed repairs."""
        signals = []
        if not AUDIT_LOG_FILE.exists():
            return signals

        try:
            lines = AUDIT_LOG_FILE.read_text().strip().splitlines()
            recent = lines[-200:]  # last 200 entries

            entries = []
            for line in recent:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

            # Count action types
            action_counts: dict[str, int] = {}
            errors = []
            crashes = []
            for entry in entries:
                action = entry.get("action", "")
                action_counts[action] = action_counts.get(action, 0) + 1
                if "error" in action or "fail" in action:
                    errors.append(entry)
                if "crash" in action:
                    crashes.append(entry)

            if errors or crashes:
                signals.append({
                    "type": "audit_errors",
                    "error_count": len(errors),
                    "crash_count": len(crashes),
                    "action_summary": action_counts,
                    "recent_errors": errors[-10:],
                    "recent_crashes": crashes[-5:],
                })

        except Exception as exc:
            logger.warning("gather_audit_failed", error=str(exc))

        return signals

    def _gather_log_signals(self) -> list[dict[str, Any]]:
        """Read application log files for warnings and errors."""
        signals = []
        log_dir = self._root / "data" / "logs"
        if not log_dir.exists():
            return signals

        try:
            warnings = []
            errors = []
            for log_file in sorted(log_dir.glob("*.log"))[-3:]:  # last 3 log files
                for line in log_file.read_text().splitlines()[-500:]:
                    lower = line.lower()
                    if "error" in lower or "exception" in lower:
                        errors.append(line.strip()[:200])
                    elif "warning" in lower:
                        warnings.append(line.strip()[:200])

            if errors or warnings:
                # Deduplicate
                unique_errors = list(set(errors))[-20:]
                unique_warnings = list(set(warnings))[-20:]
                signals.append({
                    "type": "app_logs",
                    "unique_errors": len(unique_errors),
                    "unique_warnings": len(unique_warnings),
                    "errors": unique_errors,
                    "warnings": unique_warnings[:10],
                })

        except Exception as exc:
            logger.warning("gather_logs_failed", error=str(exc))

        return signals

    def _gather_runtime_error_signals(self) -> list[dict[str, Any]]:
        """Read runtime tool execution errors captured by the error collector."""
        signals = []
        try:
            from koda2.supervisor.error_collector import get_error_summary
            summary = get_error_summary()
            if summary["total"] > 0:
                signals.append({
                    "type": "runtime_errors",
                    "total": summary["total"],
                    "by_tool": summary["by_tool"],
                    "top_errors": summary["top_errors"],
                })
        except Exception as exc:
            logger.warning("gather_runtime_errors_failed", error=str(exc))
        return signals

    # ── LLM Analysis ──────────────────────────────────────────────────

    async def _analyze_signals(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Send gathered signals to LLM for analysis and improvement proposals."""
        from koda2.supervisor.evolution import EvolutionEngine

        engine = EvolutionEngine(self._safety, self._root)

        system_prompt = """You are the autonomous improvement brain of Koda2, an AI executive assistant
designed to help entrepreneurs and company founders run their business solo.

You analyze signals from multiple sources to propose concrete code improvements:
- **Conversations**: Look for user frustration, confusion, repeated requests that
  failed, feature wishes ("kan je ook...", "ik wil dat...", "waarom werkt X niet"),
  and behavioral complaints ("je antwoord was fout", "dat klopt niet").
- **Runtime errors**: Tool execution failures that users experienced.
- **Audit logs**: Crashes, failed repairs, system errors.
- **App logs**: Warnings, exceptions, recurring error patterns.

RULES:
1. Focus on HIGH-IMPACT improvements that users will notice immediately.
2. Prioritize: bug fixes > user complaints > runtime errors > feature requests > code quality.
3. Each proposal must be specific and actionable (not vague).
4. Max 3 proposals per analysis cycle.
5. Skip proposals that are too risky or too vague.
6. Consider what has already been tried and failed (listed below).
7. For conversation signals: extract the UNDERLYING need, not just the surface complaint.
   Example: "email werkt niet" → check email service error handling, not UI.
8. For runtime errors: focus on the most FREQUENT errors first.

RESPONSE FORMAT (JSON):
{
    "analysis": "Brief summary of what you found",
    "proposals": [
        {
            "id": "short_snake_case_id",
            "type": "bugfix|feature|improvement|cleanup",
            "priority": 1-5 (1=highest),
            "description": "What to change and why",
            "implementation_request": "Detailed instruction for the evolution engine",
            "estimated_impact": "How this helps users",
            "risk": "low|medium|high"
        }
    ]
}

If there's nothing meaningful to improve, return {"analysis": "...", "proposals": []}."""

        # Build context
        failed_list = "\n".join(f"- {f}" for f in list(self._failed_ideas)[-20:]) or "None"
        recent_improvements = "\n".join(
            f"- {i.get('description', '')[:100]}" for i in self._improvements_applied[-10:]
        ) or "None"

        signals_text = json.dumps(signals, default=str, ensure_ascii=False)
        # Truncate to stay well within LLM context limits
        if len(signals_text) > 6000:
            signals_text = signals_text[:6000] + "... (truncated)"

        user_prompt = f"""## Signals from Koda2 system

{signals_text}

## Previously failed improvement attempts (DO NOT retry these):
{failed_list}

## Recent successful improvements:
{recent_improvements}

Analyze these signals and propose concrete improvements. Return JSON only."""

        try:
            response = await engine._call_llm(system_prompt, user_prompt, task_type="signal_analysis")
            return engine._parse_json_response(response).get("proposals", [])
        except Exception as exc:
            logger.error("signal_analysis_failed", error=str(exc))
            return []

    # ── Improvement Execution ─────────────────────────────────────────

    async def _execute_improvement(self, proposal: dict[str, Any]) -> tuple[bool, str]:
        """Execute a single improvement proposal through the evolution engine."""
        from koda2.supervisor.evolution import EvolutionEngine

        proposal_id = proposal.get("id", "unknown")
        description = proposal.get("description", "")
        request = proposal.get("implementation_request", description)

        fingerprint = self._request_fingerprint(request)
        if fingerprint in self._failed_ideas:
            return False, f"Skipped — previously failed: {proposal_id}"

        if proposal.get("risk") == "high":
            self._safety.audit("learner_skip_high_risk", {"proposal": proposal_id})
            return False, f"Skipped high-risk proposal: {description}"

        self._safety.audit("learner_improvement_start", {
            "proposal_id": proposal_id,
            "type": proposal.get("type"),
            "description": description[:200],
        })

        engine = EvolutionEngine(self._safety, self._root)
        success, message = await engine.implement_improvement(request)

        if success:
            self._improvements_applied.append({
                "proposal_id": proposal_id,
                "description": description,
                "type": proposal.get("type"),
                "timestamp": dt.datetime.now().isoformat(),
            })
            self._safety.audit("learner_improvement_success", {
                "proposal_id": proposal_id,
                "message": message[:200],
            })
        else:
            self._failed_ideas.add(fingerprint)
            self._safety.audit("learner_improvement_failed", {
                "proposal_id": proposal_id,
                "fingerprint": fingerprint,
                "message": message[:200],
            })

        self._save_state()
        return success, message

    # ── Post-Improvement: Docs, Version, Notify ───────────────────────

    async def _update_documentation(self, improvements: list[dict[str, Any]]) -> bool:
        """Ask LLM to update CHANGELOG with the improvements made."""
        if not improvements:
            return False

        from koda2.supervisor.evolution import EvolutionEngine
        engine = EvolutionEngine(self._safety, self._root)

        changelog_path = self._root / CHANGELOG_PATH
        current_changelog = ""
        if changelog_path.exists():
            current_changelog = changelog_path.read_text()

        # Read current version
        version = self._read_current_version()

        descriptions = "\n".join(
            f"- [{i.get('type', 'improvement')}] {i.get('description', '')}"
            for i in improvements
        )

        system_prompt = """You update the CHANGELOG.md for Koda2.
Add a new entry under the current version section for the improvements made.
Keep the existing format. Be concise.

RESPONSE FORMAT (JSON):
{
    "changelog_entry": "The markdown text to INSERT at the top of the changelog entries (after the version header)"
}"""

        user_prompt = f"""Current version: {version}
Improvements made:
{descriptions}

Current CHANGELOG.md (first 2000 chars):
{current_changelog[:2000]}

Generate the changelog entry. Return JSON only."""

        try:
            response = await engine._call_llm(system_prompt, user_prompt)
            result = engine._parse_json_response(response)
            entry = result.get("changelog_entry", "")

            if entry and current_changelog:
                # Insert after the first version header
                pattern = r'(## \[\d+\.\d+\.\d+\].*?\n)'
                match = re.search(pattern, current_changelog)
                if match:
                    insert_pos = match.end()
                    # Check if there's already a ### section, insert before it or after header
                    updated = current_changelog[:insert_pos] + "\n" + entry.strip() + "\n" + current_changelog[insert_pos:]
                    changelog_path.write_text(updated)
                    self._safety.audit("docs_changelog_updated", {"entry_length": len(entry)})
                    return True

        except Exception as exc:
            logger.warning("changelog_update_failed", error=str(exc))

        return False

    def _read_current_version(self) -> str:
        """Read current version from pyproject.toml."""
        pyproject = self._root / PYPROJECT_PATH
        if not pyproject.exists():
            return "0.0.0"
        try:
            content = pyproject.read_text()
            match = re.search(r'version\s*=\s*"(\d+\.\d+\.\d+)"', content)
            return match.group(1) if match else "0.0.0"
        except Exception:
            return "0.0.0"

    def _bump_version(self, bump_type: str = "patch") -> str:
        """Bump version in pyproject.toml. Returns new version string."""
        current = self._read_current_version()
        parts = current.split(".")
        if len(parts) != 3:
            return current

        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

        if bump_type == "major":
            major += 1
            minor = 0
            patch = 0
        elif bump_type == "minor":
            minor += 1
            patch = 0
        else:  # patch
            patch += 1

        new_version = f"{major}.{minor}.{patch}"

        # Update pyproject.toml
        pyproject = self._root / PYPROJECT_PATH
        if pyproject.exists():
            content = pyproject.read_text()
            updated = re.sub(
                r'version\s*=\s*"\d+\.\d+\.\d+"',
                f'version = "{new_version}"',
                content,
            )
            pyproject.write_text(updated)

        # Keep koda2/__init__.py in sync
        init_file = self._root / "koda2" / "__init__.py"
        if init_file.exists():
            init_content = init_file.read_text()
            updated_init = re.sub(
                r'__version__\s*=\s*"\d+\.\d+\.\d+"',
                f'__version__ = "{new_version}"',
                init_content,
            )
            init_file.write_text(updated_init)

        self._safety.audit("version_bump", {
            "from": current,
            "to": new_version,
            "type": bump_type,
        })

        return new_version

    def _determine_bump_type(self, improvements: list[dict[str, Any]]) -> str:
        """Determine version bump type based on improvement types."""
        types = {i.get("type", "") for i in improvements}
        if "feature" in types:
            return "minor"
        return "patch"

    async def _notify_user(self, version: str, improvements: list[dict[str, Any]]) -> None:
        """Send WhatsApp notification about the new version."""
        if not self._notify_user_id:
            return

        try:
            descriptions = "\n".join(
                f"• {i.get('description', 'Improvement')[:100]}"
                for i in improvements
            )

            message = (
                f"🧬 *Koda2 v{version} — Auto-Update*\n\n"
                f"I've analyzed my logs and conversations and made some improvements:\n\n"
                f"{descriptions}\n\n"
                f"Changes are committed and pushed. Restart to activate.\n"
                f"Use /feedback to tell me what you think!"
            )

            from koda2.modules.messaging.whatsapp_bot import WhatsAppBot
            bot = WhatsAppBot(get_settings())
            if bot.is_configured:
                await bot.send_message(self._notify_user_id, message)
                self._safety.audit("user_notified", {
                    "version": version,
                    "user_id": self._notify_user_id,
                    "channel": "whatsapp",
                })

        except Exception as exc:
            logger.warning("user_notification_failed", error=str(exc))

    # ── Code Hygiene ──────────────────────────────────────────────────

    async def _run_hygiene_check(self) -> Optional[dict[str, Any]]:
        """Check for code hygiene issues: unused imports, dead code, organization."""
        from koda2.supervisor.evolution import EvolutionEngine
        engine = EvolutionEngine(self._safety, self._root)

        # Gather some stats
        py_files = list(self._root.rglob("*.py"))
        py_files = [
            f for f in py_files
            if not any(skip in f.parts for skip in (".venv", "__pycache__", "node_modules", ".git"))
        ]

        total_lines = 0
        large_files = []
        for f in py_files:
            try:
                lines = len(f.read_text().splitlines())
                total_lines += lines
                if lines > 500:
                    rel = f.relative_to(self._root)
                    large_files.append(f"{rel} ({lines} lines)")
            except Exception:
                continue

        if not large_files:
            return None

        system_prompt = """You are a code hygiene analyzer for Koda2.
Check for organizational issues and suggest ONE specific cleanup action.
Only suggest if there's a clear, low-risk improvement.

RESPONSE FORMAT (JSON):
{
    "has_issue": true/false,
    "issue": "Description of the issue",
    "suggestion": "Specific cleanup action",
    "risk": "low|medium|high"
}"""

        user_prompt = f"""Project stats:
- {len(py_files)} Python files
- {total_lines} total lines
- Large files (>500 lines): {', '.join(large_files[:10])}

Any organizational issues? Return JSON only."""

        try:
            response = await engine._call_llm(system_prompt, user_prompt)
            result = engine._parse_json_response(response)
            if result.get("has_issue") and result.get("risk") != "high":
                return result
        except Exception as exc:
            logger.warning("hygiene_check_failed", error=str(exc))

        return None

    # ── Main Loop ─────────────────────────────────────────────────────

    async def run_cycle(self) -> dict[str, Any]:
        """Run one learning cycle: gather → analyze → improve → document → notify.

        Returns a summary of what happened.
        """
        self._cycle_count += 1
        cycle_start = dt.datetime.now()
        self._safety.audit("learner_cycle_start", {"cycle": self._cycle_count})

        summary: dict[str, Any] = {
            "cycle": self._cycle_count,
            "started_at": cycle_start.isoformat(),
            "signals_gathered": 0,
            "proposals": 0,
            "improvements_applied": 0,
            "improvements_failed": 0,
            "version_bumped": False,
            "user_notified": False,
        }

        try:
            # Step 1: Gather signals
            signals = []
            signals.extend(await self._gather_conversation_signals())
            signals.extend(self._gather_audit_signals())
            signals.extend(self._gather_log_signals())
            signals.extend(self._gather_runtime_error_signals())
            summary["signals_gathered"] = len(signals)

            if not signals:
                self._safety.audit("learner_cycle_no_signals", {"cycle": self._cycle_count})
                self._save_state()
                return summary

            # Step 2: Analyze signals → get proposals
            proposals = await self._analyze_signals(signals)
            summary["proposals"] = len(proposals)

            if not proposals:
                self._safety.audit("learner_cycle_no_proposals", {"cycle": self._cycle_count})
                self._save_state()
                return summary

            # Sort by priority
            proposals.sort(key=lambda p: p.get("priority", 5))

            # Step 3: Queue proposals via the ImprovementQueue
            from koda2.supervisor.improvement_queue import get_improvement_queue
            queue = get_improvement_queue()

            # Don't flood the queue if items are already pending
            if queue.pending_count() >= MAX_PENDING_QUEUE_ITEMS:
                logger.info("learner_queue_full", pending=queue.pending_count())
                self._safety.audit("learner_queue_full", {"pending": queue.pending_count()})
                self._save_state()
                return summary

            queued_count = 0
            for proposal in proposals[:MAX_AUTO_IMPROVEMENTS_PER_CYCLE]:
                proposal_id = proposal.get("id", "unknown")
                description = proposal.get("description", "")
                request = proposal.get("implementation_request", description)

                # Dedup by request text fingerprint (not LLM-generated ID)
                fingerprint = self._request_fingerprint(request)
                if fingerprint in self._failed_ideas:
                    logger.debug("learner_skip_already_failed", fingerprint=fingerprint[:40])
                    continue
                if proposal.get("risk") == "high":
                    self._safety.audit("learner_skip_high_risk", {"proposal": proposal_id})
                    continue

                queue.add(
                    request=request,
                    source="learner",
                    priority=proposal.get("priority", 5),
                    metadata={
                        "proposal_id": proposal_id,
                        "type": proposal.get("type"),
                        "description": description[:200],
                        "cycle": self._cycle_count,
                        "fingerprint": fingerprint,
                    },
                )
                queued_count += 1

            summary["improvements_queued"] = queued_count

            # Start queue worker if items were added and it's not running
            if queued_count > 0 and not queue.is_running:
                queue.start_worker()

            # Step 4: Periodic hygiene check (every 6 cycles)
            if self._cycle_count % 6 == 0:
                hygiene = await self._run_hygiene_check()
                if hygiene and hygiene.get("suggestion"):
                    queue.add(
                        request=hygiene["suggestion"],
                        source="learner",
                        priority=8,
                        metadata={"type": "hygiene", "issue": hygiene.get("issue", "")},
                    )
                    summary["hygiene_issue"] = hygiene.get("issue", "")

        except Exception as exc:
            logger.error("learner_cycle_error", error=str(exc))
            self._safety.audit("learner_cycle_error", {"error": str(exc)})
            summary["error"] = str(exc)

        summary["finished_at"] = dt.datetime.now().isoformat()
        self._safety.audit("learner_cycle_complete", summary)
        self._save_state()
        return summary

    async def run_forever(self) -> None:
        """Run the learning loop continuously in the background."""
        self._running = True
        logger.info("continuous_learner_starting", interval=LEARNING_INTERVAL_SECONDS)
        self._safety.audit("learner_start", {"interval_seconds": LEARNING_INTERVAL_SECONDS})

        # Wait a bit before first cycle (let the system stabilize)
        await asyncio.sleep(60)

        while self._running:
            try:
                summary = await self.run_cycle()
                logger.info("learner_cycle_done",
                            cycle=summary["cycle"],
                            applied=summary["improvements_applied"])
            except Exception as exc:
                logger.error("learner_loop_error", error=str(exc))

            # Wait for next cycle
            await asyncio.sleep(LEARNING_INTERVAL_SECONDS)

        self._safety.audit("learner_stop")

    def stop(self) -> None:
        """Signal the learner to stop."""
        self._running = False
