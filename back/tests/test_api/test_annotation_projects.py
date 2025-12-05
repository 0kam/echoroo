"""Test suite for annotation project API."""

from pathlib import Path
from typing import Callable
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import api, exceptions, models, schemas


async def _add_project_member(
    session: AsyncSession,
    project_id: str,
    user_id,
    role: models.ProjectMemberRole,
) -> None:
    session.add(
        models.ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role=role,
        )
    )
    await session.flush()


async def test_created_annotation_is_stored_in_the_database(
    session: AsyncSession,
    user: schemas.SimpleUser,
    dataset: schemas.Dataset,
):
    """Test that an annotation project is stored in the database."""
    annotation_project = await api.annotation_projects.create(
        session,
        name="Test Annotation Project",
        description="A test annotation project.",
        user=user,
        dataset_id=dataset.id,
    )
    assert annotation_project.id is not None

    stmt = select(models.AnnotationProject).where(
        models.AnnotationProject.id == annotation_project.id
    )
    result = await session.execute(stmt)
    db_annotation_project = result.scalars().first()
    assert db_annotation_project is not None
    assert db_annotation_project.id == annotation_project.id
    assert db_annotation_project.name == annotation_project.name
    assert db_annotation_project.description == annotation_project.description


async def test_created_annotations_return_type_is_correct(
    session: AsyncSession,
    user: schemas.SimpleUser,
    dataset: schemas.Dataset,
):
    """Test that the return type of create_annotation_project is correct."""
    annotation_project = await api.annotation_projects.create(
        session,
        name="Test Annotation Project",
        description="A test annotation project.",
        user=user,
        dataset_id=dataset.id,
    )
    assert isinstance(annotation_project, schemas.AnnotationProject)


async def test_cannot_create_an_annotation_project_with_a_duplicate_name(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    user: schemas.SimpleUser,
    dataset: schemas.Dataset,
):
    """Test that an annotation project fails with a duplicate name."""
    with pytest.raises(exceptions.DuplicateObjectError):
        await api.annotation_projects.create(
            session,
            name=annotation_project.name,
            description="foo",
            user=user,
            dataset_id=dataset.id,
        )


async def test_cannot_create_an_annotation_project_with_duplicate_uuid(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    user: schemas.SimpleUser,
    dataset: schemas.Dataset,
):
    """Test that an annotation project fails with a duplicate uuid."""
    with pytest.raises(exceptions.DuplicateObjectError):
        await api.annotation_projects.create(
            session,
            name="foo",
            description="bar",
            uuid=annotation_project.uuid,
            user=user,
            dataset_id=dataset.id,
        )


async def test_can_create_a_project_with_a_given_uuid(
    session: AsyncSession,
    user: schemas.SimpleUser,
    dataset: schemas.Dataset,
):
    """Test that an annotation project can be created with a given uuid."""
    uuid = uuid4()
    data = await api.annotation_projects.create(
        session,
        name="Test Annotation Project",
        description="A test annotation project.",
        uuid=uuid,
        user=user,
        dataset_id=dataset.id,
    )
    annotation_project = await api.annotation_projects.get(
        session,
        data.uuid,
    )
    assert annotation_project.uuid == uuid


async def test_can_get_a_project_by_uuid(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
):
    """Test that an annotation project can be retrieved by its uuid."""
    retrieved_annotation_project = await api.annotation_projects.get(
        session,
        annotation_project.uuid,
    )
    assert retrieved_annotation_project == annotation_project


async def test_can_update_project_name(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    user: schemas.SimpleUser,
):
    """Test that an annotation project can be updated."""
    new_name = "New Name"
    updated_annotation_project = await api.annotation_projects.update(
        session,
        annotation_project,
        schemas.AnnotationProjectUpdate(
            name=new_name,
        ),
        user=user,
    )
    assert updated_annotation_project.name == new_name


async def test_can_update_project_description(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    user: schemas.SimpleUser,
):
    """Test that an annotation project can be updated."""
    new_description = "New Description"
    updated_annotation_project = await api.annotation_projects.update(
        session,
        annotation_project,
        schemas.AnnotationProjectUpdate(
            description=new_description,
        ),
        user=user,
    )
    assert updated_annotation_project.description == new_description


async def test_can_update_project_annotation_instructions(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    user: schemas.SimpleUser,
):
    """Test that an annotation project can be updated."""
    new_annotation_instructions = "New Annotation Instructions"
    updated_annotation_project = await api.annotation_projects.update(
        session,
        annotation_project,
        schemas.AnnotationProjectUpdate(
            annotation_instructions=new_annotation_instructions,
        ),
        user=user,
    )
    assert (
        updated_annotation_project.annotation_instructions
        == new_annotation_instructions
    )


