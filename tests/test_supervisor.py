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
        assert "koda2/" in structure
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

    def test_learner_constants(self) -> None:
        from koda2.supervisor.learner import (
            LEARNING_INTERVAL_SECONDS,
            CONVERSATION_LOOKBACK,
            MIN_COMPLAINT_OCCURRENCES,
            MAX_AUTO_IMPROVEMENTS_PER_CYCLE,
        )
        assert LEARNING_INTERVAL_SECONDS > 0
        assert CONVERSATION_LOOKBACK > 0
        assert MIN_COMPLAINT_OCCURRENCES >= 1
        assert MAX_AUTO_IMPROVEMENTS_PER_CYCLE >= 1


# ── ContinuousLearner Tests ──────────────────────────────────────────

class TestContinuousLearner:
    """Tests for the continuous learning loop."""

    def test_learner_init(self) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        assert learner._cycle_count == 0
        assert learner._running is False
        assert isinstance(learner._failed_ideas, set)
        assert isinstance(learner._improvements_applied, list)

    def test_learner_state_persistence(self, tmp_path) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        learner._state_file = tmp_path / "learner_state.json"
        learner._cycle_count = 5
        learner._failed_ideas = {"idea_1", "idea_2"}
        learner._improvements_applied = [{"description": "test"}]
        learner._save_state()

        # Load into new instance
        learner2 = ContinuousLearner(safety)
        learner2._state_file = tmp_path / "learner_state.json"
        learner2._load_state()
        assert learner2._cycle_count == 5
        assert "idea_1" in learner2._failed_ideas
        assert len(learner2._improvements_applied) == 1

    def test_read_current_version(self) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        version = learner._read_current_version()
        # Should match semver pattern
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_determine_bump_type_patch(self) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        assert learner._determine_bump_type([{"type": "bugfix"}]) == "patch"
        assert learner._determine_bump_type([{"type": "improvement"}]) == "patch"

    def test_determine_bump_type_minor(self) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        assert learner._determine_bump_type([{"type": "feature"}]) == "minor"
        assert learner._determine_bump_type([{"type": "bugfix"}, {"type": "feature"}]) == "minor"

    def test_bump_version_patch(self, tmp_path) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety, project_root=tmp_path)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "1.2.3"\n')
        new = learner._bump_version("patch")
        assert new == "1.2.4"
        assert '1.2.4' in pyproject.read_text()

    def test_bump_version_minor(self, tmp_path) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety, project_root=tmp_path)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "1.2.3"\n')
        new = learner._bump_version("minor")
        assert new == "1.3.0"

    def test_bump_version_major(self, tmp_path) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety, project_root=tmp_path)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('version = "1.2.3"\n')
        new = learner._bump_version("major")
        assert new == "2.0.0"

    def test_gather_audit_signals_empty(self) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        signals = learner._gather_audit_signals()
        # May or may not have signals depending on audit log state
        assert isinstance(signals, list)

    def test_gather_log_signals(self) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        signals = learner._gather_log_signals()
        assert isinstance(signals, list)

    def test_stop(self) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        learner._running = True
        learner.stop()
        assert not learner._running

    def test_gather_runtime_error_signals_empty(self) -> None:
        from koda2.supervisor.learner import ContinuousLearner
        safety = SafetyGuard()
        learner = ContinuousLearner(safety)
        signals = learner._gather_runtime_error_signals()
        assert isinstance(signals, list)


# ── SupervisorNotifier Tests ─────────────────────────────────────────

class TestSupervisorNotifier:
    """Tests for the supervisor notification system."""

    def test_notifier_init_no_user(self) -> None:
        from koda2.supervisor.notifier import SupervisorNotifier
        notifier = SupervisorNotifier()
        assert not notifier.is_configured

    def test_notifier_init_with_user(self) -> None:
        from koda2.supervisor.notifier import SupervisorNotifier
        notifier = SupervisorNotifier(user_id="31612345678@s.whatsapp.net")
        assert notifier.is_configured

    @pytest.mark.asyncio
    async def test_notify_improvement_no_user(self) -> None:
        from koda2.supervisor.notifier import SupervisorNotifier
        notifier = SupervisorNotifier()
        # Should not raise even without user_id
        await notifier.notify_improvement_applied("test improvement")

    @pytest.mark.asyncio
    async def test_notify_escalation_no_user(self) -> None:
        from koda2.supervisor.notifier import SupervisorNotifier
        notifier = SupervisorNotifier()
        await notifier.notify_escalation("test issue", 3)

    @pytest.mark.asyncio
    async def test_notify_crash_no_user(self) -> None:
        from koda2.supervisor.notifier import SupervisorNotifier
        notifier = SupervisorNotifier()
        await notifier.notify_crash_and_restart(1, False, "test diagnosis")

    @pytest.mark.asyncio
    async def test_notify_learning_cycle_zero_queued(self) -> None:
        from koda2.supervisor.notifier import SupervisorNotifier
        notifier = SupervisorNotifier(user_id="test")
        # Should return early without sending (queued=0)
        await notifier.notify_learning_cycle(1, 0, 5)


