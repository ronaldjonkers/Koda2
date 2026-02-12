"""Self-improvement engine — capability detection, auto-code generation, plugin system."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional

from koda2.logging_config import get_logger
from koda2.modules.git_manager.service import GitManagerService

logger = get_logger(__name__)

PLUGINS_DIR = Path("plugins")
PLUGINS_DIR.mkdir(exist_ok=True)


class Plugin:
    """Metadata about a loaded plugin."""

    def __init__(
        self,
        name: str,
        description: str,
        version: str,
        module: Any,
        capabilities: list[str],
    ) -> None:
        self.name = name
        self.description = description
        self.version = version
        self.module = module
        self.capabilities = capabilities


class SelfImproveService:
    """Detects missing capabilities and generates new modules/plugins."""

    def __init__(self) -> None:
        self._known_capabilities: dict[str, str] = {
            "schedule_meeting": "calendar",
            "send_email": "email",
            "read_email": "email",
            "generate_document": "documents",
            "generate_image": "images",
            "analyze_image": "images",
            "send_telegram": "messaging",
            "send_whatsapp": "messaging",
            "run_shell": "macos",
            "get_contacts": "macos",
            "create_reminder": "macos",
            "search_memory": "memory",
            "schedule_task": "scheduler",
        }
        self._plugins: dict[str, Plugin] = {}
        self._llm_router: Optional[Any] = None
        self._git_manager: Optional[GitManagerService] = None

    def set_llm_router(self, router: Any) -> None:
        """Inject the LLM router for code generation."""
        self._llm_router = router
        # Initialize git manager with same LLM router
        self._git_manager = GitManagerService(router)

    async def handle_plugin_generation_complete(
        self, 
        capability_name: str, 
        plugin_path: str,
        description: str,
    ) -> dict[str, Any]:
        """Handle post-generation tasks: docs update, git commit."""
        if not self._git_manager:
            return {"committed": False, "reason": "no_git_manager"}
        
        return await self._git_manager.after_plugin_generation(
            capability_name, plugin_path, description
        )

    def has_capability(self, capability: str) -> bool:
        """Check if a capability exists in core modules or plugins."""
        if capability in self._known_capabilities:
            return True
        return any(capability in p.capabilities for p in self._plugins.values())

    def detect_missing(self, requested: str) -> Optional[str]:
        """Detect if a requested capability is missing.

        Returns the capability name if missing, None if available.
        """
        normalized = requested.lower().replace(" ", "_").replace("-", "_")
        if self.has_capability(normalized):
            return None
        for cap in self._known_capabilities:
            if cap in normalized or normalized in cap:
                return None
        return normalized

    async def generate_plugin(
        self,
        capability_name: str,
        description: str,
    ) -> str:
        """Auto-generate a plugin module for a missing capability."""
        if not self._llm_router:
            raise RuntimeError("LLM router not configured for self-improvement")

        prompt = f"""Generate a Python plugin module for Koda2.

Capability: {capability_name}
Description: {description}

Requirements:
1. Create a class named `{capability_name.title().replace('_', '')}Plugin`
2. The class must have:
   - `name` class attribute (str)
   - `description` class attribute (str)
   - `version` class attribute (str, default "0.1.0")
   - `capabilities` class attribute (list[str])
   - async methods implementing the capability
   - Proper error handling and logging
3. Use the koda2.logging_config.get_logger for logging
4. Include a module-level `register()` function that returns an instance of the plugin class
5. Include docstrings for all classes and methods
6. Include type hints throughout

Return ONLY the Python code, no markdown formatting."""

        code = await self._llm_router.quick(prompt, complexity="complex")

        code = code.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

        plugin_file = PLUGINS_DIR / f"{capability_name}.py"
        plugin_file.write_text(code)
        logger.info("plugin_generated", capability=capability_name, path=str(plugin_file))

        test_code = await self._generate_test(capability_name, code)
        test_file = Path("tests") / "plugins" / f"test_{capability_name}.py"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(test_code)
        logger.info("plugin_test_generated", path=str(test_file))

        self.load_plugin(str(plugin_file))
        
        # Trigger git commit and doc updates
        if self._git_manager:
            try:
                import asyncio
                await self.handle_plugin_generation_complete(
                    capability_name, str(plugin_file), description
                )
            except Exception as exc:
                logger.error("post_generation_hook_failed", error=str(exc))
        
        return str(plugin_file)

    async def _generate_test(self, capability_name: str, plugin_code: str) -> str:
        """Generate test code for a plugin."""
        if not self._llm_router:
            return f'"""Tests for {capability_name} plugin."""\n\ndef test_placeholder():\n    pass\n'

        prompt = f"""Generate pytest tests for this Python plugin:

```python
{plugin_code}
```

Requirements:
1. Test the register() function
2. Test each public method (use mocks for external dependencies)
3. Test error handling
4. Use pytest and pytest-asyncio
5. Include proper imports

Return ONLY the Python code, no markdown."""

        test_code = await self._llm_router.quick(prompt, complexity="standard")
        test_code = test_code.strip()
        if test_code.startswith("```"):
            lines = test_code.split("\n")
            test_code = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        return test_code

    def load_plugin(self, plugin_path: str) -> Plugin:
        """Dynamically load a plugin from a Python file."""
        path = Path(plugin_path)
        if not path.exists():
            raise FileNotFoundError(f"Plugin not found: {plugin_path}")

        module_name = f"koda2_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin: {plugin_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        if hasattr(module, "register"):
            instance = module.register()
            plugin = Plugin(
                name=getattr(instance, "name", path.stem),
                description=getattr(instance, "description", ""),
                version=getattr(instance, "version", "0.1.0"),
                module=instance,
                capabilities=getattr(instance, "capabilities", [path.stem]),
            )
            self._plugins[plugin.name] = plugin
            for cap in plugin.capabilities:
                self._known_capabilities[cap] = f"plugin:{plugin.name}"
            logger.info("plugin_loaded", name=plugin.name, capabilities=plugin.capabilities)
            return plugin

        raise ImportError(f"Plugin {plugin_path} has no register() function")

    def load_all_plugins(self) -> int:
        """Load all plugins from the plugins directory."""
        count = 0
        for plugin_file in PLUGINS_DIR.glob("*.py"):
            if plugin_file.name.startswith("_"):
                continue
            try:
                self.load_plugin(str(plugin_file))
                count += 1
            except Exception as exc:
                logger.error("plugin_load_failed", file=str(plugin_file), error=str(exc))
        return count

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all loaded plugins with metadata."""
        return [
            {
                "name": p.name,
                "description": p.description,
                "version": p.version,
                "capabilities": p.capabilities,
            }
            for p in self._plugins.values()
        ]

    def list_capabilities(self) -> dict[str, str]:
        """List all known capabilities and their source modules."""
        return dict(self._known_capabilities)

    def get_plugin(self, name: str) -> Optional[Plugin]:
        """Get a loaded plugin by name."""
        return self._plugins.get(name)
