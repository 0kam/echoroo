"""Group related dependency helpers."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import and_, select

from whombat.models.group import Group, GroupMembership, GroupRole
from whombat.routes.dependencies.auth import (
    get_current_admin_dependency,
    get_current_user_dependency,
)
from whombat.routes.dependencies.session import Session
from whombat.routes.dependencies.settings import WhombatSettings

__all__ = [
    "get_group_dependency",
    "require_admin",
    "require_group_manager",
]


async def get_group_dependency(
    session: Session,
    group_id: int,
) -> Group:
    """Retrieve a group by id or raise 404."""

    stmt = select(Group).where(Group.id == group_id)
    result = await session.execute(stmt)
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


def require_admin(settings: WhombatSettings):
    """Return a dependency that requires the current user to be an admin."""

    return get_current_admin_dependency(settings)


def require_group_manager(settings: WhombatSettings):
    """Return a dependency that ensures the user manages the given group."""

    current_user = get_current_user_dependency(settings)

    async def dependency(
        session: Session,
        group: Group = Depends(get_group_dependency),
        user = Depends(current_user),
    ) -> Group:
        if user.is_superuser:
            return group

        stmt = select(GroupMembership).where(
            and_(
                GroupMembership.group_id == group.id,
                GroupMembership.user_id == user.id,
            )
        )
        result = await session.execute(stmt)
        membership = result.scalar_one_or_none()
        if membership is None or membership.role != GroupRole.MANAGER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this group",
            )
        return group

    return dependency
