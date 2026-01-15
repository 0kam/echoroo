import json
from pathlib import Path
from typing import Any, BinaryIO

import sqlalchemy as sa
from soundevent.io import aoef
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import exceptions, models
from echoroo.api import common
from echoroo.api.io.aoef.features import get_feature_names
from echoroo.api.io.aoef.recordings import import_recordings
from echoroo.api.io.aoef.tags import import_tags
from echoroo.api.io.aoef.users import import_users
from echoroo.api.users import ensure_system_user


def _extract_metadata(payload: Any) -> dict[str, Any]:
    """Best-effort extraction of project-related metadata."""
    if isinstance(payload, dict):
        return payload
    return {}


async def _resolve_project(
    session: AsyncSession,
    *,
    project_meta: dict[str, Any],
    fallback_name: str,
) -> models.Project:
    """Fetch or create a project based on AOEF metadata."""
    project_id = project_meta.get("project_id") or project_meta.get("id")
    project_name = project_meta.get("project_name") or project_meta.get("name")
    project_url = project_meta.get("url")
    project_description = project_meta.get("description")
    project_target_taxa = project_meta.get("target_taxa")
    admin_name = project_meta.get("admin_name")
    admin_email = project_meta.get("admin_email")

    if project_id:
        project = await session.get(models.Project, project_id)
        if project is not None:
            return project

    if project_name:
        result = await session.execute(
            select(models.Project).where(
                models.Project.project_name == project_name
            )
        )
        project = result.scalar_one_or_none()
        if project is not None:
            return project

    project_kwargs: dict[str, Any] = {
        "project_name": project_name or fallback_name,
        "url": project_url,
        "description": project_description,
        "target_taxa": project_target_taxa,
        "admin_name": admin_name,
        "admin_email": admin_email,
    }
    if project_id:
        project_kwargs["project_id"] = project_id

    project = await common.create_object(session, models.Project, **project_kwargs)
    await session.flush()
    return project


async def _ensure_project_membership(
    session: AsyncSession,
    project_id: str,
    user_id: Any,
    role: models.ProjectMemberRole = models.ProjectMemberRole.MANAGER,
) -> None:
    if user_id is None:
        return
    await session.execute(
        sa.text(
            """
            INSERT INTO project_member (project_id, user_id, role, created_on)
            VALUES (:project_id, :user_id, :role, CURRENT_TIMESTAMP)
            ON CONFLICT (project_id, user_id) DO NOTHING
            """
        ),
        {
            "project_id": project_id,
            "user_id": str(user_id),
            "role": role.value,
        },
    )


async def import_dataset(
    session: AsyncSession,
    src: Path | BinaryIO | str,
    dataset_dir: Path,
    audio_dir: Path,
) -> models.Dataset:
    if isinstance(src, (Path, str)):
        with open(src, "r") as file:
            obj = json.load(file)
    else:
        obj = json.loads(src.read())

    if not isinstance(obj, dict):
        raise TypeError(f"Expected dict, got {type(obj)}")

    if "data" not in obj:
        raise ValueError("Missing 'data' key")

    if not dataset_dir.is_absolute():
        # Assume relative to audio_dir
        dataset_dir = audio_dir / dataset_dir

    if not dataset_dir.is_relative_to(audio_dir):
        raise ValueError(
            f"Dataset directory {dataset_dir} is not relative "
            f"to audio directory {audio_dir}"
        )

    data = obj["data"]
    dataset_object = aoef.DatasetObject.model_validate(data)

    tags = await import_tags(session, dataset_object.tags or [])

    users = await import_users(session, dataset_object.users or [])

    feature_names = await get_feature_names(
        session,
        dataset_object,
    )

    recordings = await import_recordings(
        session,
        dataset_object.recordings or [],
        tags=tags,
        users=users,
        feature_names=feature_names,
        audio_dir=dataset_dir,
        base_audio_dir=audio_dir,
    )

    meta_container = _extract_metadata(getattr(dataset_object, "metadata", {}))
    project_meta = _extract_metadata(
        meta_container.get("project") or meta_container
    )
    project = await _resolve_project(
        session,
        project_meta=project_meta,
        fallback_name=f"{dataset_object.name or 'Imported'} Project",
    )

    raw_visibility = getattr(dataset_object, "visibility", None) or project_meta.get(
        "visibility"
    )
    try:
        visibility = (
            models.VisibilityLevel(raw_visibility)
            if raw_visibility is not None
            else models.VisibilityLevel.RESTRICTED
        )
    except ValueError:
        visibility = models.VisibilityLevel.RESTRICTED

    created_by_ref = getattr(dataset_object, "created_by", None)
    created_by_id = None
    if created_by_ref is not None:
        created_by_id = users.get(created_by_ref)
    if created_by_id is None and users:
        created_by_id = next(iter(users.values()))
    if created_by_id is None:
        created_by_id = (await ensure_system_user(session)).id

    note = getattr(dataset_object, "note", None)
    doi = getattr(dataset_object, "doi", None)

    try:
        dataset = await common.get_object(
            session,
            models.Dataset,
            models.Dataset.uuid == dataset_object.uuid,
        )
    except exceptions.NotFoundError:
        dataset = await common.create_object(
            session,
            models.Dataset,
            name=dataset_object.name,
            description=dataset_object.description,
            audio_dir=dataset_dir.relative_to(audio_dir),
            uuid=dataset_object.uuid,
            created_by_id=created_by_id,
            visibility=visibility,
            project_id=project.project_id,
            note=note,
            doi=doi,
        )
    else:
        dataset.name = dataset_object.name
        dataset.description = dataset_object.description
        dataset.audio_dir = dataset_dir.relative_to(audio_dir)
        dataset.visibility = visibility
        dataset.project_id = project.project_id
        dataset.note = note
        dataset.doi = doi

    path_mapping = {
        recording.uuid: normalize_path(recording.path, dataset_dir)
        for recording in dataset_object.recordings or []
    }

    # Create dataset recordings
    values = [
        {
            "recording_id": recording_id,
            "dataset_id": dataset.id,
            "path": path_mapping[recording_uuid],
        }
        for recording_uuid, recording_id in recordings.items()
    ]
    await common.create_objects_without_duplicates(
        session,
        models.DatasetRecording,
        values,
        key=lambda x: (x["recording_id"], x["dataset_id"]),
        key_column=tuple_(
            models.DatasetRecording.recording_id,
            models.DatasetRecording.dataset_id,
        ),
    )

    await _ensure_project_membership(
        session,
        project.project_id,
        created_by_id,
        role=models.ProjectMemberRole.MANAGER,
    )

    return dataset


def normalize_path(path: Path, dataset_dir: Path) -> Path:
    """Normalize a path to a dataset directory."""
    if path.is_absolute():
        return path.relative_to(dataset_dir)
    return path
