"""Tests for the Koda2 Self-Healing Supervisor."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.supervisor.safety import SafetyGuard, MAX_REPAIR_ATTEMPTS, MAX_RESTARTS_PER_WINDOW


# ── SafetyGuard Tests ─────────────────────────────────────────────────

class TestSafetyGuard:
    """Tests for the safety guardrails."""

    def test_crash_signature_extracts_error(self) -> None:
        guard = SafetyGuard()
        stderr = """Traceback (most recent call last):
  File "koda2/orchestrator.py", line 215, in process_message
    while iteration < MAX_TOOL_ITERATIONS:
NameError: name 'MAX_TOOL_ITERATIONS' is not defined"""
        sig = guard.crash_signature(stderr)
        assert "NameError" in sig
        assert "MAX_TOOL_ITERATIONS" in sig

    def test_crash_signature_unknown(self) -> None:
        guard = SafetyGuard()
        sig = guard.crash_signature("")
        assert sig == "unknown_crash"

    def test_crash_signature_last_line_fallback(self) -> None:
        guard = SafetyGuard()
        sig = guard.crash_signature("some random output\nfinal line")
        assert sig == "final line"

    def test_can_attempt_repair_initially(self) -> None:
        guard = SafetyGuard()
        assert guard.can_attempt_repair("SomeError: test")

    def test_repair_attempts_exhausted(self) -> None:
        guard = SafetyGuard()
        error = "NameError: name 'foo' is not defined"
        for _ in range(MAX_REPAIR_ATTEMPTS):
            guard.record_repair_attempt(error, False)
        assert not guard.can_attempt_repair(error)

    def test_clear_repair_count(self) -> None:
        guard = SafetyGuard()
        error = "NameError: name 'foo' is not defined"
        guard.record_repair_attempt(error, False)
        guard.record_repair_attempt(error, False)
        guard.clear_repair_count(error)
        assert guard.can_attempt_repair(error)

    def test_can_restart_initially(self) -> None:
        guard = SafetyGuard()
        assert guard.can_restart()

    def test_restart_rate_limit(self) -> None:
        guard = SafetyGuard()
        for _ in range(MAX_RESTARTS_PER_WINDOW):
            guard.record_restart()
        assert not guard.can_restart()

    def test_audit_creates_log(self, tmp_path) -> None:
        with patch("koda2.supervisor.safety.AUDIT_LOG_DIR", tmp_path), \
             patch("koda2.supervisor.safety.AUDIT_LOG_FILE", tmp_path / "audit.jsonl"):
            guard = SafetyGuard()
            guard.audit("test_action", {"key": "value"})
            log_file = tmp_path / "audit.jsonl"
            assert log_file.exists()
            entry = json.loads(log_file.read_text().strip())
            assert entry["action"] == "test_action"
            assert entry["key"] == "value"

    def test_git_diff_returns_string(self) -> None:
        guard = SafetyGuard()
        diff = guard.git_diff()
        assert isinstance(diff, str)


# ── RepairEngine Tests ────────────────────────────────────────────────

class TestRepairEngine:
    """Tests for crash analysis and repair."""

    def test_extract_crash_info(self) -> None:
        from koda2.supervisor.repair import RepairEngine
        safety = SafetyGuard()
        engine = RepairEngine(safety)

        stderr = """Traceback (most recent call last):
  File "/Users/ronald/Developer/Koda2/koda2/orchestrator.py", line 215, in process_message
    while iteration < MAX_TOOL_ITERATIONS:
