"""Git manager service for auto-commits, doc updates, and repository maintenance."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger

logger = get_logger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent.parent


class GitManagerService:
    """Manages git operations, auto-commits, and documentation updates.
    
    This service integrates with the self-improvement engine to automatically
    commit changes, generate meaningful commit messages using LLM analysis of
    diffs, and keep documentation in sync with code changes.
    """

    def __init__(self, llm_router: Optional[Any] = None) -> None:
        self._llm = llm_router
        self._settings = get_settings()

    def set_llm_router(self, router: Any) -> None:
        """Inject LLM router for commit message generation."""
        self._llm = router

    async def _run_git(
        self, 
        *args: str, 
        cwd: Optional[Path] = None,
        check: bool = True,
    ) -> tuple[int, str, str]:
        """Execute a git command and return (returncode, stdout, stderr)."""
        cmd = ["git"] + list(args)
        logger.debug("git_executing", command=" ".join(cmd))
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd or REPO_ROOT),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            
            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()
            
            if check and proc.returncode != 0:
                logger.error("git_command_failed", 
                           command=" ".join(cmd), 
                           stderr=stderr_str,
                           returncode=proc.returncode)
            
            return proc.returncode, stdout_str, stderr_str
        except Exception as exc:
            logger.error("git_execution_error", error=str(exc))
            return 1, "", str(exc)

    async def is_repo(self) -> bool:
        """Check if we're in a git repository."""
        code, _, _ = await self._run_git("rev-parse", "--git-dir", check=False)
        return code == 0

    async def has_changes(self) -> bool:
        """Check if there are uncommitted changes."""
        code, stdout, _ = await self._run_git(
            "status", "--porcelain", "--untracked-files=all", check=False
        )
        return code == 0 and bool(stdout.strip())

    async def get_diff(self, staged: bool = False) -> str:
        """Get the diff of changes."""
        args = ["diff", "--stat"] if staged else ["diff", "--stat"]
        _, stdout, _ = await self._run_git(*args, check=False)
        return stdout

    async def get_changed_files(self) -> list[dict[str, str]]:
        """Get list of changed files with their status."""
        code, stdout, _ = await self._run_git(
            "status", "--porcelain", "--untracked-files=all", check=False
        )
        if code != 0:
            return []
        
        files = []
        for line in stdout.strip().split("\n"):
            if len(line) >= 3:
                status = line[:2].strip()
                filepath = line[3:].strip()
                files.append({
                    "status": status,
                    "path": filepath,
                    "type": self._categorize_file(filepath),
                })
        return files

    def _categorize_file(self, filepath: str) -> str:
        """Categorize a file by its path."""
        if filepath.startswith("koda2/modules/"):
            return "module"
        elif filepath.startswith("tests/"):
            return "test"
        elif filepath.startswith("docs/"):
            return "docs"
        elif filepath in ("README.md", "CHANGELOG.md"):
            return "docs"
        elif filepath == ".env.example":
            return "config"
        elif filepath.endswith(".py"):
            return "code"
        else:
            return "other"

    async def _generate_commit_message(
        self, 
        files: list[dict[str, str]], 
        diff_summary: str,
        context: Optional[str] = None,
    ) -> str:
        """Generate a conventional commit message using LLM."""
        if not self._llm:
            # Fallback to simple message
            types = {f["type"] for f in files}
            if "module" in types:
                return f"feat: add/update modules ({len(files)} files changed)"
            elif "test" in types:
                return f"test: update test suite ({len(files)} files changed)"
            elif "docs" in types:
                return f"docs: update documentation ({len(files)} files changed)"
            else:
                return f"chore: update {len(files)} files"

        file_list = "\n".join(f"  - {f['status']} {f['path']} ({f['type']})" for f in files[:20])
        
        prompt = f"""Generate a conventional commit message for these changes.

Files changed:
{file_list}

Diff summary:
{diff_summary[:1000]}

Context: {context or "Auto-generated changes via Koda2 self-improvement"}

Requirements:
1. Use conventional commits format: type(scope): description
2. Types: feat, fix, docs, style, refactor, test, chore
3. Keep the first line under 72 characters
4. Add a detailed body if needed (separated by blank line)
5. Be specific about what changed and why
6. Reference module names in scope when applicable

Return ONLY the commit message, no markdown formatting."""

        try:
            message = await self._llm.quick(prompt, complexity="simple")
            message = message.strip()
            # Remove code blocks if present
            if message.startswith("```"):
                lines = message.split("\n")
                message = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            return message.strip()
        except Exception as exc:
            logger.error("commit_message_generation_failed", error=str(exc))
            return f"feat: auto-update {len(files)} files via Koda2"

    async def stage_all(self) -> bool:
        """Stage all changes including untracked files."""
        code, _, stderr = await self._run_git("add", "-A")
        if code != 0:
            logger.error("git_add_failed", stderr=stderr)
            return False
        logger.debug("git_all_staged")
        return True

    async def commit(
        self, 
        message: Optional[str] = None,
        context: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Commit changes with auto-generated or provided message.
        
        Returns:
            Tuple of (success, commit_message)
        """
        if not await self.is_repo():
            logger.warning("git_not_a_repository")
            return False, ""

        if not await self.has_changes():
            logger.info("git_no_changes_to_commit")
            return False, ""

        if not await self.stage_all():
            return False, ""

        # Generate message if not provided
        if not message:
            files = await self.get_changed_files()
            diff = await self.get_diff(staged=True)
            message = await self._generate_commit_message(files, diff, context)

        # Commit
        code, stdout, stderr = await self._run_git(
            "commit", "-m", message, check=False
        )
        
        if code != 0:
            # Check if it's just "nothing to commit"
            if "nothing to commit" in stderr.lower():
                logger.info("git_nothing_to_commit")
                return False, ""
            logger.error("git_commit_failed", stderr=stderr)
            return False, ""

        logger.info("git_commit_success", message=message.split("\n")[0])
        return True, message

    async def push(self) -> bool:
        """Push commits to remote."""
        if not await self.is_repo():
            return False

        # Check if we have a remote
        code, remotes, _ = await self._run_git("remote", check=False)
        if code != 0 or not remotes.strip():
            logger.warning("git_no_remote_configured")
            return False

        # Push
        code, stdout, stderr = await self._run_git("push", check=False)
        if code != 0:
            logger.error("git_push_failed", stderr=stderr)
            return False

        logger.info("git_push_success")
        return True

    async def commit_and_push(
        self, 
        context: Optional[str] = None,
    ) -> dict[str, Any]:
        """Commit and push changes.
        
        This is used by the self-improvement system after generating code.
        """
        if not await self.is_repo():
            return {"committed": False, "pushed": False, "reason": "not_a_repo"}

        committed, message = await self.commit(context=context)
        
        result = {
            "committed": committed,
            "message": message,
            "pushed": False,
        }

        if committed:
            result["pushed"] = await self.push()

        return result

    # ── Documentation Updates ────────────────────────────────────────

    async def update_readme_capabilities(self, capabilities: list[dict[str, Any]]) -> bool:
        """Update the capabilities table in README.md."""
        readme_path = REPO_ROOT / "README.md"
        if not readme_path.exists():
            logger.warning("readme_not_found")
            return False

        content = readme_path.read_text(encoding="utf-8")
        
        # Generate new capabilities table
        table_lines = [
            "## Capabilities",
            "",
            "| Module | Features | Status |",
            "|--------|----------|--------|",
        ]
        
        for cap in sorted(capabilities, key=lambda x: x.get("name", "")):
            name = cap.get("name", "")
            features = cap.get("features", "")
            status = "✅" if cap.get("implemented", False) else "🚧"
            table_lines.append(f"| {name} | {features} | {status} |")

        new_section = "\n".join(table_lines)

        # Find and replace existing capabilities section
        import re
        pattern = r"## Capabilities\n.*?\n(?=## |\Z)"
        
        if re.search(pattern, content, re.DOTALL):
            content = re.sub(pattern, new_section + "\n\n", content, flags=re.DOTALL)
        else:
            # Add before the first ## or at the end
            if "## " in content:
                first_header = content.find("## ")
                content = content[:first_header] + new_section + "\n\n" + content[first_header:]
            else:
                content += "\n\n" + new_section + "\n"

        readme_path.write_text(content, encoding="utf-8")
        logger.info("readme_capabilities_updated")
        return True

    async def update_changelog(
        self, 
        version: str, 
        changes: list[dict[str, Any]],
    ) -> bool:
        """Add entry to CHANGELOG.md following Keep a Changelog format."""
        changelog_path = REPO_ROOT / "CHANGELOG.md"
        
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        
        entry_lines = [f"## [{version}] - {today}", ""]
        
        # Group by type
        by_type: dict[str, list[str]] = {}
        for change in changes:
            change_type = change.get("type", "changed")
            description = change.get("description", "")
            by_type.setdefault(change_type, []).append(description)
        
        type_headers = {
            "added": "### Added",
            "changed": "### Changed", 
            "deprecated": "### Deprecated",
            "removed": "### Removed",
            "fixed": "### Fixed",
            "security": "### Security",
        }
        
        for type_key, header in type_headers.items():
            if type_key in by_type:
                entry_lines.append(header)
                for desc in by_type[type_key]:
                    entry_lines.append(f"- {desc}")
                entry_lines.append("")

        new_entry = "\n".join(entry_lines)

        if changelog_path.exists():
            content = changelog_path.read_text(encoding="utf-8")
            # Insert after the header
            if "# Changelog" in content:
                insert_pos = content.find("\n## [") if "\n## [" in content else len(content)
                content = content[:insert_pos] + new_entry + "\n" + content[insert_pos:]
            else:
                content = f"# Changelog\n\nAll notable changes to this project.\n\n{new_entry}\n" + content
        else:
            content = f"# Changelog\n\nAll notable changes to this project.\n\n{new_entry}\n"

        changelog_path.write_text(content, encoding="utf-8")
        logger.info("changelog_updated", version=version)
        return True

    async def create_adr(
        self, 
        number: int, 
        title: str, 
        context: str, 
        decision: str,
        consequences: list[str],
    ) -> str:
        """Create a new Architecture Decision Record."""
        adr_dir = REPO_ROOT / "docs" / "adr"
        adr_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{number:03d}-{title.lower().replace(' ', '-').replace('_', '-')}.md"
        filepath = adr_dir / filename
        
        consequences_text = "\n".join(f"- {c}" for c in consequences)
        
        content = f"""# ADR-{number:03d}: {title}

## Status
Accepted

## Date
{datetime.now(timezone.utc).strftime("%Y-%m-%d")}

## Context
{context}

## Decision
{decision}

## Consequences
{consequences_text}
"""
        
        filepath.write_text(content, encoding="utf-8")
        logger.info("adr_created", number=number, title=title, path=str(filepath))
        return str(filepath)

    # ── Integration Hooks ────────────────────────────────────────────

    async def after_plugin_generation(
        self, 
        plugin_name: str, 
        plugin_path: str,
        description: str,
    ) -> dict[str, Any]:
        """Hook called after a plugin is generated."""
        logger.info("git_manager_plugin_generated", plugin=plugin_name)
        
        # Update changelog
        await self.update_changelog(
            version="0.2.0",
            changes=[{
                "type": "added",
                "description": f"Auto-generated plugin: {plugin_name} - {description}",
            }],
        )
        
        # Commit the changes
        result = await self.commit_and_push(
            context=f"Auto-generate plugin: {plugin_name}"
        )
        
        return result