# ── Error Collector Tests ────────────────────────────────────────────

class TestErrorCollector:
    """Tests for the runtime error collector."""

    def test_record_error(self, tmp_path) -> None:
        from koda2.supervisor import error_collector
        with patch.object(error_collector, "ERROR_LOG_DIR", tmp_path), \
             patch.object(error_collector, "ERROR_LOG_FILE", tmp_path / "runtime_errors.jsonl"):
            error_collector.record_error(
                "send_whatsapp", "Connection timeout",
                args_preview='{"to": "+31612345678"}',
                user_id="user1",
                channel="api",
            )
            log_file = tmp_path / "runtime_errors.jsonl"
            assert log_file.exists()
            entry = json.loads(log_file.read_text().strip())
            assert entry["tool"] == "send_whatsapp"
            assert "timeout" in entry["error"].lower()

    def test_read_recent_errors_empty(self) -> None:
        from koda2.supervisor.error_collector import read_recent_errors
        # Should not raise on missing file
        with patch("koda2.supervisor.error_collector.ERROR_LOG_FILE", Path("/nonexistent/path")):
            errors = read_recent_errors()
            assert errors == []

    def test_get_error_summary_empty(self) -> None:
        from koda2.supervisor.error_collector import get_error_summary
        with patch("koda2.supervisor.error_collector.ERROR_LOG_FILE", Path("/nonexistent/path")):
            summary = get_error_summary()
            assert summary["total"] == 0

    def test_record_and_read_multiple(self, tmp_path) -> None:
        from koda2.supervisor import error_collector
        with patch.object(error_collector, "ERROR_LOG_DIR", tmp_path), \
             patch.object(error_collector, "ERROR_LOG_FILE", tmp_path / "runtime_errors.jsonl"):
            error_collector.record_error("tool_a", "Error 1")
            error_collector.record_error("tool_a", "Error 1")
            error_collector.record_error("tool_b", "Error 2")
            errors = error_collector.read_recent_errors()
            assert len(errors) == 3
            summary = error_collector.get_error_summary()
            assert summary["total"] == 3
            assert summary["by_tool"]["tool_a"] == 2
            assert summary["by_tool"]["tool_b"] == 1


# ── Evolution Self-Correction Tests ──────────────────────────────────

class TestEvolutionSelfCorrection:
    """Tests for the self-correction loop in EvolutionEngine."""

    def test_max_self_correction_constant(self) -> None:
        from koda2.supervisor.evolution import MAX_SELF_CORRECTION_ATTEMPTS
        assert MAX_SELF_CORRECTION_ATTEMPTS == 3

    @pytest.mark.asyncio
    async def test_revise_plan_returns_dict_on_failure(self) -> None:
        from koda2.supervisor.evolution import EvolutionEngine
        safety = SafetyGuard()
        engine = EvolutionEngine(safety)
        # With no API key, revise_plan should fail gracefully and return {}
        with patch.object(engine, "_call_llm", side_effect=RuntimeError("No API key")):
            result = await engine.revise_plan(
                {"summary": "test", "changes": [{"file": "test.py", "action": "modify"}]},
                "FAILED: assert False",
            )
            assert result == {}

    @pytest.mark.asyncio
    async def test_apply_plan_self_correction_disabled(self) -> None:
        from koda2.supervisor.evolution import EvolutionEngine
        safety = SafetyGuard()
        engine = EvolutionEngine(safety)
        # Mock run_tests to fail, with self-correction disabled
        with patch.object(safety, "run_tests", return_value=(False, "test failed")), \
             patch.object(safety, "git_stash"), \
             patch.object(safety, "git_reset_hard"), \
             patch.object(safety, "audit"):
            success, msg = await engine.apply_plan(
                {"summary": "test", "changes": []},
                allow_self_correction=False,
            )
            # Empty changes = tests run but nothing was applied
            assert not success or "test failed" in msg or "attempt" in msg.lower()