NameError: name 'MAX_TOOL_ITERATIONS' is not defined"""

        info = engine._extract_crash_info(stderr)
        assert info["error_type"] == "NameError"
        assert "MAX_TOOL_ITERATIONS" in info["error_message"]
        assert "orchestrator.py" in info["file"]
        assert info["line"] == 215
        assert info["function"] == "process_message"

    def test_extract_crash_info_empty(self) -> None:
        from koda2.supervisor.repair import RepairEngine
        safety = SafetyGuard()
        engine = RepairEngine(safety)
        info = engine._extract_crash_info("")
        assert info["error_type"] == "unknown"

    def test_parse_llm_response_json(self) -> None:
        from koda2.supervisor.repair import RepairEngine
        safety = SafetyGuard()
        engine = RepairEngine(safety)

        response = '{"diagnosis": "Missing import", "confidence": "high", "commit_message": "fix: add import", "patched_content": "import foo"}'
        result = engine._parse_llm_response(response)
        assert result["diagnosis"] == "Missing import"
        assert result["confidence"] == "high"
        assert result["patched"] == "import foo"

    def test_parse_llm_response_markdown_wrapped(self) -> None:
        from koda2.supervisor.repair import RepairEngine
        safety = SafetyGuard()
        engine = RepairEngine(safety)

        response = '```json\n{"diagnosis": "Bug fix", "confidence": "medium", "commit_message": "fix: bug", "patched_content": "fixed"}\n```'
        result = engine._parse_llm_response(response)
        assert result["diagnosis"] == "Bug fix"
        assert result["confidence"] == "medium"


# ── EvolutionEngine Tests ─────────────────────────────────────────────

class TestEvolutionEngine:
    """Tests for the evolution/improvement engine."""

    def test_get_project_structure(self) -> None:
        from koda2.supervisor.evolution import EvolutionEngine
        safety = SafetyGuard()
        engine = EvolutionEngine(safety)
        structure = engine._get_project_structure()
        assert "orchestrator.py" in structure
        assert ".venv" not in structure

    def test_read_file_safe(self) -> None:
        from koda2.supervisor.evolution import EvolutionEngine
        safety = SafetyGuard()
        engine = EvolutionEngine(safety)
        content = engine._read_file_safe("koda2/__init__.py")
        assert isinstance(content, str)

    def test_read_file_safe_missing(self) -> None:
        from koda2.supervisor.evolution import EvolutionEngine
        safety = SafetyGuard()
        engine = EvolutionEngine(safety)
        content = engine._read_file_safe("nonexistent_file.py")
        assert content == ""

    def test_parse_json_response(self) -> None:
        from koda2.supervisor.evolution import EvolutionEngine
        safety = SafetyGuard()
        engine = EvolutionEngine(safety)
        result = engine._parse_json_response('{"summary": "test", "changes": [], "risk": "low"}')
        assert result["summary"] == "test"
        assert result["risk"] == "low"


# ── ProcessMonitor Tests ──────────────────────────────────────────────

class TestProcessMonitor:
    """Tests for the process monitor."""

    def test_monitor_not_running_initially(self) -> None:
        from koda2.supervisor.monitor import ProcessMonitor
        safety = SafetyGuard()
        monitor = ProcessMonitor(safety)
        assert not monitor.is_running
        assert monitor.uptime == 0

    def test_monitor_stderr_buffer_empty(self) -> None:
        from koda2.supervisor.monitor import ProcessMonitor
        safety = SafetyGuard()
        monitor = ProcessMonitor(safety)
        assert monitor.last_stderr == ""

    def test_shutdown_sets_running_false(self) -> None:
        from koda2.supervisor.monitor import ProcessMonitor
        safety = SafetyGuard()
        monitor = ProcessMonitor(safety)
        monitor._running = True
        monitor.shutdown()
        assert not monitor._running


# ── Integration: Safe Patch Workflow ──────────────────────────────────

class TestSafePatchWorkflow:
    """Tests for the full patch → test → commit/rollback workflow."""

    def test_patch_file_not_found(self) -> None:
        guard = SafetyGuard()
        success, msg = guard.apply_patch_safely(
            "nonexistent_file.py", "", "new content", "test commit"
        )
        assert not success
        assert "not found" in msg.lower()

    def test_patch_content_mismatch(self, tmp_path) -> None:
        # Create a temp file
        test_file = tmp_path / "test.py"
        test_file.write_text("original content")

        guard = SafetyGuard(project_root=tmp_path)
        success, msg = guard.apply_patch_safely(
            "test.py", "wrong content", "new content", "test commit"
        )
        assert not success
        assert "changed since analysis" in msg.lower()


# ── Constants ─────────────────────────────────────────────────────────

class TestSupervisorConstants:
    """Tests for supervisor configuration constants."""

    def test_max_repair_attempts(self) -> None:
        assert MAX_REPAIR_ATTEMPTS == 3

    def test_max_restarts(self) -> None:
        assert MAX_RESTARTS_PER_WINDOW == 5

    def test_monitor_constants(self) -> None:
        from koda2.supervisor.monitor import (
            HEALTH_CHECK_INTERVAL,
            STARTUP_GRACE_PERIOD,
            STDERR_BUFFER_LINES,
        )
        assert HEALTH_CHECK_INTERVAL > 0
        assert STARTUP_GRACE_PERIOD > 0
        assert STDERR_BUFFER_LINES > 0

    def test_repair_constants(self) -> None:
        from koda2.supervisor.repair import MAX_SOURCE_LINES, REPAIR_MODEL
        assert MAX_SOURCE_LINES > 0
        assert "claude" in REPAIR_MODEL or "anthropic" in REPAIR_MODEL
