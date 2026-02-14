"""Evolution Engine — self-improvement loop for Koda2.

Allows the assistant to improve itself based on:
- User requests ("Koda, verbeter jezelf: voeg X toe")
- Recurring error patterns (auto-detected from logs)
- Feature requests via /improve command
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.supervisor.safety import SafetyGuard
from koda2.supervisor.model_router import call_llm as _routed_llm_call

logger = get_logger(__name__)

MAX_SELF_CORRECTION_ATTEMPTS = 3


class EvolutionEngine:
    """Generates code improvements and new features via LLM."""

    def __init__(self, safety: SafetyGuard, project_root: Optional[Path] = None) -> None:
        self._safety = safety
        self._root = project_root or Path(__file__).parent.parent.parent
        self._settings = get_settings()

    async def _call_llm(self, system: str, user: str, task_type: str = "code_generation") -> str:
        """Call the LLM via the smart model router.

        Args:
            system: System prompt
            user: User prompt
            task_type: Task complexity hint (see model_router.TASK_COMPLEXITY_MAP)
        """
        return await _routed_llm_call(system, user, task_type=task_type)

    def _get_project_structure(self) -> str:
        """Get a summary of the project structure for context."""
        lines = []
        for p in sorted(self._root.rglob("*.py")):
            try:
                rel = p.relative_to(self._root)
            except ValueError:
                continue
            # Skip venv, __pycache__, etc.
            parts = rel.parts
            if any(skip in parts for skip in (".venv", "__pycache__", "node_modules", ".git")):
                continue
            size = p.stat().st_size
            lines.append(f"  {rel} ({size} bytes)")
        return "\n".join(lines[:100])  # cap at 100 files

    def _read_file_safe(self, relative_path: str) -> str:
        """Read a project file safely."""
        path = self._root / relative_path
        if not path.exists():
            return ""
        try:
            path.relative_to(self._root)
            return path.read_text()
        except (ValueError, Exception):
            return ""

    async def plan_improvement(self, request: str) -> dict[str, Any]:
        """Plan an improvement based on a user request.

        Returns a plan with files to create/modify and the changes needed.
        """
        structure = self._get_project_structure()

        system_prompt = """You are a senior Python developer working on Koda2, an AI executive assistant.
You plan code improvements and new features.

RULES:
1. Propose MINIMAL, focused changes. Don't refactor unrelated code.
2. Follow existing code patterns and style.
3. Always include proper imports, error handling, and logging.
4. If creating new files, include full content.
5. If modifying existing files, specify exact old_text → new_text replacements.
6. Include test suggestions.

RESPONSE FORMAT (JSON):
{
    "summary": "Brief description of what will change",
    "changes": [
        {
            "action": "create|modify",
            "file": "relative/path/to/file.py",
            "description": "What this change does",
            "content": "Full file content (for create)",
            "old_text": "Text to find (for modify)",
            "new_text": "Replacement text (for modify)"
        }
    ],
    "test_suggestions": "How to verify this works",
    "risk": "low|medium|high"
}"""

        user_prompt = f"""Improvement request: {request}

## Project Structure
```
{structure}
```