# ── ImprovementQueue Tests ──────────────────────────────────────────

class TestImprovementQueue:
    """Tests for the persistent improvement queue."""

    def test_queue_add_and_stats(self) -> None:
        from koda2.supervisor.improvement_queue import ImprovementQueue
        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", Path("/tmp/koda2_test_q")), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", Path("/tmp/koda2_test_q/q.json")):
            q = ImprovementQueue()
            q._items = []  # Fresh start
            item = q.add("Improve error handling", source="learner", priority=3)
            assert item["status"] == "pending"
            assert item["source"] == "learner"
            stats = q.stats()
            assert stats["pending"] >= 1

    def test_queue_cancel_item(self) -> None:
        from koda2.supervisor.improvement_queue import ImprovementQueue
        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", Path("/tmp/koda2_test_q")), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", Path("/tmp/koda2_test_q/q.json")):
            q = ImprovementQueue()
            q._items = []
            item = q.add("Test task")
            assert q.cancel_item(item["id"])
            assert q.get_item(item["id"])["status"] == "skipped"

    def test_queue_next_pending_priority(self) -> None:
        from koda2.supervisor.improvement_queue import ImprovementQueue
        with patch("koda2.supervisor.improvement_queue.QUEUE_DIR", Path("/tmp/koda2_test_q")), \
             patch("koda2.supervisor.improvement_queue.QUEUE_FILE", Path("/tmp/koda2_test_q/q.json")):
            q = ImprovementQueue()
            q._items = []
            q.add("Low priority", priority=8)
            q.add("High priority", priority=1)
            nxt = q._next_pending()
            assert nxt is not None
            assert "High priority" in nxt["request"]


# ── Model Router Tests ───────────────────────────────────────────────

class TestModelRouter:
    """Tests for the smart model routing system."""

    def test_task_complexity_mapping(self) -> None:
        from koda2.supervisor.model_router import get_complexity, TaskComplexity
        assert get_complexity("signal_analysis") == TaskComplexity.LIGHT
        assert get_complexity("classify_feedback") == TaskComplexity.LIGHT
        assert get_complexity("crash_analysis") == TaskComplexity.MEDIUM
        assert get_complexity("code_generation") == TaskComplexity.HEAVY
        assert get_complexity("repair") == TaskComplexity.HEAVY
        # Unknown defaults to MEDIUM
        assert get_complexity("unknown_task") == TaskComplexity.MEDIUM

    def test_select_model_openrouter(self) -> None:
        from koda2.supervisor.model_router import select_model, TaskComplexity
        with patch("koda2.supervisor.model_router.get_settings") as mock:
            mock.return_value = MagicMock(
                openrouter_api_key="sk-or-test123",
                anthropic_api_key="",
                openai_api_key="",
            )
            url, model, complexity = select_model("signal_analysis")
            assert "openrouter" in url
            assert complexity == TaskComplexity.LIGHT

            url, model, complexity = select_model("code_generation")
            assert complexity == TaskComplexity.HEAVY
            assert "claude" in model or "anthropic" in model

    def test_select_model_anthropic_direct(self) -> None:
        from koda2.supervisor.model_router import select_model, TaskComplexity, BACKEND_ANTHROPIC
        with patch("koda2.supervisor.model_router.get_settings") as mock:
            mock.return_value = MagicMock(
                openrouter_api_key="",
                anthropic_api_key="sk-ant-test123",
                openai_api_key="",
            )
            backend, model, complexity = select_model("code_generation")
            assert backend == BACKEND_ANTHROPIC
            assert "claude-sonnet-4" in model
            assert complexity == TaskComplexity.HEAVY

            backend, model, complexity = select_model("signal_analysis")
            assert backend == BACKEND_ANTHROPIC
            assert "haiku" in model
            assert complexity == TaskComplexity.LIGHT

    def test_select_model_openai_fallback(self) -> None:
        from koda2.supervisor.model_router import select_model, TaskComplexity
        with patch("koda2.supervisor.model_router.get_settings") as mock:
            mock.return_value = MagicMock(
                openrouter_api_key="",
                anthropic_api_key="",
                openai_api_key="sk-test123",
            )
            url, model, complexity = select_model("code_generation")
            assert "openai" in url
            assert model == "gpt-4o"
            assert complexity == TaskComplexity.HEAVY

            url, model, complexity = select_model("signal_analysis")
            assert model == "gpt-4o-mini"
            assert complexity == TaskComplexity.LIGHT

    def test_select_model_no_keys_raises(self) -> None:
        from koda2.supervisor.model_router import select_model
        with patch("koda2.supervisor.model_router.get_settings") as mock:
            mock.return_value = MagicMock(
                openrouter_api_key="",
                anthropic_api_key="",
                openai_api_key="",
            )
            with pytest.raises(RuntimeError, match="No API key configured"):
                select_model("code_generation")

    def test_model_tiers_all_have_entries(self) -> None:
        from koda2.supervisor.model_router import MODEL_TIERS, TaskComplexity
        for complexity in TaskComplexity:
            assert len(MODEL_TIERS[complexity]) > 0


