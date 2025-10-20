"""Tests for visibility permissions and access helpers."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whombat import api, exceptions, models, schemas
from whombat.api.common.permissions import (
    can_edit_annotation_project,
    can_edit_dataset,
    can_view_annotation_project,
    can_view_dataset,
)


async def _create_dataset(
    session: AsyncSession,
    audio_dir: Path,
    creator: schemas.SimpleUser,
    random_wav_factory: Callable[..., Path],
    *,
    visibility: models.VisibilityLevel,
    owner_group_id: int | None = None,
) -> schemas.Dataset:
    dataset_dir = audio_dir / f"dataset_{uuid4()}"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    random_wav_factory(dataset_dir / "recording.wav")
    db_user = await session.get(models.User, creator.id)
    assert db_user is not None
    dataset = await api.datasets.create(
        session,
        name=f"dataset_{uuid4()}",
        description="visibility test dataset",
        dataset_dir=dataset_dir,
        audio_dir=audio_dir,
        user=db_user,
        visibility=visibility,
        owner_group_id=owner_group_id,
    )
    return dataset


async def _create_annotation_project(
    session: AsyncSession,
    creator: schemas.SimpleUser,
    *,
    visibility: models.VisibilityLevel,
    owner_group_id: int | None = None,
) -> schemas.AnnotationProject:
    project = await api.annotation_projects.create(
        session,
        name=f"project_{uuid4()}",
        description="visibility test project",
        annotation_instructions=None,
        user=creator,
        visibility=visibility,
        owner_group_id=owner_group_id,
    )
    return project


async def test_can_view_dataset_private_requires_creator_or_superuser(
    session: AsyncSession,
    audio_dir: Path,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    superuser: schemas.SimpleUser,
    random_wav_factory: Callable[..., Path],
) -> None:
    dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        visibility=models.VisibilityLevel.PRIVATE,
    )

    creator = await session.get(models.User, user.id)
    other = await session.get(models.User, other_user.id)
    super_user = await session.get(models.User, superuser.id)

    assert creator is not None
    assert other is not None
    assert super_user is not None

    assert await can_view_dataset(session, dataset, None) is False
    assert await can_view_dataset(session, dataset, other) is False
    assert await can_view_dataset(session, dataset, creator) is True
    assert await can_view_dataset(session, dataset, super_user) is True


async def test_can_view_dataset_restricted_requires_membership(
    session: AsyncSession,
    audio_dir: Path,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    group: schemas.Group,
    group_manager_membership: schemas.GroupMembership,
    random_wav_factory: Callable[..., Path],
) -> None:
    dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        visibility=models.VisibilityLevel.RESTRICTED,
        owner_group_id=group.id,
    )

    other = await session.get(models.User, other_user.id)
    assert other is not None

    # Not a member yet -> cannot view
    assert await can_view_dataset(session, dataset, other) is False

    await api.groups.add_membership(
        session,
        group.id,
        other.id,
        models.GroupRole.MEMBER,
    )
    await session.commit()

    assert await can_view_dataset(session, dataset, other) is True


async def test_can_edit_dataset_requires_manager(
    session: AsyncSession,
    audio_dir: Path,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    superuser: schemas.SimpleUser,
    group: schemas.Group,
    group_manager_membership: schemas.GroupMembership,
    random_wav_factory: Callable[..., Path],
) -> None:
    dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        visibility=models.VisibilityLevel.RESTRICTED,
        owner_group_id=group.id,
    )

    creator = await session.get(models.User, user.id)
    other = await session.get(models.User, other_user.id)
    super_user = await session.get(models.User, superuser.id)

    assert creator is not None
    assert other is not None
    assert super_user is not None

    assert await can_edit_dataset(session, dataset, creator) is True
    assert await can_edit_dataset(session, dataset, super_user) is True
    assert await can_edit_dataset(session, dataset, other) is False

    await api.groups.add_membership(
        session,
        group.id,
        other.id,
        models.GroupRole.MEMBER,
    )
    await session.commit()

    # Member without manager role still cannot edit
    assert await can_edit_dataset(session, dataset, other) is False

    await api.groups.update_membership_role(
        session,
        group.id,
        other.id,
        models.GroupRole.MANAGER,
    )
    await session.commit()

    assert await can_edit_dataset(session, dataset, other) is True


async def test_can_view_annotation_project_private(
    session: AsyncSession,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
) -> None:
    project = await _create_annotation_project(
        session,
        user,
        visibility=models.VisibilityLevel.PRIVATE,
    )

    creator = await session.get(models.User, user.id)
    other = await session.get(models.User, other_user.id)

    assert creator is not None
    assert other is not None

    assert await can_view_annotation_project(session, project, None) is False
    assert await can_view_annotation_project(session, project, other) is False
    assert await can_view_annotation_project(session, project, creator) is True


async def test_can_edit_annotation_project_manager_required(
    session: AsyncSession,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    group: schemas.Group,
    group_manager_membership: schemas.GroupMembership,
) -> None:
    project = await _create_annotation_project(
        session,
        user,
        visibility=models.VisibilityLevel.RESTRICTED,
        owner_group_id=group.id,
    )

    creator = await session.get(models.User, user.id)
    other = await session.get(models.User, other_user.id)

    assert creator is not None
    assert other is not None

    assert await can_edit_annotation_project(session, project, creator) is True
    assert await can_edit_annotation_project(session, project, other) is False

    await api.groups.add_membership(
        session,
        group.id,
        other.id,
        models.GroupRole.MEMBER,
    )
    await session.commit()
    assert await can_edit_annotation_project(session, project, other) is False

    await api.groups.update_membership_role(
        session,
        group.id,
        other.id,
        models.GroupRole.MANAGER,
    )
    await session.commit()

    assert await can_edit_annotation_project(session, project, other) is True


async def test_dataset_get_respects_visibility_rules(
    session: AsyncSession,
    audio_dir: Path,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    group: schemas.Group,
    group_manager_membership: schemas.GroupMembership,
    random_wav_factory: Callable[..., Path],
) -> None:
    public_dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        visibility=models.VisibilityLevel.PUBLIC,
    )
    private_dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        visibility=models.VisibilityLevel.PRIVATE,
    )
    restricted_dataset = await _create_dataset(
        session,
        audio_dir,
        user,
        random_wav_factory,
        visibility=models.VisibilityLevel.RESTRICTED,
        owner_group_id=group.id,
    )

    # Public dataset visible without authentication
    fetched = await api.datasets.get(session, public_dataset.uuid)
    assert fetched.uuid == public_dataset.uuid

    # Private dataset hidden from anonymous users
    with pytest.raises(exceptions.NotFoundError):
        await api.datasets.get(session, private_dataset.uuid)

    other = await session.get(models.User, other_user.id)
    assert other is not None

    with pytest.raises(exceptions.NotFoundError):
        await api.datasets.get(session, restricted_dataset.uuid, user=other)

    await api.groups.add_membership(
        session,
        group.id,
        other.id,
        models.GroupRole.MEMBER,
    )
    await session.commit()

    allowed = await api.datasets.get(
        session,
        restricted_dataset.uuid,
        user=other,
    )
    assert allowed.uuid == restricted_dataset.uuid


async def test_annotation_project_get_respects_visibility(
    session: AsyncSession,
    user: schemas.SimpleUser,
    other_user: schemas.SimpleUser,
    group: schemas.Group,
    group_manager_membership: schemas.GroupMembership,
) -> None:
    public_project = await _create_annotation_project(
        session,
        user,
        visibility=models.VisibilityLevel.PUBLIC,
    )
    private_project = await _create_annotation_project(
        session,
        user,
        visibility=models.VisibilityLevel.PRIVATE,
    )
    restricted_project = await _create_annotation_project(
        session,
        user,
        visibility=models.VisibilityLevel.RESTRICTED,
        owner_group_id=group.id,
    )

    fetched = await api.annotation_projects.get(
        session,
        public_project.uuid,
    )
    assert fetched.uuid == public_project.uuid

    with pytest.raises(exceptions.NotFoundError):
        await api.annotation_projects.get(
            session,
            private_project.uuid,
        )

    other = await session.get(models.User, other_user.id)
    assert other is not None

    with pytest.raises(exceptions.NotFoundError):
        await api.annotation_projects.get(
            session,
            restricted_project.uuid,
            user=other,
        )

    await api.groups.add_membership(
        session,
        group.id,
        other.id,
        models.GroupRole.MEMBER,
    )
    await session.commit()

    allowed = await api.annotation_projects.get(
        session,
        restricted_project.uuid,
        user=other,
    )
    assert allowed.uuid == restricted_project.uuid