Plan the minimal changes needed. Return JSON only."""

        try:
            response = await self._call_llm(system_prompt, user_prompt)
            return self._parse_json_response(response)
        except Exception as exc:
            logger.error("plan_improvement_failed", error=str(exc))
            return {"summary": f"Planning failed: {exc}", "changes": [], "risk": "high"}

    async def implement_improvement(self, request: str) -> tuple[bool, str]:
        """Full improvement cycle: plan → implement → test → commit.

        Returns:
            (success, message)
        """
        self._safety.audit("evolution_start", {"request": request})

        # Phase 1: Plan (LLM call — safe to run concurrently)
        plan = await self.plan_improvement(request)

        if not plan.get("changes"):
            return False, f"No changes planned. {plan.get('summary', '')}"

        if plan.get("risk") == "high":
            return False, f"High-risk change — needs manual review. Plan: {plan['summary']}"

        logger.info("evolution_plan_ready", summary=plan["summary"], changes=len(plan["changes"]))
        self._safety.audit("evolution_plan", {
            "summary": plan["summary"],
            "change_count": len(plan["changes"]),
            "risk": plan.get("risk", "unknown"),
        })

        # Phase 2: Apply (git/files/tests — must be serialized)
        return await self.apply_plan(plan)

    async def apply_plan(
        self, plan: dict[str, Any], *, allow_self_correction: bool = True,
    ) -> tuple[bool, str]:
        """Apply a pre-computed plan: stash → write files → test → commit or rollback.

        This method touches git and the filesystem and must NOT run concurrently.
        The ImprovementQueue holds a git lock to enforce this.

        If tests fail and ``allow_self_correction`` is True, the plan is revised
        using the test output as feedback (up to MAX_SELF_CORRECTION_ATTEMPTS).
        """
        current_plan = plan

        for attempt in range(1, MAX_SELF_CORRECTION_ATTEMPTS + 1):
            self._safety.git_stash("pre-evolution-backup")
            messages: list[str] = []

            try:
                # Apply changes
                for change in current_plan["changes"]:
                    action = change.get("action", "modify")
                    file_path = change.get("file", "")

                    if not file_path:
                        continue

                    full_path = self._root / file_path

                    if action == "create":
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        full_path.write_text(change.get("content", ""))
                        messages.append(f"Created {file_path}")
                        self._safety.audit("evolution_file_created", {"file": file_path})

                    elif action == "modify":
                        old_text = change.get("old_text", "")
                        new_text = change.get("new_text", "")
                        if not old_text or not new_text:
                            continue

                        current = self._read_file_safe(file_path)
                        if old_text not in current:
                            messages.append(f"Skipped {file_path}: old_text not found")
                            continue

                        patched = current.replace(old_text, new_text, 1)
                        full_path.write_text(patched)
                        messages.append(f"Modified {file_path}")
                        self._safety.audit("evolution_file_modified", {"file": file_path})

                # Run tests
                passed, test_output = self._safety.run_tests()

                if passed:
                    # Generate detailed commit message (cheap model)
                    commit_msg = await self._generate_commit_message(current_plan, messages)
                    # Update CHANGELOG.md with this improvement
                    self._update_changelog(current_plan, messages)
                    self._safety.git_commit(commit_msg)
                    self._safety.git_push()
                    self._safety.request_restart(f"evolution: {current_plan['summary'][:60]}")
                    self._safety.audit("evolution_success", {
                        "summary": current_plan["summary"],
                        "attempt": attempt,
                    })
                    return True, f"Improvement applied (attempt {attempt}): {current_plan['summary']}\nChanges: {'; '.join(messages)}"

                # Tests failed — rollback this attempt
                self._safety.git_reset_hard()
                self._safety.audit("evolution_rollback", {
                    "test_output": test_output[:500],
                    "attempt": attempt,
                })

                # Self-correction: ask LLM to revise the plan
                if allow_self_correction and attempt < MAX_SELF_CORRECTION_ATTEMPTS:
                    logger.info("self_correction_attempt", attempt=attempt, max=MAX_SELF_CORRECTION_ATTEMPTS)
                    revised = await self.revise_plan(current_plan, test_output)
                    if revised and revised.get("changes"):
                        current_plan = revised
                        continue

                return False, f"Tests failed after {attempt} attempt(s) — rolled back.\n{test_output[:300]}"

            except Exception as exc:
                self._safety.git_reset_hard()
                self._safety.audit("evolution_error", {"error": str(exc), "attempt": attempt})
                return False, f"Evolution failed (attempt {attempt}): {exc}"

        return False, "Self-correction attempts exhausted"

    async def revise_plan(
        self, original_plan: dict[str, Any], test_output: str,
    ) -> dict[str, Any]:
        """Ask the LLM to revise a failed plan based on test output.

        Returns a new plan dict with corrected changes, or empty dict on failure.
        """
        self._safety.audit("revise_plan_start", {
            "summary": original_plan.get("summary", "")[:100],
        })

        structure = self._get_project_structure()

        # Read current file contents for files touched by the plan
        file_contexts = ""
        for change in original_plan.get("changes", []):
            fpath = change.get("file", "")
            if fpath:
                content = self._read_file_safe(fpath)
                if content:
                    file_contexts += f"\n### {fpath}\n```python\n{content[:3000]}\n```\n"

        system_prompt = """You are a senior Python developer fixing a failed code improvement.
