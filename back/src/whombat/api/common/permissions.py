"""Permission helpers for entity visibility control."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from whombat.models.annotation_project import AnnotationProject
from whombat.models.dataset import Dataset, VisibilityLevel
from whombat.models.group import GroupMembership, GroupRole
from whombat.models.user import User

__all__ = [
    "can_view_dataset",
    "can_edit_dataset",
    "can_delete_dataset",
    "can_manage_restricted_dataset",
    "filter_datasets_by_access",
    "can_view_annotation_project",
    "can_edit_annotation_project",
    "can_delete_annotation_project",
    "can_manage_restricted_annotation_project",
    "filter_annotation_projects_by_access",
]


async def _get_membership(
    session: AsyncSession,
    group_id: int,
    user: User | None,
) -> GroupMembership | None:
    if user is None:
        return None

    return await session.scalar(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id,
            GroupMembership.user_id == user.id,
        )
    )


async def can_view_dataset(
    session: AsyncSession,
    dataset: Dataset,
    user: User | None,
) -> bool:
    """Return True if the user can view the dataset."""
    if dataset.visibility == VisibilityLevel.PUBLIC:
        return True

    if user is None:
        return False

    if user.is_superuser or dataset.created_by_id == user.id:
        return True

    if dataset.visibility == VisibilityLevel.RESTRICTED and dataset.owner_group_id:
        membership = await _get_membership(session, dataset.owner_group_id, user)
        return membership is not None

    return False


async def can_edit_dataset(
    session: AsyncSession,
    dataset: Dataset,
    user: User | None,
) -> bool:
    """Return True if the user can edit the dataset."""
    if user is None:
        return False

    if user.is_superuser or dataset.created_by_id == user.id:
        return True

    if dataset.visibility == VisibilityLevel.RESTRICTED and dataset.owner_group_id:
        membership = await _get_membership(session, dataset.owner_group_id, user)
        return membership is not None and membership.role == GroupRole.MANAGER

    return False


async def can_delete_dataset(
    session: AsyncSession,
    dataset: Dataset,
    user: User | None,
) -> bool:
    """Return True if the user can delete the dataset."""
    if user is None:
        return False

    if user.is_superuser or dataset.created_by_id == user.id:
        return True

    return False


async def can_manage_restricted_dataset(
    session: AsyncSession,
    group_id: int,
    user: User,
) -> bool:
    """Return True if the user can create/update restricted datasets for the group."""
    if user.is_superuser:
        return True

    membership = await _get_membership(session, group_id, user)
    return membership is not None and membership.role == GroupRole.MANAGER


async def filter_datasets_by_access(
    session: AsyncSession,
    user: User | None,
) -> list[ColumnElement[bool]]:
    """Return SQLAlchemy filter conditions limiting datasets accessible to the user."""
    if user is None:
        return [Dataset.visibility == VisibilityLevel.PUBLIC]

    if user.is_superuser:
        return []

    group_ids: Iterable[int] = (
        await session.scalars(
            select(GroupMembership.group_id).where(
                GroupMembership.user_id == user.id
            )
        )
    ).all()

    conditions: list[ColumnElement[bool]] = [
        Dataset.visibility == VisibilityLevel.PUBLIC,
        Dataset.created_by_id == user.id,
    ]

    if group_ids:
        conditions.append(
            and_(
                Dataset.visibility == VisibilityLevel.RESTRICTED,
                Dataset.owner_group_id.in_(group_ids),
            )
        )

    return [or_(*conditions)]


async def can_view_annotation_project(
    session: AsyncSession,
    project: AnnotationProject,
    user: User | None,
) -> bool:
    """Return True if the user can view the annotation project."""
    if project.visibility == VisibilityLevel.PUBLIC:
        return True

    if user is None:
        return False

    if user.is_superuser or project.created_by_id == user.id:
        return True

    if project.visibility == VisibilityLevel.RESTRICTED and project.owner_group_id:
        membership = await _get_membership(session, project.owner_group_id, user)
        return membership is not None

    return False


async def can_edit_annotation_project(
    session: AsyncSession,
    project: AnnotationProject,
    user: User | None,
) -> bool:
    """Return True if the user can edit the annotation project."""
    if user is None:
        return False

    if user.is_superuser or project.created_by_id == user.id:
        return True

    if project.visibility == VisibilityLevel.RESTRICTED and project.owner_group_id:
        membership = await _get_membership(session, project.owner_group_id, user)
        return membership is not None and membership.role == GroupRole.MANAGER

    return False


async def can_delete_annotation_project(
    session: AsyncSession,
    project: AnnotationProject,
    user: User | None,
) -> bool:
    """Return True if the user can delete the annotation project."""
    if user is None:
        return False

    if user.is_superuser or project.created_by_id == user.id:
        return True

    return False


async def can_manage_restricted_annotation_project(
    session: AsyncSession,
    group_id: int,
    user: User,
) -> bool:
    """Return True if the user can create/update restricted projects for the group."""
    if user.is_superuser:
        return True

    membership = await _get_membership(session, group_id, user)
    return membership is not None and membership.role == GroupRole.MANAGER


async def filter_annotation_projects_by_access(
    session: AsyncSession,
    user: User | None,
) -> list[ColumnElement[bool]]:
    """Return filter conditions limiting projects accessible to the user."""
    if user is None:
        return [AnnotationProject.visibility == VisibilityLevel.PUBLIC]

    if user.is_superuser:
        return []

    group_ids: Iterable[int] = (
        await session.scalars(
            select(GroupMembership.group_id).where(
                GroupMembership.user_id == user.id
            )
        )
    ).all()

    conditions: list[ColumnElement[bool]] = [
        AnnotationProject.visibility == VisibilityLevel.PUBLIC,
        AnnotationProject.created_by_id == user.id,
    ]

    if group_ids:
        conditions.append(
            and_(
                AnnotationProject.visibility == VisibilityLevel.RESTRICTED,
                AnnotationProject.owner_group_id.in_(group_ids),
            )
        )

    return [or_(*conditions)]