# ── Restart Signal Tests ─────────────────────────────────────────────

class TestRestartSignal:
    """Tests for the process restart signaling."""

    def test_request_restart(self, tmp_path) -> None:
        with patch("koda2.supervisor.safety.AUDIT_LOG_DIR", tmp_path), \
             patch("koda2.supervisor.safety.AUDIT_LOG_FILE", tmp_path / "audit.jsonl"):
            guard = SafetyGuard()
            guard.request_restart("code updated")
            assert (tmp_path / "restart_requested").exists()
            assert "code updated" in (tmp_path / "restart_requested").read_text()

    def test_check_restart_requested(self, tmp_path) -> None:
        with patch("koda2.supervisor.safety.AUDIT_LOG_DIR", tmp_path), \
             patch("koda2.supervisor.safety.AUDIT_LOG_FILE", tmp_path / "audit.jsonl"):
            guard = SafetyGuard()
            # No restart requested
            assert guard.check_restart_requested() == ""
            # Request one
            guard.request_restart("new feature")
            reason = guard.check_restart_requested()
            assert reason == "new feature"
            # Should be consumed
            assert guard.check_restart_requested() == ""


# ── Changelog Update Tests ───────────────────────────────────────────

class TestChangelogUpdate:
    """Tests for automatic CHANGELOG.md updates."""

    def test_update_changelog(self, tmp_path) -> None:
        from koda2.supervisor.evolution import EvolutionEngine
        safety = SafetyGuard()
        engine = EvolutionEngine(safety, project_root=tmp_path)
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("# Changelog\n\n## [0.5.0] - 2026-02-14\n\n### Added\n- Feature X\n")

        engine._update_changelog(
            {"summary": "Better error handling", "risk": "low"},
            ["Modified koda2/orchestrator.py"],
        )

        content = changelog.read_text()
        assert "Better error handling" in content
        assert "Modified koda2/orchestrator.py" in content

    def test_update_changelog_missing_file(self, tmp_path) -> None:
        from koda2.supervisor.evolution import EvolutionEngine
        safety = SafetyGuard()
        engine = EvolutionEngine(safety, project_root=tmp_path)
        # Should not raise when CHANGELOG.md doesn't exist
        engine._update_changelog({"summary": "test"}, [])


# ── Git Remote Polling Tests ─────────────────────────────────────────

