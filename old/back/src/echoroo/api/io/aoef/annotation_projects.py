import datetime
import json
import uuid as uuidlib
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

from soundevent.io import aoef
from soundevent.io.aoef import AnnotationProjectObject
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import models
from echoroo.api import common
from echoroo.api.common import utils
from echoroo.api.io.aoef.annotation_tasks import get_annotation_tasks
from echoroo.api.io.aoef.clip_annotations import get_clip_annotations
from echoroo.api.io.aoef.clips import get_clips
from echoroo.api.io.aoef.datasets import (
    _ensure_project_membership,
    _resolve_project as _resolve_project_from_datasets,
)
from echoroo.api.io.aoef.features import get_feature_names
from echoroo.api.io.aoef.recordings import get_recordings
from echoroo.api.io.aoef.sound_event_annotations import (
    get_sound_event_annotations,
)
from echoroo.api.io.aoef.sound_events import get_sound_events
from echoroo.api.io.aoef.tags import import_tags
from echoroo.api.io.aoef.users import import_users
from echoroo.api.users import ensure_system_user


def _extract_metadata(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _sanitize_audio_dir(raw: str | None, slug: str) -> Path:
    if not raw:
        return Path("legacy") / "annotation_projects" / slug
    raw = raw.strip()
    if raw.startswith("/"):
        raw = raw.lstrip("/")
    return Path(raw)


async def _resolve_dataset_for_annotation_project(
    session: AsyncSession,
    *,
    dataset_meta: dict[str, Any],
    project: models.Project,
    created_by_id: UUID,
    visibility: models.VisibilityLevel,
) -> models.Dataset:
    dataset_uuid_raw = dataset_meta.get("uuid") or dataset_meta.get("dataset_uuid")
    dataset_uuid_value = None
    if dataset_uuid_raw:
        try:
            dataset_uuid_value = uuidlib.UUID(str(dataset_uuid_raw))
        except (TypeError, ValueError):
            dataset_uuid_value = None
    dataset_name = dataset_meta.get("name") or dataset_meta.get("dataset_name")
    dataset_description = dataset_meta.get("description")
    dataset_note = dataset_meta.get("note")
    dataset_doi = dataset_meta.get("doi")
    dataset_audio_dir = dataset_meta.get("audio_dir")

    dataset: models.Dataset | None = None
    if dataset_uuid_value is not None:
        result = await session.execute(
            select(models.Dataset).where(
                models.Dataset.uuid == dataset_uuid_value
            )
        )
        dataset = result.scalar_one_or_none()

    if dataset is None and dataset_name:
        result = await session.execute(
            select(models.Dataset).where(models.Dataset.name == dataset_name)
        )
        dataset = result.scalar_one_or_none()

    if dataset is None:
        generated_uuid = dataset_uuid_value or uuidlib.uuid4()
        slug = dataset_name or str(generated_uuid)
        audio_dir = _sanitize_audio_dir(dataset_audio_dir, slug)
        dataset = await common.create_object(
            session,
            models.Dataset,
            uuid=generated_uuid,
            name=dataset_name or f"imported_dataset_{slug}",
            description=dataset_description,
            audio_dir=audio_dir,
            created_by_id=created_by_id,
            visibility=visibility,
            project_id=project.project_id,
            note=dataset_note,
            doi=dataset_doi,
        )
    else:
        dataset.project_id = project.project_id
        dataset.visibility = visibility
        if dataset_description is not None:
            dataset.description = dataset_description
        if dataset_note is not None:
            dataset.note = dataset_note
        if dataset_doi is not None:
            dataset.doi = dataset_doi

    await _ensure_project_membership(
        session,
        project.project_id,
        created_by_id,
        role=models.ProjectMemberRole.MANAGER,
    )

    return dataset


async def import_annotation_project(
    session: AsyncSession,
    src: Path | BinaryIO | str,
    audio_dir: Path,
    base_audio_dir: Path,
) -> models.AnnotationProject:
    if isinstance(src, (Path, str)):
        with open(src, "r") as file:
            data = json.load(file)
    else:
        data = json.loads(src.read())

    if not isinstance(data, dict):
        raise TypeError(f"Expected dict, got {type(data)}")

    if "data" not in data:
        raise ValueError("Missing 'data' key")

    obj = aoef.AnnotationProjectObject.model_validate(data["data"])

    users = await import_users(session, obj.users or [])

    project = await get_or_create_annotation_project(session, obj, users)

    tags = await import_tags(session, obj.tags or [])

    feature_names = await get_feature_names(session, obj)

    recordings = await get_recordings(
        session,
        obj,
        tags=tags,
        users=users,
        feature_names=feature_names,
        audio_dir=audio_dir,
        base_audio_dir=base_audio_dir,
        should_import=False,
    )

    clips = await get_clips(
        session,
        obj,
        recordings=recordings,
        feature_names=feature_names,
    )

    sound_events = await get_sound_events(
        session,
        obj,
        recordings=recordings,
        feature_names=feature_names,
    )

    clip_annotations = await get_clip_annotations(
        session,
        obj,
        clips=clips,
        users=users,
        tags=tags,
    )

    await get_sound_event_annotations(
        session,
        obj,
        sound_events=sound_events,
        clip_annotations=clip_annotations,
        users=users,
        tags=tags,
    )

    await get_annotation_tasks(
        session,
        obj,
        clips=clips,
        annotation_projects={project.uuid: project.id},
        users=users,
        clip_annotations=clip_annotations,
    )

    await add_annotation_tags(
        session,
        obj,
        project.id,
        tags,
    )

    session.expire(project, ["tags"])

    return project


async def get_or_create_annotation_project(
    session: AsyncSession,
    obj: AnnotationProjectObject,
    users: dict[UUID, UUID],
) -> models.AnnotationProject:
    stmt = select(models.AnnotationProject).where(
        models.AnnotationProject.uuid == obj.uuid
    )
    result = await session.execute(stmt)
    row = result.unique().one_or_none()
    if row is not None:
        return row[0]

    created_by_ref = getattr(obj, "created_by", None)
    created_by_id = users.get(created_by_ref) if created_by_ref else None
    if created_by_id is None:
        created_by_id = (await ensure_system_user(session)).id

    metadata = _extract_metadata(getattr(obj, "metadata", {}))
    dataset_meta = _extract_metadata(metadata.get("dataset"))
    project_meta = _extract_metadata(metadata.get("project"))

    project = await _resolve_project_from_datasets(
        session,
        project_meta=project_meta,
        fallback_name=f"{obj.name or 'Imported'} Project",
    )

    raw_visibility = (
        dataset_meta.get("visibility")
        or project_meta.get("visibility")
        or getattr(obj, "visibility", None)
    )
    try:
        visibility = (
            models.VisibilityLevel(raw_visibility)
            if raw_visibility is not None
            else models.VisibilityLevel.RESTRICTED
        )
    except ValueError:
        visibility = models.VisibilityLevel.RESTRICTED

    dataset = await _resolve_dataset_for_annotation_project(
        session,
        dataset_meta=dataset_meta,
        project=project,
        created_by_id=created_by_id,
        visibility=visibility,
    )

    db_obj = models.AnnotationProject(
        uuid=obj.uuid,
        name=obj.name,
        description=obj.description or "",
        annotation_instructions=obj.instructions,
        created_on=obj.created_on
        or datetime.datetime.now(datetime.timezone.utc),
        visibility=dataset.visibility,
        created_by_id=created_by_id,
        project_id=project.project_id,
        dataset_id=dataset.id,
    )
    session.add(db_obj)
    await session.flush()

    await _ensure_project_membership(
        session,
        project.project_id,
        created_by_id,
        role=models.ProjectMemberRole.MANAGER,
    )

    return db_obj


async def add_annotation_tags(
    session: AsyncSession,
    project: AnnotationProjectObject,
    project_id: int,
    tags: dict[int, int],
) -> list[models.AnnotationProjectTag]:
    """Add annotation tags to a project."""
    proj_tags = project.project_tags or []
    if not proj_tags:
        return []

    values = [
        {
            "annotation_project_id": project_id,
            "tag_id": tags[tag],
            "created_on": datetime.datetime.now(),
        }
        for tag in proj_tags
        if tag in tags
    ]

    if not values:
        return []

    return await utils.create_objects_without_duplicates(
        session,
        models.AnnotationProjectTag,
        values,
        key=lambda x: (x["annotation_project_id"], x["tag_id"]),
        key_column=(
            tuple_(
                models.AnnotationProjectTag.annotation_project_id,
                models.AnnotationProjectTag.tag_id,
            )
        ),
    )
