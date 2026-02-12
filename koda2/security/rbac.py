"""Role-based access control (RBAC) for Koda2."""

from __future__ import annotations

from enum import StrEnum
from typing import Optional

from pydantic import BaseModel

from koda2.logging_config import get_logger

logger = get_logger(__name__)


class Role(StrEnum):
    """System roles ordered by privilege level."""

    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"


class Permission(StrEnum):
    """Granular permissions for system actions."""

    READ_CALENDAR = "read_calendar"
    WRITE_CALENDAR = "write_calendar"
    READ_EMAIL = "read_email"
    SEND_EMAIL = "send_email"
    MANAGE_TASKS = "manage_tasks"
    GENERATE_DOCUMENTS = "generate_documents"
    GENERATE_IMAGES = "generate_images"
    MANAGE_SETTINGS = "manage_settings"
    SYSTEM_ACCESS = "system_access"
    SELF_IMPROVE = "self_improve"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.USER: {
        Permission.READ_CALENDAR,
        Permission.WRITE_CALENDAR,
        Permission.READ_EMAIL,
        Permission.SEND_EMAIL,
        Permission.MANAGE_TASKS,
        Permission.GENERATE_DOCUMENTS,
        Permission.GENERATE_IMAGES,
    },
    Role.VIEWER: {
        Permission.READ_CALENDAR,
        Permission.READ_EMAIL,
    },
}


class UserIdentity(BaseModel):
    """Represents an authenticated user with their role."""

    user_id: str
    role: Role = Role.USER
    display_name: str = ""

    def has_permission(self, permission: Permission) -> bool:
        """Check if the user's role grants the given permission."""
        return permission in ROLE_PERMISSIONS.get(self.role, set())

    def require_permission(self, permission: Permission) -> None:
        """Raise if the user lacks the required permission."""
        if not self.has_permission(permission):
            logger.warning(
                "permission_denied",
                user_id=self.user_id,
                role=self.role,
                permission=permission,
            )
            raise PermissionError(
                f"User '{self.user_id}' with role '{self.role}' lacks permission '{permission}'"
            )
