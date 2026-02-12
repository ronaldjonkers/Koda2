"""Git management module for auto-commit and documentation updates."""

from koda2.modules.git_manager.auto_commit import (
    GitAutoCommitService,
    commit_now,
    get_auto_commit_service,
    start_auto_commit,
    stop_auto_commit,
)
from koda2.modules.git_manager.service import GitManagerService

__all__ = [
    "GitManagerService",
    "GitAutoCommitService",
    "start_auto_commit",
    "stop_auto_commit",
    "commit_now",
    "get_auto_commit_service",
]
