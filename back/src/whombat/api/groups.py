"""API helpers for managing user groups and memberships."""

from __future__ import annotations

from typing import Sequence
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whombat import exceptions, models, schemas
from whombat.api.common import BaseAPI

__all__ = [
    "GroupAPI",
    "add_membership",
    "groups",
    "list_groups_for_user",
    "remove_membership",
    "update_membership_role",
]


class GroupAPI(
    BaseAPI[
        int,
        models.Group,
        schemas.Group,
        schemas.GroupCreate,
        schemas.GroupUpdate,
    ]
):
    """API wrapper for group level operations."""

    _model = models.Group
    _schema = schemas.Group

    def _get_pk_condition(self, pk: int):
        return models.Group.id == pk

    def _get_pk_from_obj(self, obj: schemas.Group) -> int:
        return obj.id

    def _get_key_column(self):
        return models.Group.name

    def _key_fn(self, obj: dict) -> str:
        return obj["name"]

    async def get_detail(
        self,
        session: AsyncSession,
        pk: int,
    ) -> schemas.GroupDetail:
        """Fetch a group with membership details eagerly loaded."""

        stmt = (
            select(models.Group)
            .where(models.Group.id == pk)
            .options(
                selectinload(models.Group.memberships).selectinload(
                    models.GroupMembership.user
                )
            )
        )
        result = await session.execute(stmt)
        group = result.scalar_one_or_none()
        if group is None:
            raise exceptions.NotFoundError("Group not found")

        return schemas.GroupDetail.model_validate(group)

    async def add_membership(
        self,
        session: AsyncSession,
        group_id: int,
        user_id: UUID,
        role: models.GroupRole,
    ) -> schemas.GroupMembership:
        """Add a user to a group."""
        return await add_membership(session, group_id, user_id, role)

    async def update_membership_role(
        self,
        session: AsyncSession,
        group_id: int,
        user_id: UUID,
        role: models.GroupRole,
    ) -> schemas.GroupMembership:
        """Update the role of an existing membership."""
        return await update_membership_role(session, group_id, user_id, role)

    async def remove_membership(
        self,
        session: AsyncSession,
        group_id: int,
        user_id: UUID,
    ) -> None:
        """Remove a user from a group."""
        return await remove_membership(session, group_id, user_id)


async def list_groups_for_user(
    session: AsyncSession,
    user_id: UUID,
) -> Sequence[schemas.GroupDetail]:
    """Return the groups a user belongs to, with memberships eager loaded."""

    stmt = (
        select(models.Group)
        .join(models.GroupMembership)
        .where(models.GroupMembership.user_id == user_id)
        .options(
            selectinload(models.Group.memberships).selectinload(
                models.GroupMembership.user
            )
        )
        .order_by(models.Group.name)
    )
    result = await session.execute(stmt)
    groups = result.scalars().unique().all()
    return [schemas.GroupDetail.model_validate(group) for group in groups]


async def add_membership(
    session: AsyncSession,
    group_id: int,
    user_id: UUID,
    role: models.GroupRole,
) -> schemas.GroupMembership:
    """Add a user to a group."""

    stmt = select(models.GroupMembership).where(
        and_(
            models.GroupMembership.group_id == group_id,
            models.GroupMembership.user_id == user_id,
        )
    )
    existing = await session.execute(stmt)
    membership = existing.scalar_one_or_none()
    if membership is not None:
        raise exceptions.DuplicateObjectError(
            "User already belongs to this group"
        )

    membership = models.GroupMembership(
        group_id=group_id,
        user_id=user_id,
        role=role,
    )
    session.add(membership)
    await session.flush()
    await session.refresh(membership, ["user"])
    return schemas.GroupMembership.model_validate(membership)


async def update_membership_role(
    session: AsyncSession,
    group_id: int,
    user_id: UUID,
    role: models.GroupRole,
) -> schemas.GroupMembership:
    """Update the role of an existing membership."""

    stmt = select(models.GroupMembership).where(
        and_(
            models.GroupMembership.group_id == group_id,
            models.GroupMembership.user_id == user_id,
        )
    )
    result = await session.execute(stmt)
    membership = result.scalar_one_or_none()
    if membership is None:
        raise exceptions.NotFoundError("Membership not found")

    membership.role = role
    await session.flush()
    await session.refresh(membership, ["user"])
    return schemas.GroupMembership.model_validate(membership)


async def remove_membership(
    session: AsyncSession,
    group_id: int,
    user_id: UUID,
) -> None:
    """Remove a user from a group."""

    stmt = select(models.GroupMembership).where(
        and_(
            models.GroupMembership.group_id == group_id,
            models.GroupMembership.user_id == user_id,
        )
    )
    result = await session.execute(stmt)
    membership = result.scalar_one_or_none()
    if membership is None:
        raise exceptions.NotFoundError("Membership not found")

    await session.delete(membership)


groups = GroupAPI()
