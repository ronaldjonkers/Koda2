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

import httpx

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.supervisor.safety import SafetyGuard

logger = get_logger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
EVOLUTION_MODEL_FALLBACK = "anthropic/claude-3.5-sonnet"


class EvolutionEngine:
    """Generates code improvements and new features via LLM."""

    def __init__(self, safety: SafetyGuard, project_root: Optional[Path] = None) -> None:
        self._safety = safety
        self._root = project_root or Path(__file__).parent.parent.parent
        self._settings = get_settings()

    def _get_api_key(self) -> str:
        """Get API key for LLM access."""
        key = self._settings.openrouter_api_key
        if not key:
            key = self._settings.openai_api_key
        if not key:
            raise RuntimeError("No API key for evolution engine")
        return key

    async def _call_llm(self, system: str, user: str) -> str:
        """Call the LLM via OpenRouter or OpenAI."""
        api_key = self._get_api_key()

        if api_key.startswith("sk-or-"):
            url = OPENROUTER_URL
            model = self._settings.openrouter_model or EVOLUTION_MODEL_FALLBACK
        else:
            url = "https://api.openai.com/v1/chat/completions"
            model = "gpt-4o"

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 16000,
                },
            )
            if resp.status_code != 200:
                body = resp.text[:500]
                logger.error("llm_call_failed", status=resp.status_code, body=body, model=model)
                resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

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

        # Step 1: Plan
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

        # Step 2: Backup
        self._safety.git_stash("pre-evolution-backup")

        all_success = True
        messages = []

        try:
            # Step 3: Apply changes
            for change in plan["changes"]:
                action = change.get("action", "modify")
                file_path = change.get("file", "")

                if not file_path:
                    continue

                full_path = self._root / file_path

                if action == "create":
                    # Create new file
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

            # Step 4: Run tests
            passed, test_output = self._safety.run_tests()

            if passed:
                # Step 5: Commit
                commit_msg = f"feat(evolution): {plan['summary'][:80]}"
                self._safety.git_commit(commit_msg)
                self._safety.git_push()
                self._safety.audit("evolution_success", {"summary": plan["summary"]})
                return True, f"Improvement applied: {plan['summary']}\nChanges: {'; '.join(messages)}"
            else:
                # Rollback
                self._safety.git_reset_hard()
                self._safety.audit("evolution_rollback", {"test_output": test_output[:500]})
                return False, f"Tests failed after changes — rolled back.\n{test_output[:300]}"

        except Exception as exc:
            self._safety.git_reset_hard()
            self._safety.audit("evolution_error", {"error": str(exc)})
            return False, f"Evolution failed: {exc}"

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
            response = await self._call_llm(system_prompt, user_prompt)
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