The previous attempt broke the test suite. Analyze the test output and fix the plan.

RULES:
1. Only fix what the tests are complaining about.
2. Keep the original intent of the improvement.
3. Use the SAME response format as the original plan.
4. If the improvement is fundamentally wrong, return {"changes": [], "summary": "Cannot fix", "risk": "high"}.

RESPONSE FORMAT (JSON):
{
    "summary": "Revised: ...",
    "changes": [
        {
            "action": "create|modify",
            "file": "relative/path/to/file.py",
            "description": "What this change does",
            "content": "Full file content (for create)",
            "old_text": "Text to find (for modify)",
            "new_text": "Replacement text (for modify)"
        }
    ],
    "risk": "low|medium|high"
}"""

        user_prompt = f"""## Original Plan
{json.dumps(original_plan, default=str, ensure_ascii=False)[:3000]}

## Test Output (FAILED)
```
{test_output[:2000]}
```

## Current File Contents
{file_contexts[:4000]}

## Project Structure
```
{structure[:1500]}
```

Fix the plan so tests pass. Return JSON only."""

        try:
            response = await self._call_llm(system_prompt, user_prompt, task_type="self_correction")
            revised = self._parse_json_response(response)
            self._safety.audit("revise_plan_done", {
                "changes": len(revised.get("changes", [])),
                "risk": revised.get("risk", "unknown"),
            })
            return revised
        except Exception as exc:
            logger.error("revise_plan_failed", error=str(exc))
            self._safety.audit("revise_plan_failed", {"error": str(exc)})
            return {}

    async def _generate_commit_message(
        self, plan: dict[str, Any], changes_applied: list[str],
    ) -> str:
        """Generate a detailed, informative commit message using a cheap model."""
        system = """Generate a git commit message for this code change.
Format:
- First line: type(scope): short summary (max 72 chars)
- Blank line
- Body: detailed description of WHAT changed and WHY
- List each file changed and what was done
- End with "Automated by: Koda2 Self-Improving Supervisor"

Types: feat, fix, refactor, docs, chore
Return ONLY the commit message text, no JSON."""

        user = f"""Summary: {plan.get('summary', 'Improvement')}
