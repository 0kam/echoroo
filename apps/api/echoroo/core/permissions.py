"""Permission checking utilities for role-based access control (RBAC).

This module provides decorators and helper functions to check user permissions
on projects based on their role (admin, member, viewer).
"""

from enum import Enum
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectRole
from echoroo.models.project import Project, ProjectMember


class Permission(str, Enum):
    """Permission types for project access control.

    Attributes:
        VIEW_PROJECT: Can view project details and data (all roles)
        EDIT_PROJECT: Can edit project data (member and admin)
        MANAGE_MEMBERS: Can add/remove members and change roles (admin only)
        DELETE_PROJECT: Can delete the project (owner only)
    """

    VIEW_PROJECT = "view_project"
    EDIT_PROJECT = "edit_project"
    MANAGE_MEMBERS = "manage_members"
    DELETE_PROJECT = "delete_project"


# Role to permissions mapping
ROLE_PERMISSIONS = {
    ProjectRole.VIEWER: {
        Permission.VIEW_PROJECT,
    },
    ProjectRole.MEMBER: {
        Permission.VIEW_PROJECT,
        Permission.EDIT_PROJECT,
    },
    ProjectRole.ADMIN: {
        Permission.VIEW_PROJECT,
        Permission.EDIT_PROJECT,
        Permission.MANAGE_MEMBERS,
    },
}


async def get_user_project_role(
    db: AsyncSession,
    user_id: UUID,
    project_id: UUID,
) -> ProjectRole | None:
    """Get user's role in a project.

    Args:
        db: Database session
        user_id: User's UUID
        project_id: Project's UUID

    Returns:
        User's ProjectRole if they are a member, None otherwise.
        Note: Owner is not in ProjectMember table, check separately.
    """
    result = await db.execute(
        select(ProjectMember.role).where(
            ProjectMember.user_id == user_id,
            ProjectMember.project_id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def is_project_owner(
    db: AsyncSession,
    user_id: UUID,
    project_id: UUID,
) -> bool:
    """Check if user is the project owner.

    Args:
        db: Database session
        user_id: User's UUID
        project_id: Project's UUID

    Returns:
        True if user is the project owner
    """
    result = await db.execute(
        select(Project.owner_id).where(Project.id == project_id)
    )
    owner_id = result.scalar_one_or_none()
    return owner_id == user_id if owner_id else False


async def check_project_permission(
    db: AsyncSession,
    user_id: UUID,
    project_id: UUID,
    permission: Permission,
) -> bool:
    """Check if user has required permission on project.

    Permission hierarchy:
    - Owner: All permissions (VIEW, EDIT, MANAGE_MEMBERS, DELETE)
    - Admin: VIEW, EDIT, MANAGE_MEMBERS
    - Member: VIEW, EDIT
    - Viewer: VIEW only

    Args:
        db: Database session
        user_id: User's UUID
        project_id: Project's UUID
        permission: Required permission

    Returns:
        True if user has the required permission
    """
    # Check if user is owner (has all permissions)
    if await is_project_owner(db, user_id, project_id):
        return True

    # Special case: DELETE_PROJECT is owner-only
    if permission == Permission.DELETE_PROJECT:
        return False

    # Get user's role in the project
    role = await get_user_project_role(db, user_id, project_id)
    if not role:
        return False

    # Check if role has the required permission
    role_perms = ROLE_PERMISSIONS.get(role, set())
    return permission in role_perms
