"""Permission helpers for entity visibility control."""

from __future__ import annotations

from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.dataset import Dataset, VisibilityLevel
from echoroo.models.project import ProjectMember, ProjectMemberRole
from echoroo.models.user import User

__all__ = [
    "can_view_dataset",
    "can_edit_dataset",
    "can_delete_dataset",
    "can_manage_project_datasets",
    "can_manage_project",
    "can_view_project",
    "can_edit_project",
    "filter_datasets_by_access",
    "can_view_annotation_project",
    "can_edit_annotation_project",
    "can_delete_annotation_project",
    "can_manage_project_annotation_projects",
    "filter_annotation_projects_by_access",
]


async def _get_project_membership(
    session: AsyncSession,
    project_id: str,
    user: User | None,
) -> ProjectMember | None:
    if user is None:
        return None

    return await session.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )


async def _is_project_manager(
    session: AsyncSession,
    project_id: str,
    user: User | None,
) -> bool:
    if user is None:
        return False

    if user.is_superuser:
        return True

    membership = await _get_project_membership(session, project_id, user)
    return membership is not None and membership.role == ProjectMemberRole.MANAGER


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

    membership = await _get_project_membership(session, dataset.project_id, user)
    if membership is not None:
        return True

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

    if await _is_project_manager(session, dataset.project_id, user):
        return True

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

    # Project managers can delete datasets in their projects
    if await _is_project_manager(session, dataset.project_id, user):
        return True

    return False


async def can_manage_project_datasets(
    session: AsyncSession,
    project_id: str,
    user: User,
) -> bool:
    """Return True if the user can manage datasets under the given project."""

    return await can_manage_project(session, project_id, user)


async def can_manage_project(
    session: AsyncSession,
    project_id: str,
    user: User | None,
) -> bool:
    """Return True if the user can manage project-level resources."""

    if user is None:
        return False

    if user.is_superuser:
        return True

    membership = await _get_project_membership(session, project_id, user)
    return membership is not None and membership.role == ProjectMemberRole.MANAGER


def can_view_project(
    user: User | None,
    project_id: str,
) -> bool:
    """Return True if the user can view resources in the project.

    Note: This is a synchronous helper for simple checks. For more complex
    permission checks involving database queries, use the async can_view_* functions.
    """
    if user is None:
        return False

    if user.is_superuser:
        return True

    # For now, assume any authenticated user with project membership can view
    # This is a simplified check - actual membership verification happens in the async API layer
    return True


def can_edit_project(
    user: User | None,
    project_id: str,
) -> bool:
    """Return True if the user can edit resources in the project.

    Note: This is a synchronous helper for simple checks. For more complex
    permission checks involving database queries, use the async can_edit_* functions.
    """
    if user is None:
        return False

    if user.is_superuser:
        return True

    # For now, assume any authenticated user can edit
    # Actual fine-grained permission checks happen in the async API layer
    return True


async def filter_datasets_by_access(
    session: AsyncSession,
    user: User | None,
) -> list[ColumnElement[bool]]:
    """Return SQLAlchemy filter conditions limiting datasets accessible to the user."""
    if user is None:
        return [Dataset.visibility == VisibilityLevel.PUBLIC]

    if user.is_superuser:
        return []

    project_ids: Iterable[str] = (
        await session.scalars(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id
            )
        )
    ).all()

    conditions: list[ColumnElement[bool]] = [
        Dataset.visibility == VisibilityLevel.PUBLIC,
        Dataset.created_by_id == user.id,
    ]

    if project_ids:
        conditions.append(Dataset.project_id.in_(project_ids))

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

    membership = await _get_project_membership(session, project.project_id, user)
    if membership is not None:
        return True

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

    if await _is_project_manager(session, project.project_id, user):
        return True

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

    # Project managers can delete annotation projects in their projects
    if await _is_project_manager(session, project.project_id, user):
        return True

    return False


async def can_manage_project_annotation_projects(
    session: AsyncSession,
    project_id: str,
    user: User,
) -> bool:
    """Return True if the user can manage annotation projects under the project."""

    return await _is_project_manager(session, project_id, user)


async def filter_annotation_projects_by_access(
    session: AsyncSession,
    user: User | None,
) -> list[ColumnElement[bool]]:
    """Return filter conditions limiting projects accessible to the user."""
    if user is None:
        return [AnnotationProject.visibility == VisibilityLevel.PUBLIC]

    if user.is_superuser:
        return []

    project_ids: Iterable[str] = (
        await session.scalars(
            select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id
            )
        )
    ).all()

    conditions: list[ColumnElement[bool]] = [
        AnnotationProject.visibility == VisibilityLevel.PUBLIC,
        AnnotationProject.created_by_id == user.id,
    ]

    if project_ids:
        conditions.append(AnnotationProject.project_id.in_(project_ids))

    return [or_(*conditions)]