async def test_update_modifies_database_values(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    user: schemas.SimpleUser,
):
    """Test that an annotation project can be updated."""
    new_name = "New Name"
    new_description = "New Description"
    new_annotation_instructions = "New Annotation Instructions"
    await api.annotation_projects.update(
        session,
        annotation_project,
        schemas.AnnotationProjectUpdate(
            name=new_name,
            description=new_description,
            annotation_instructions=new_annotation_instructions,
        ),
        user=user,
    )
    stmt = select(models.AnnotationProject).where(
        models.AnnotationProject.id == annotation_project.id
    )
    result = await session.execute(stmt)
    db_annotation_project = result.scalars().first()
    assert db_annotation_project is not None
    assert db_annotation_project.id == annotation_project.id
    assert db_annotation_project.name == new_name
    assert db_annotation_project.description == new_description
    assert (
        db_annotation_project.annotation_instructions
        == new_annotation_instructions
    )


async def test_update_annotation_project_metadata_requires_authorized_user(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    other_user: schemas.SimpleUser,
):
    """Ensure unauthorized users cannot change core annotation project metadata."""
    with pytest.raises(exceptions.PermissionDeniedError):
        await api.annotation_projects.update(
            session,
            annotation_project,
            schemas.AnnotationProjectUpdate(name="forbidden"),
            user=other_user,
        )
    with pytest.raises(exceptions.PermissionDeniedError):
        await api.annotation_projects.update(
            session,
            annotation_project,
            schemas.AnnotationProjectUpdate(description="forbidden"),
            user=other_user,
        )
    with pytest.raises(exceptions.PermissionDeniedError):
        await api.annotation_projects.update(
            session,
            annotation_project,
            schemas.AnnotationProjectUpdate(
                annotation_instructions="forbidden"
            ),
            user=other_user,
        )


async def test_project_manager_can_update_project_metadata(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    other_user: schemas.SimpleUser,
):
    """Ensure project managers can update annotation project metadata."""
    await _add_project_member(
        session,
        annotation_project.project_id,
        other_user.id,
        models.ProjectMemberRole.MANAGER,
    )

    updated = await api.annotation_projects.update(
        session,
        annotation_project,
        schemas.AnnotationProjectUpdate(name="managed_update"),
        user=other_user,
    )
    assert updated.name == "managed_update"


async def test_delete_removes_project_from_database(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    user: schemas.SimpleUser,
):
    """Test that an annotation project can be deleted."""
    await api.annotation_projects.delete(
        session,
        annotation_project,
        user=user,
    )
    stmt = select(models.AnnotationProject).where(
        models.AnnotationProject.id == annotation_project.id
    )
    result = await session.execute(stmt)
    db_annotation_project = result.scalars().first()
    assert db_annotation_project is None


async def test_delete_annotation_project_requires_owner(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    other_user: schemas.SimpleUser,
):
    """Ensure non-owners cannot delete annotation projects."""
    with pytest.raises(exceptions.PermissionDeniedError):
        await api.annotation_projects.delete(
            session,
            annotation_project,
            user=other_user,
        )


async def test_project_manager_cannot_delete_project(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    other_user: schemas.SimpleUser,
):
    """Ensure project managers cannot delete annotation projects they manage."""
    await _add_project_member(
        session,
        annotation_project.project_id,
        other_user.id,
        models.ProjectMemberRole.MANAGER,
    )

    with pytest.raises(exceptions.PermissionDeniedError):
        await api.annotation_projects.delete(
            session,
            annotation_project,
            user=other_user,
        )


async def test_add_tag_to_project(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    tag: schemas.Tag,
    user: schemas.SimpleUser,
):
    """Test that a tag can be added to an annotation project."""
    updated_annotation_project = await api.annotation_projects.add_tag(
        session,
        annotation_project,
        tag,
        user=user,
    )
    assert tag in updated_annotation_project.tags


async def test_add_tag_to_project_modifies_database(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    tag: schemas.Tag,
    user: schemas.SimpleUser,
):
    """Test that a tag can be added to an annotation project."""
    await api.annotation_projects.add_tag(
        session,
        annotation_project,
        tag,
        user=user,
    )
    stmt = select(models.AnnotationProjectTag).where(
        models.AnnotationProjectTag.annotation_project_id
        == annotation_project.id,
        models.AnnotationProjectTag.tag_id == tag.id,
    )
    result = await session.execute(stmt)
    db_annotation_project_tag = result.scalars().first()
    assert db_annotation_project_tag is not None
    assert (
        db_annotation_project_tag.annotation_project_id
        == annotation_project.id
    )
    assert db_annotation_project_tag.tag_id == tag.id


