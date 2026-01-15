"""Permission helper tests for project-centric access control."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, models, schemas
from echoroo.api.common.permissions import (
    can_edit_annotation_project,
    can_edit_dataset,
    can_view_annotation_project,
    can_view_dataset,
)


async def _create_project(
    session: AsyncSession,
    manager: schemas.SimpleUser,
    *,
    name: str = "visibility-test-project",
) -> models.Project:
    db_manager = await session.get(models.User, manager.id)
    assert db_manager is not None

    project = models.Project(
        project_id=f"proj-{uuid4().hex[:8]}",
        project_name=name,
    )
    session.add(project)
    await session.flush()

    membership = models.ProjectMember(
        project_id=project.project_id,
        user_id=db_manager.id,
        role=models.ProjectMemberRole.MANAGER,
    )
    session.add(membership)
    await session.flush()
    return project


async def _create_dataset(
    session: AsyncSession,
    audio_dir: Path,
    creator: schemas.SimpleUser,
    random_wav_factory: Callable[..., Path],
    *,
    project: models.Project,
    visibility: models.VisibilityLevel,
    name: str | None = None,
) -> schemas.Dataset:
    dataset_dir = audio_dir / f"dataset_{uuid4()}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    random_wav_factory(dataset_dir / "recording.wav")
    db_user = await session.get(models.User, creator.id)
    assert db_user is not None
    dataset = await api.datasets.create(
        session,
        name=name or f"dataset_{uuid4()}",
        description="visibility test dataset",
        dataset_dir=dataset_dir,
        audio_dir=audio_dir,
        user=db_user,
        visibility=visibility,
        project_id=project.project_id,
    )
    return dataset


async def _create_annotation_project(
    session: AsyncSession,
    creator: schemas.SimpleUser,
    *,
    dataset: schemas.Dataset,
) -> schemas.AnnotationProject:
    return await api.annotation_projects.create(
        session,
        name=f"annotation-project-{uuid4().hex[:8]}",
        description="visibility test annotation project",
        annotation_instructions=None,
        user=creator,
        dataset_id=dataset.id,
    )


async def test_can_view_dataset_restricted_requires_project_membership(
    session: AsyncSession,
    audio_dir: Path,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    random_wav_factory: Callable[..., Path],
) -> None:
    project = await _create_project(session, user)
    dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        project=project,
        visibility=models.VisibilityLevel.RESTRICTED,
    )

    other = await session.get(models.User, other_user.id)
    assert other is not None

    assert await can_view_dataset(session, dataset, other) is False

    session.add(
        models.ProjectMember(
            project_id=project.project_id,
            user_id=other.id,
            role=models.ProjectMemberRole.MEMBER,
        )
    )
    await session.flush()

    assert await can_view_dataset(session, dataset, other) is True


async def test_can_edit_dataset_requires_project_manager(
    session: AsyncSession,
    audio_dir: Path,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    superuser: schemas.SimpleUser,
    random_wav_factory: Callable[..., Path],
) -> None:
    project = await _create_project(session, user)
    dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        project=project,
        visibility=models.VisibilityLevel.RESTRICTED,
    )

    creator = await session.get(models.User, user.id)
    other = await session.get(models.User, other_user.id)
    super_user = await session.get(models.User, superuser.id)

    assert creator and other and super_user

    assert await can_edit_dataset(session, dataset, creator) is True
    assert await can_edit_dataset(session, dataset, super_user) is True
    assert await can_edit_dataset(session, dataset, other) is False

    session.add(
        models.ProjectMember(
            project_id=project.project_id,
            user_id=other.id,
            role=models.ProjectMemberRole.MEMBER,
        )
    )
    await session.flush()
    assert await can_edit_dataset(session, dataset, other) is False

    await session.execute(
        sa.update(models.ProjectMember)
        .where(
            models.ProjectMember.project_id == project.project_id,
            models.ProjectMember.user_id == other.id,
        )
        .values(role=models.ProjectMemberRole.MANAGER)
    )
    await session.flush()

    assert await can_edit_dataset(session, dataset, other) is True


async def test_can_view_annotation_project_respects_project_membership(
    session: AsyncSession,
    audio_dir: Path,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    random_wav_factory: Callable[..., Path],
) -> None:
    project = await _create_project(session, user)
    dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        project=project,
        visibility=models.VisibilityLevel.RESTRICTED,
    )
    annotation_project = await _create_annotation_project(
        session,
        user,
        dataset=dataset,
    )

    other = await session.get(models.User, other_user.id)
    assert other is not None

    assert await can_view_annotation_project(
        session, annotation_project, other
    ) is False

    session.add(
        models.ProjectMember(
            project_id=project.project_id,
            user_id=other.id,
            role=models.ProjectMemberRole.MEMBER,
        )
    )
    await session.flush()

    assert await can_view_annotation_project(
        session, annotation_project, other
    ) is True


async def test_can_edit_annotation_project_requires_manager(
    session: AsyncSession,
    audio_dir: Path,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    random_wav_factory: Callable[..., Path],
) -> None:
    project = await _create_project(session, user)
    dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        project=project,
        visibility=models.VisibilityLevel.RESTRICTED,
    )
    annotation_project = await _create_annotation_project(
        session,
        user,
        dataset=dataset,
    )

    creator = await session.get(models.User, user.id)
    other = await session.get(models.User, other_user.id)
    assert creator and other

    assert await can_edit_annotation_project(
        session, annotation_project, creator
    )
    assert not await can_edit_annotation_project(
        session, annotation_project, other
    )

    session.add(
        models.ProjectMember(
            project_id=project.project_id,
            user_id=other.id,
            role=models.ProjectMemberRole.MANAGER,
        )
    )
    await session.flush()

    assert await can_edit_annotation_project(
        session, annotation_project, other
    )