Risk: {plan.get('risk', 'unknown')}
Changes applied: {'; '.join(changes_applied)}
Change details: {json.dumps(plan.get('changes', [])[:5], default=str)[:2000]}"""

        try:
            msg = await self._call_llm(system, user, task_type="commit_message")
            # Clean up: remove markdown fences if present
            msg = msg.strip().strip('`').strip()
            if msg.startswith("```"):
                msg = "\n".join(msg.split("\n")[1:])
            if msg.endswith("```"):
                msg = msg[:-3].strip()
            return msg
        except Exception as exc:
            logger.warning("commit_message_generation_failed", error=str(exc))
            return f"feat(evolution): {plan.get('summary', 'Improvement')[:72]}"

    def _update_changelog(self, plan: dict[str, Any], changes_applied: list[str]) -> None:
        """Append an entry to CHANGELOG.md for this improvement."""
        changelog_path = self._root / "CHANGELOG.md"
        if not changelog_path.exists():
            return

        try:
            import datetime as dt
            today = dt.date.today().isoformat()
            summary = plan.get("summary", "Improvement")
            risk = plan.get("risk", "unknown")

            entry_lines = [
                f"\n### Auto-improvement ({today})",
                f"- **{summary}** (risk: {risk})",
            ]
            for change in changes_applied:
                entry_lines.append(f"  - {change}")
            entry_lines.append("")

            content = changelog_path.read_text()
            # Insert after the first ## heading
            marker = "\n## "
            idx = content.find(marker, content.find(marker) + 1)
            if idx == -1:
                idx = len(content)

            new_content = content[:idx] + "\n".join(entry_lines) + "\n" + content[idx:]
            changelog_path.write_text(new_content)
            logger.info("changelog_updated", summary=summary[:80])
        except Exception as exc:
            logger.warning("changelog_update_failed", error=str(exc))

    async def analyze_error_patterns(self) -> list[dict[str, Any]]:
        """Analyze the audit log for recurring error patterns.

        Returns a list of suggested improvements based on patterns.
        """
        audit_file = self._safety._root.parent / "data" / "supervisor" / "audit_log.jsonl"
        if not audit_file.exists():
            return []

        # Read recent audit entries
        entries = []
        try:
            for line in audit_file.read_text().splitlines()[-200:]:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:
            return []

        # Count crash signatures
        crash_counts: dict[str, int] = {}
        for entry in entries:
            if entry.get("action") == "process_crash":
                stderr = entry.get("stderr_tail", "")
                if stderr:
                    sig = self._safety.crash_signature(stderr)
                    crash_counts[sig] = crash_counts.get(sig, 0) + 1

        # Return recurring crashes (>= 2 occurrences)
        patterns = []
        for sig, count in crash_counts.items():
            if count >= 2:
                patterns.append({
                    "type": "recurring_crash",
                    "signature": sig,
                    "count": count,
                    "suggestion": f"Fix recurring crash: {sig}",
                })

        return patterns

    async def analyze_user_feedback(self, feedback: str) -> dict[str, Any]:
        """Analyze user feedback and determine if it warrants a code change.

        The LLM decides whether the feedback is:
        - A bug report → triggers repair
        - A feature request → triggers evolution
        - A complaint about behavior → triggers prompt/config tweak
        - General feedback → stored as memory, no code change
        """
        system_prompt = """You analyze user feedback about Koda2 (an AI assistant).
Classify the feedback and decide if a code change is needed.

RESPONSE FORMAT (JSON):
{
    "category": "bug|feature|behavior|general",
    "actionable": true/false,
    "improvement_request": "Concrete description of what to change (empty if not actionable)",
    "explanation": "Why this change would help"
}"""

        user_prompt = f"User feedback: {feedback}"

        try:
            response = await self._call_llm(system_prompt, user_prompt, task_type="classify_feedback")
            return self._parse_json_response(response)
        except Exception as exc:
            logger.error("feedback_analysis_failed", error=str(exc))
            return {"category": "general", "actionable": False, "improvement_request": "", "explanation": str(exc)}

    async def process_feedback(self, feedback: str) -> tuple[bool, str]:
        """Full feedback loop: analyze → decide → implement if actionable.

        Returns:
            (acted, message) — whether a code change was made
        """
        self._safety.audit("feedback_received", {"feedback": feedback[:200]})

        analysis = await self.analyze_user_feedback(feedback)
        category = analysis.get("category", "general")
        actionable = analysis.get("actionable", False)
        request = analysis.get("improvement_request", "")

        if not actionable or not request:
            self._safety.audit("feedback_not_actionable", {
                "category": category,
                "explanation": analysis.get("explanation", "")[:200],
            })
            return False, f"Feedback noted ({category}): {analysis.get('explanation', 'No action needed')}"

        # Actionable — trigger improvement
        logger.info("feedback_actionable", category=category, request=request[:100])
        self._safety.audit("feedback_actionable", {"category": category, "request": request[:200]})

        success, message = await self.implement_improvement(request)
        return success, f"[{category}] {message}"

    def _parse_json_response(self, response: str) -> dict[str, Any]:
        """Parse JSON from LLM response."""
        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                return json.loads(match.group())
            raise ValueError("Could not parse LLM response as JSON")
