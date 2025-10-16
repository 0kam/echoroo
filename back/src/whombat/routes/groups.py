"""REST API routes for managing user groups and memberships."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from whombat import api, schemas
from whombat.api.groups import (
    add_membership,
    list_groups_for_user,
    remove_membership,
    update_membership_role,
)
from whombat.models.group import Group, GroupRole
from whombat.routes.dependencies import Session, get_current_user_dependency
from whombat.routes.dependencies.groups import require_admin, require_group_manager
from whombat.routes.dependencies.settings import WhombatSettings
from whombat.routes.types import Limit, Offset

__all__ = ["get_groups_router"]


def get_groups_router(settings: WhombatSettings) -> APIRouter:
    router = APIRouter()

    current_user_dep = get_current_user_dependency(settings)
    admin_required_dep = require_admin(settings)
    group_manager_dep = require_group_manager(settings)

    @router.get(
        "",
        response_model=schemas.Page[schemas.Group],
    )
    @router.get(
        "/",
        response_model=schemas.Page[schemas.Group],
    )
    async def list_groups(
        session: Session,
        _: Any = Depends(admin_required_dep),
        limit: Limit = 50,
        offset: Offset = 0,
    ):
        """List all groups (admin only)."""

        items, total = await api.groups.get_many(
            session,
            limit=limit,
            offset=offset,
            sort_by="name",
        )
        return schemas.Page(
            items=items,
            total=total,
            offset=offset,
            limit=limit,
        )

    @router.post(
        "",
        response_model=schemas.Group,
        status_code=status.HTTP_201_CREATED,
    )
    @router.post(
        "/",
        response_model=schemas.Group,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_group(
        session: Session,
        payload: schemas.GroupCreate,
        admin_user: Any = Depends(admin_required_dep),
    ):
        """Create a new group and add the creator as a manager."""

        group = await api.groups.create_from_data(
            session,
            payload,
            created_by_id=admin_user.id,
        )
        await add_membership(
            session,
            group.id,
            admin_user.id,
            GroupRole.MANAGER,
        )
        await session.commit()
        return group

    @router.patch(
        "/{group_id}",
        response_model=schemas.Group,
    )
    async def update_group(
        session: Session,
        group_id: int,
        data: schemas.GroupUpdate,
        _: Any = Depends(admin_required_dep),
    ):
        """Update an existing group."""

        group = await api.groups.get(session, group_id)
        updated = await api.groups.update(session, group, data)
        await session.commit()
        return updated

    @router.delete(
        "/{group_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_group(
        session: Session,
        group_id: int,
        _: Any = Depends(admin_required_dep),
    ):
        """Delete a group."""

        group = await api.groups.get(session, group_id)
        await api.groups.delete(session, group)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/me",
        response_model=list[schemas.GroupDetail],
    )
    async def list_my_groups(
        session: Session,
        user: Any = Depends(current_user_dep),
    ):
        """List groups the current user belongs to."""

        return await list_groups_for_user(session, user.id)

    @router.get(
        "/{group_id}",
        response_model=schemas.GroupDetail,
    )
    async def get_group_detail(
        session: Session,
        group: Group = Depends(group_manager_dep),
    ):
        """Retrieve detail for a single group."""

        return await api.groups.get_detail(session, group.id)

    @router.post(
        "/{group_id}/members",
        response_model=schemas.GroupMembership,
        status_code=status.HTTP_201_CREATED,
    )
    async def add_group_member(
        session: Session,
        data: schemas.GroupMembershipCreate,
        group: Group = Depends(group_manager_dep),
    ):
        """Add a new member to the group."""

        membership = await add_membership(
            session,
            group.id,
            data.user_id,
            data.role,
        )
        await session.commit()
        return membership

    @router.patch(
        "/{group_id}/members/{user_id}",
        response_model=schemas.GroupMembership,
    )
    async def update_group_member(
        session: Session,
        user_id: UUID,
        data: schemas.GroupMembershipUpdate,
        group: Group = Depends(group_manager_dep),
    ):
        """Update a member's role within the group."""

        membership = await update_membership_role(
            session,
            group.id,
            user_id,
            data.role,
        )
        await session.commit()
        return membership

    @router.delete(
        "/{group_id}/members/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_group_member(
        session: Session,
        user_id: UUID,
        group: Group = Depends(group_manager_dep),
    ):
        """Remove a user from the group."""

        await remove_membership(session, group.id, user_id)
        await session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
