"""Runtime Error Collector — captures tool execution errors for the learning loop.

The orchestrator calls ``record_error()`` when a tool call fails at runtime.
The ContinuousLearner reads these errors as signals for self-improvement.

Errors are stored in a bounded JSONL file (max 500 entries).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

from koda2.logging_config import get_logger

logger = get_logger(__name__)

ERROR_LOG_DIR = Path("data/supervisor")
ERROR_LOG_FILE = ERROR_LOG_DIR / "runtime_errors.jsonl"
MAX_ERROR_ENTRIES = 500


def record_error(
    tool_name: str,
    error: str,
    *,
    args_preview: str = "",
    user_id: str = "",
    channel: str = "",
) -> None:
    """Record a runtime tool execution error (fire-and-forget, never raises)."""
    try:
        ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": dt.datetime.now().isoformat(),
            "tool": tool_name,
            "error": error[:500],
            "args_preview": args_preview[:200],
            "user_id": user_id,
            "channel": channel,
        }
        with open(ERROR_LOG_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Prune if too large
        _prune_if_needed()
    except Exception as exc:
        logger.debug("error_collector_write_failed", error=str(exc))


def read_recent_errors(limit: int = 50) -> list[dict[str, Any]]:
    """Read the most recent runtime errors for analysis."""
    if not ERROR_LOG_FILE.exists():
        return []
    try:
        lines = ERROR_LOG_FILE.read_text().strip().splitlines()
        recent = lines[-limit:]
        errors = []
        for line in recent:
            try:
                errors.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return errors
    except Exception:
        return []


def get_error_summary() -> dict[str, Any]:
    """Get a summary of runtime errors: counts by tool, top errors."""
    errors = read_recent_errors(200)
    if not errors:
        return {"total": 0, "by_tool": {}, "top_errors": []}

    by_tool: dict[str, int] = {}
    error_msgs: dict[str, int] = {}
    for e in errors:
        tool = e.get("tool", "unknown")
        by_tool[tool] = by_tool.get(tool, 0) + 1
        msg = e.get("error", "")[:100]
        error_msgs[msg] = error_msgs.get(msg, 0) + 1

    # Top 10 most frequent errors
    top = sorted(error_msgs.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total": len(errors),
        "by_tool": by_tool,
        "top_errors": [{"error": msg, "count": cnt} for msg, cnt in top],
    }


def _prune_if_needed() -> None:
    """Keep only the last MAX_ERROR_ENTRIES lines."""
    try:
        if not ERROR_LOG_FILE.exists():
            return
        lines = ERROR_LOG_FILE.read_text().strip().splitlines()
        if len(lines) > MAX_ERROR_ENTRIES * 1.5:
            ERROR_LOG_FILE.write_text(
                "\n".join(lines[-MAX_ERROR_ENTRIES:]) + "\n"
            )
    except Exception:
        pass
