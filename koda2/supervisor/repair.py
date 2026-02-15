"""Self-Repair Engine — part of the Self-Development Supervisor.

When Koda2 crashes, this engine:
1. Extracts the error and relevant source code
2. Sends it to Claude (via OpenRouter) for analysis
3. Receives a code patch
4. Applies it through the SafetyGuard (test → commit or rollback)
"""

from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger
from koda2.supervisor.safety import SafetyGuard
from koda2.supervisor.model_router import call_llm as _routed_llm_call

logger = get_logger(__name__)

REPAIR_MODEL = "anthropic/claude-sonnet-4-20250514"  # kept for test compatibility
MAX_SOURCE_LINES = 100  # max lines of source context to send


class RepairEngine:
    """LLM-powered crash analysis and code repair."""

    def __init__(self, safety: SafetyGuard, project_root: Optional[Path] = None) -> None:
        self._safety = safety
        self._root = project_root or Path(__file__).parent.parent.parent
        self._settings = get_settings()


    def _extract_crash_info(self, stderr: str) -> dict[str, Any]:
        """Extract structured crash information from stderr output."""
        info: dict[str, Any] = {
            "error_type": "unknown",
            "error_message": "",
            "file": "",
            "line": 0,
            "function": "",
            "traceback": "",
        }

        lines = stderr.strip().splitlines()
        if not lines:
            return info

        # Find traceback
        tb_start = -1
        for i, line in enumerate(lines):
            if line.strip().startswith("Traceback"):
                tb_start = i
                break

        if tb_start >= 0:
            info["traceback"] = "\n".join(lines[tb_start:])

        # Extract error type and message from last line
        for line in reversed(lines):
            line = line.strip()
            if "Error:" in line or "Exception:" in line:
                parts = line.split(":", 1)
                info["error_type"] = parts[0].strip()
                info["error_message"] = parts[1].strip() if len(parts) > 1 else ""
                break

        # Extract file and line number from traceback
        file_pattern = re.compile(r'File "([^"]+)", line (\d+), in (\w+)')
        matches = list(file_pattern.finditer(stderr))
        if matches:
            last_match = matches[-1]
            info["file"] = last_match.group(1)
            info["line"] = int(last_match.group(2))
            info["function"] = last_match.group(3)

        return info

    def _read_source_context(self, file_path: str, error_line: int) -> str:
        """Read source code around the error location."""
        try:
            path = Path(file_path)
            if not path.exists():
                return ""

            # Make path relative to project root if possible
            try:
                path.relative_to(self._root)
            except ValueError:
                return ""  # Don't read files outside project

            content = path.read_text()
            lines = content.splitlines()
            start = max(0, error_line - MAX_SOURCE_LINES // 2)
            end = min(len(lines), error_line + MAX_SOURCE_LINES // 2)

            numbered = []
            for i in range(start, end):
                marker = " >>> " if i + 1 == error_line else "     "
                numbered.append(f"{i + 1:4d}{marker}{lines[i]}")

            return "\n".join(numbered)
        except Exception:
            return ""

    async def _call_llm(self, system: str, user: str, task_type: str = "repair") -> str:
        """Call the LLM via the smart model router."""
        return await _routed_llm_call(
            system, user, task_type=task_type,
            temperature=0.2, max_tokens=8000, timeout=60,
        )

    async def analyze_crash(self, stderr: str) -> dict[str, Any]:
        """Analyze a crash and propose a fix.

        Returns:
            {
                "diagnosis": str,       # Human-readable explanation
                "file": str,            # File to patch (relative path)
                "original": str,        # Original file content
                "patched": str,         # Patched file content
                "commit_message": str,  # Git commit message
                "confidence": str,      # "high", "medium", "low"
            }
        """
        crash_info = self._extract_crash_info(stderr)
        self._safety.audit("crash_analysis_start", crash_info)

        # Read source context
        source_context = ""
        if crash_info["file"]:
            source_context = self._read_source_context(
                crash_info["file"], crash_info["line"]
            )

        # Read the full file for patching
        full_file_content = ""
        relative_path = ""
        if crash_info["file"]:
            try:
                file_path = Path(crash_info["file"])
                relative_path = str(file_path.relative_to(self._root))
                full_file_content = file_path.read_text()
            except (ValueError, FileNotFoundError):
                pass

        system_prompt = """You are a Python debugging expert. You analyze crash reports and generate minimal, targeted fixes.

RULES:
1. Only fix the actual bug — do NOT refactor, add features, or change unrelated code.
2. Your fix must be the MINIMUM change needed to resolve the crash.
3. Return the COMPLETE file content with your fix applied.
4. Explain your diagnosis clearly.
5. Rate your confidence: "high" (obvious fix), "medium" (likely correct), "low" (uncertain).
6. If you're not confident, say so — it's better to not patch than to break things further.

RESPONSE FORMAT (JSON):
{
    "diagnosis": "Clear explanation of what went wrong",
    "confidence": "high|medium|low",
    "commit_message": "fix: brief description",
    "patched_content": "...complete file with fix applied..."
}"""

        user_prompt = f"""Koda2 crashed with this error:

## Error
Type: {crash_info['error_type']}
Message: {crash_info['error_message']}
File: {relative_path}
Line: {crash_info['line']}
Function: {crash_info['function']}

## Traceback
```
{crash_info['traceback']}
```

## Source Context (around error line)
```python
{source_context}
```

## Full File Content ({relative_path})
```python
{full_file_content}
```

Analyze this crash and provide a minimal fix. Return JSON only."""

        try:
            response = await self._call_llm(system_prompt, user_prompt)

            # Parse JSON from response
            result = self._parse_llm_response(response)
            result["file"] = relative_path
            result["original"] = full_file_content

            self._safety.audit("crash_analysis_complete", {
                "file": relative_path,
                "confidence": result.get("confidence", "unknown"),
                "diagnosis": result.get("diagnosis", "")[:200],
            })

            return result

        except Exception as exc:
            logger.error("crash_analysis_failed", error=str(exc))
            self._safety.audit("crash_analysis_failed", {"error": str(exc)})
            return {
                "diagnosis": f"Analysis failed: {exc}",
                "file": relative_path,
                "original": full_file_content,
                "patched": full_file_content,
                "commit_message": "",
                "confidence": "low",
            }

    def _parse_llm_response(self, response: str) -> dict[str, Any]:
        """Parse the LLM's JSON response, handling markdown code blocks."""
        import json

        # Strip markdown code blocks
        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON in the response
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError("Could not parse LLM response as JSON")

        return {
            "diagnosis": data.get("diagnosis", "No diagnosis"),
            "patched": data.get("patched_content", ""),
            "commit_message": data.get("commit_message", "fix: auto-repair"),
            "confidence": data.get("confidence", "low"),
        }

    async def attempt_repair(self, stderr: str) -> tuple[bool, str]:
        """Full repair cycle: analyze → patch → test → commit or rollback.

        Returns:
            (success, message)
        """
        # Check rate limit
        if not self._safety.can_attempt_repair(stderr):
            msg = "Repair attempts exhausted for this crash type"
            logger.warning("repair_rate_limited", message=msg)
            return False, msg

        logger.info("repair_attempt_starting")
        self._safety.audit("repair_cycle_start")

        # Step 1: Analyze
        analysis = await self.analyze_crash(stderr)

        if analysis["confidence"] == "low":
            self._safety.record_repair_attempt(stderr, False)
            msg = f"Low confidence fix — skipping. Diagnosis: {analysis['diagnosis']}"
            logger.warning("repair_low_confidence", diagnosis=analysis["diagnosis"])
            return False, msg

        if not analysis.get("patched") or not analysis.get("file"):
            self._safety.record_repair_attempt(stderr, False)
            return False, f"No patch generated. Diagnosis: {analysis['diagnosis']}"

        # Step 2: Apply patch safely (test → commit or rollback)
        success, patch_msg = self._safety.apply_patch_safely(
            file_path=analysis["file"],
            original_content=analysis["original"],
            patched_content=analysis["patched"],
            commit_message=f"fix(auto-repair): {analysis['commit_message']}",
        )

        self._safety.record_repair_attempt(stderr, success)

        if success:
            self._safety.clear_repair_count(stderr)
            logger.info("repair_success", file=analysis["file"])
            return True, f"Repaired: {analysis['diagnosis']}"
        else:
            logger.warning("repair_failed", message=patch_msg)
            return False, f"Repair failed: {patch_msg}"
