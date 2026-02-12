"""Git auto-commit service - automatically commits and pushes changes.

This module provides automatic git commit and push functionality that runs
in the background, ensuring changes are never lost.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Optional

from koda2.config import get_settings
from koda2.logging_config import get_logger

logger = get_logger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent.parent


class GitAutoCommitService:
    """Background service that automatically commits and pushes changes.
    
    This service periodically checks for uncommitted changes and:
    1. Stages all changes
    2. Generates a commit message
    3. Commits
    4. Pushes to remote (if configured)
    
    It can also be triggered manually for immediate commit.
    """
    
    def __init__(self, interval: int = 300) -> None:
        """Initialize the auto-commit service.
        
        Args:
            interval: Check interval in seconds (default: 5 minutes)
        """
        self._interval = interval
        self._settings = get_settings()
        self._enabled = self._settings.git_auto_commit
        self._auto_push = self._settings.git_auto_push
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the auto-commit background task."""
        if not self._enabled:
            logger.info("git_auto_commit_disabled")
            return
        
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._commit_loop())
        logger.info("git_auto_commit_service_started", interval=self._interval)
    
    async def stop(self) -> None:
        """Stop the auto-commit background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        # Do a final commit before stopping
        if self._enabled:
            await self.commit_now("Auto-commit before shutdown")
        
        logger.info("git_auto_commit_service_stopped")
    
    async def _commit_loop(self) -> None:
        """Main loop that periodically checks for changes."""
        while self._running:
            try:
                await self._check_and_commit()
            except Exception as exc:
                logger.error("git_auto_commit_loop_error", error=str(exc))
            
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break
    
    async def _check_and_commit(self) -> None:
        """Check for changes and commit if needed."""
        from koda2.modules.git_manager.service import GitManagerService
        
        git = GitManagerService()
        
        if not await git.is_repo():
            return
        
        if not await git.has_changes():
            return
        
        logger.info("git_auto_commit_detected_changes")
        result = await git.auto_commit_and_push(
            context="Auto-commit: periodic background commit"
        )
        
        if result["committed"]:
            logger.info(
                "git_auto_commit_success",
                message=result.get("message", ""),
                pushed=result.get("pushed", False),
            )
        else:
            logger.debug("git_auto_commit_no_changes_or_failed", reason=result.get("reason"))
    
    async def commit_now(self, message: Optional[str] = None) -> dict[str, Any]:
        """Immediately commit and push any pending changes.
        
        Args:
            message: Optional commit message (auto-generated if not provided)
            
        Returns:
            Dict with commit results
        """
        from koda2.modules.git_manager.service import GitManagerService
        
        git = GitManagerService()
        result = await git.auto_commit_and_push(context=message)
        
        if result["committed"]:
            logger.info(
                "git_manual_commit_success",
                message=result.get("message", ""),
                pushed=result.get("pushed", False),
            )
        
        return result
    
    async def status(self) -> dict[str, Any]:
        """Get current status of the auto-commit service."""
        from koda2.modules.git_manager.service import GitManagerService
        
        git = GitManagerService()
        
        return {
            "enabled": self._enabled,
            "running": self._running,
            "interval": self._interval,
            "auto_push": self._auto_push,
            "is_repo": await git.is_repo(),
            "has_changes": await git.has_changes() if await git.is_repo() else False,
        }


# Global instance
_auto_commit_service: Optional[GitAutoCommitService] = None


def get_auto_commit_service() -> GitAutoCommitService:
    """Get or create the global auto-commit service instance."""
    global _auto_commit_service
    if _auto_commit_service is None:
        _auto_commit_service = GitAutoCommitService()
    return _auto_commit_service


async def start_auto_commit() -> None:
    """Convenience function to start the global auto-commit service."""
    service = get_auto_commit_service()
    await service.start()


async def stop_auto_commit() -> None:
    """Convenience function to stop the global auto-commit service."""
    service = get_auto_commit_service()
    await service.stop()


async def commit_now(message: Optional[str] = None) -> dict[str, Any]:
    """Convenience function to immediately commit changes."""
    service = get_auto_commit_service()
    return await service.commit_now(message)