class TestGitRemotePolling:
    """Tests for git fetch, remote ahead detection, and auto-pull."""

    def test_git_fetch(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        with patch.object(guard, "_git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0)
            assert guard.git_fetch() is True
            mock_git.assert_called_once_with("fetch", "--quiet", check=False)

    def test_git_fetch_failure(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        with patch.object(guard, "_git", side_effect=Exception("network error")):
            assert guard.git_fetch() is False

    def test_check_remote_ahead_no_updates(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        with patch.object(guard, "_git") as mock_git:
            # Same local and remote hash
            mock_git.return_value = MagicMock(stdout="abc123\n", returncode=0)
            has_updates, summary = guard.check_remote_ahead()
            assert has_updates is False
            assert summary == ""

    def test_check_remote_ahead_with_updates(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        call_count = [0]
        def fake_git(*args, **kwargs):
            call_count[0] += 1
            m = MagicMock(returncode=0)
            if args[0] == "rev-parse" and args[1] == "--abbrev-ref":
                m.stdout = "main\n"
            elif args[0] == "rev-parse" and args[1] == "HEAD":
                m.stdout = "aaa111\n"
            elif args[0] == "rev-parse" and "origin/" in args[1]:
                m.stdout = "bbb222\n"
            elif args[0] == "merge-base":
                m.stdout = "aaa111\n"  # local is ancestor of remote
            elif args[0] == "log":
                m.stdout = "bbb222 feat: new feature\nccc333 fix: bug fix\n"
            else:
                m.stdout = ""
            return m

        with patch.object(guard, "_git", side_effect=fake_git), \
             patch.object(guard, "audit"):
            has_updates, summary = guard.check_remote_ahead()
            assert has_updates is True
            assert "new feature" in summary

    def test_git_pull_success(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        with patch.object(guard, "_git") as mock_git, \
             patch.object(guard, "audit"):
            mock_git.return_value = MagicMock(returncode=0, stdout="Updating aaa..bbb\n", stderr="")
            success, output = guard.git_pull()
            assert success is True
            mock_git.assert_called_once_with("pull", "--ff-only", check=False)

    def test_git_pull_failure(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        with patch.object(guard, "_git") as mock_git, \
             patch.object(guard, "audit"):
            mock_git.return_value = MagicMock(returncode=1, stdout="", stderr="merge conflict\n")
            success, output = guard.git_pull()
            assert success is False
            assert "merge conflict" in output

    def test_monitor_check_remote_updates_rate_limit(self) -> None:
        from koda2.supervisor.monitor import ProcessMonitor, GIT_POLL_INTERVAL
        safety = MagicMock()
        monitor = ProcessMonitor(safety)
        # First call within interval should skip
        monitor._last_git_check = time.monotonic()
        assert monitor._check_remote_updates() is False
        safety.git_fetch.assert_not_called()

    def test_monitor_check_remote_updates_pulls(self) -> None:
        from koda2.supervisor.monitor import ProcessMonitor
        safety = MagicMock()
        safety.git_fetch.return_value = True
        safety.check_remote_ahead.return_value = (True, "abc123 new commit")
        safety.git_pull.return_value = (True, "Fast-forward")
        monitor = ProcessMonitor(safety)
        monitor._last_git_check = 0  # Force check
        with patch.object(monitor, "_rebuild_npm_packages") as mock_npm:
            assert monitor._check_remote_updates() is True
            safety.git_pull.assert_called_once()
            mock_npm.assert_called_once()
            safety.request_restart.assert_called_once()

    def test_rebuild_npm_packages(self, tmp_path) -> None:
        """npm install is called for each package.json (excluding node_modules)."""
        from koda2.supervisor.monitor import ProcessMonitor
        safety = MagicMock()
        safety._root = tmp_path
        monitor = ProcessMonitor(safety)

        # Create a package.json in a subdirectory
        bridge_dir = tmp_path / "koda2" / "modules" / "messaging" / "whatsapp_bridge"
        bridge_dir.mkdir(parents=True)
        (bridge_dir / "package.json").write_text('{"name": "test"}')

        # Create a package.json inside node_modules (should be skipped)
        nm_dir = bridge_dir / "node_modules" / "some-pkg"
        nm_dir.mkdir(parents=True)
        (nm_dir / "package.json").write_text('{"name": "skip-me"}')

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            monitor._rebuild_npm_packages()
            # Only the bridge package.json should trigger npm install, not node_modules
            assert mock_run.call_count == 1
            call_args = mock_run.call_args
            assert call_args[0][0] == ["npm", "install", "--production"]
            assert str(bridge_dir) in str(call_args)


# ── Pip Install Tests ────────────────────────────────────────────────

class TestPipInstall:
    """Tests for SafetyGuard.pip_install package management."""

    def test_pip_install_no_packages(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        success, output = guard.pip_install()
        assert success is False
        assert "No packages" in output

    def test_pip_install_success(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="Successfully installed foo", stderr="")
            success, output = guard.pip_install("some-package")
            assert success is True
            assert "Successfully installed" in output

    def test_pip_install_failure(self, tmp_path) -> None:
        guard = SafetyGuard(project_root=tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="No matching distribution")
            success, output = guard.pip_install("nonexistent-pkg")
            assert success is False
            assert "No matching distribution" in output