async def test_add_tag_to_project_does_not_add_duplicate(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    tag: schemas.Tag,
    user: schemas.SimpleUser,
):
    """Test that a tag cannot be added to an annotation project twice."""
    await api.annotation_projects.add_tag(
        session,
        annotation_project,
        tag,
        user=user,
    )
    with pytest.raises(exceptions.DuplicateObjectError):
        await api.annotation_projects.add_tag(
            session, annotation_project, tag, user=user
        )


async def test_remove_tag_from_project(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    tag: schemas.Tag,
    user: schemas.SimpleUser,
):
    """Test that a tag can be removed from an annotation project."""
    annotation_project = await api.annotation_projects.add_tag(
        session,
        annotation_project,
        tag,
        user=user,
    )
    updated_annotation_project = await api.annotation_projects.remove_tag(
        session,
        annotation_project,
        tag,
        user=user,
    )
    assert tag not in updated_annotation_project.tags


async def test_remove_tag_from_project_modifies_database(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    tag: schemas.Tag,
    user: schemas.SimpleUser,
):
    """Test that a tag can be removed from an annotation project."""
    annotation_project = await api.annotation_projects.add_tag(
        session,
        annotation_project,
        tag,
        user=user,
    )
    await api.annotation_projects.remove_tag(
        session,
        annotation_project,
        tag,
        user=user,
    )
    stmt = select(models.AnnotationProjectTag).where(
        models.AnnotationProjectTag.annotation_project_id
        == annotation_project.id,
        models.AnnotationProjectTag.tag_id == tag.id,
    )
    result = await session.execute(stmt)
    db_annotation_project_tag = result.scalars().first()
    assert db_annotation_project_tag is None


async def test_remove_tag_from_project_fails_if_tag_not_present(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    tag: schemas.Tag,
    user: schemas.SimpleUser,
):
    """Test that a tag removal fails gracefully when tag is absent."""
    with pytest.raises(exceptions.NotFoundError):
        await api.annotation_projects.remove_tag(
            session,
            annotation_project,
            tag,
            user=user,
        )


async def test_dataset_cant_be_deleted_if_used_in_an_annotation_project(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    dataset: schemas.Dataset,
    dataset_recording: schemas.Recording,
    user: schemas.SimpleUser,
):
    clip = await api.clips.create(
        session,
        dataset_recording,
        start_time=0,
        end_time=0.5,
    )

    await api.annotation_projects.add_task(
        session,
        annotation_project,
        clip,
        user=user,
    )

    await session.commit()

    with pytest.raises(IntegrityError):
        await api.datasets.delete(session, dataset, user=user)


async def test_can_get_base_dir_from_project_with_single_dataset(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    dataset: schemas.Dataset,
    dataset_recording: schemas.Recording,
    user: schemas.SimpleUser,
):
    clip = await api.clips.create(
        session,
        dataset_recording,
        start_time=0,
        end_time=0.5,
    )
    await api.annotation_projects.add_task(
        session,
        annotation_project,
        clip,
        user=user,
    )

    path = await api.annotation_projects.get_base_dir(
        session, annotation_project
    )
    assert path == dataset.audio_dir


async def test_can_get_base_dir_from_project_with_multiple_datasets(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
    random_wav_factory: Callable[..., Path],
    audio_dir: Path,
    user: schemas.SimpleUser,
):
    common_dir = audio_dir / "common"

    for i in range(2):
        dataset_name = f"dataset{i}"
        dataset_dir = common_dir / dataset_name
        dataset_dir.mkdir(parents=True, exist_ok=True)
        initial_file = dataset_dir / f"recording{i}.wav"
        random_wav_factory(initial_file)
        dataset = await api.datasets.create(
            session,
            name=dataset_name,
            description=dataset_name,
            dataset_dir=dataset_dir,
            audio_dir=audio_dir,
            user=user,
            visibility=models.VisibilityLevel.PUBLIC,
            project_id=annotation_project.project_id,
        )
        extra_file = dataset_dir / f"recording{i}_extra.wav"
        random_wav_factory(extra_file)
        dataset_recording = await api.datasets.add_file(
            session,
            dataset,
            path=extra_file,
            audio_dir=audio_dir,
        )
        clip = await api.clips.create(
            session,
            dataset_recording.recording,
            start_time=0,
            end_time=0.5,
        )
        await api.annotation_projects.add_task(
            session,
            annotation_project,
            clip,
            user=user,
        )

    path = await api.annotation_projects.get_base_dir(
        session,
        annotation_project,
    )
    assert path == common_dir.relative_to(audio_dir)
