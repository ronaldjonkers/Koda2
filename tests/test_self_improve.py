"""Tests for the self-improvement and plugin system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from koda2.modules.self_improve.service import SelfImproveService


class TestSelfImproveService:
    """Tests for capability detection and plugin management."""

    @pytest.fixture
    def service(self) -> SelfImproveService:
        return SelfImproveService()

    def test_has_known_capability(self, service: SelfImproveService) -> None:
        """Known capabilities are detected."""
        assert service.has_capability("schedule_meeting") is True
        assert service.has_capability("send_email") is True
        assert service.has_capability("generate_document") is True

    def test_detect_missing_capability(self, service: SelfImproveService) -> None:
        """Missing capabilities are detected."""
        result = service.detect_missing("translate_document")
        assert result == "translate_document"

    def test_detect_existing_capability(self, service: SelfImproveService) -> None:
        """Existing capabilities return None."""
        result = service.detect_missing("send_email")
        assert result is None

    def test_detect_partial_match(self, service: SelfImproveService) -> None:
        """Partial matches to existing capabilities return None."""
        result = service.detect_missing("schedule")
        assert result is None

    def test_list_capabilities(self, service: SelfImproveService) -> None:
        """Capability listing returns all known capabilities."""
        caps = service.list_capabilities()
        assert isinstance(caps, dict)
        assert "schedule_meeting" in caps
        assert "send_email" in caps

    def test_list_plugins_empty(self, service: SelfImproveService) -> None:
        """Empty plugin list when no plugins loaded."""
        assert service.list_plugins() == []

    def test_load_plugin(self, service: SelfImproveService, tmp_path: Path) -> None:
        """Loading a valid plugin registers it."""
        plugin_code = '''
class TestPlugin:
    name = "test_plugin"
    description = "A test plugin"
    version = "0.1.0"
    capabilities = ["test_capability"]

    def execute(self):
        return "executed"

def register():
    return TestPlugin()
'''
        plugin_file = tmp_path / "test_plugin.py"
        plugin_file.write_text(plugin_code)

        plugin = service.load_plugin(str(plugin_file))
        assert plugin.name == "test_plugin"
        assert "test_capability" in plugin.capabilities
        assert service.has_capability("test_capability") is True

    def test_load_plugin_no_register(self, service: SelfImproveService, tmp_path: Path) -> None:
        """Plugin without register() raises ImportError."""
        plugin_file = tmp_path / "bad_plugin.py"
        plugin_file.write_text("x = 1\n")

        with pytest.raises(ImportError, match="no register"):
            service.load_plugin(str(plugin_file))

    def test_load_plugin_file_not_found(self, service: SelfImproveService) -> None:
        """Loading nonexistent plugin raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            service.load_plugin("/nonexistent/plugin.py")

    def test_get_plugin(self, service: SelfImproveService, tmp_path: Path) -> None:
        """get_plugin returns loaded plugin by name."""
        plugin_code = '''
class MyPlugin:
    name = "my_plugin"
    description = "My plugin"
    version = "1.0.0"
    capabilities = ["my_cap"]

def register():
    return MyPlugin()
'''
        plugin_file = tmp_path / "my_plugin.py"
        plugin_file.write_text(plugin_code)
        service.load_plugin(str(plugin_file))

        plugin = service.get_plugin("my_plugin")
        assert plugin is not None
        assert plugin.version == "1.0.0"

    def test_get_nonexistent_plugin(self, service: SelfImproveService) -> None:
        """get_plugin returns None for unknown plugin."""
        assert service.get_plugin("nonexistent") is None

    @pytest.mark.asyncio
    async def test_generate_plugin_requires_llm(self, service: SelfImproveService) -> None:
        """generate_plugin raises if LLM router not set."""
        with pytest.raises(RuntimeError, match="LLM router not configured"):
            await service.generate_plugin("test_cap", "Test capability")
