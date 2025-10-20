"""Python API for annotation projects."""

import os
from pathlib import Path
from typing import Sequence
from uuid import UUID

from soundevent import data
from sqlalchemy import and_, select
from sqlalchemy.sql import ColumnExpressionArgument
from sqlalchemy.ext.asyncio import AsyncSession

from whombat import exceptions, models, schemas
from whombat.api import common
from whombat.api.annotation_tasks import annotation_tasks
from whombat.api.clip_annotations import clip_annotations
from whombat.api.common import BaseAPI
from whombat.api.common.permissions import (
    can_delete_annotation_project,
    can_edit_annotation_project,
    can_manage_restricted_annotation_project,
    can_view_annotation_project,
    filter_annotation_projects_by_access,
)
from whombat.api.tags import tags
from whombat.api.users import ensure_system_user
from whombat.filters.annotation_tasks import (
    AnnotationProjectFilter as AnnotationTaskAnnotationProjectFilter,
)
from whombat.filters.base import Filter
from whombat.filters.clip_annotations import AnnotationProjectFilter
from whombat.system.settings import get_settings

__all__ = [
    "AnnotationProjectAPI",
    "annotation_projects",
]


class AnnotationProjectAPI(
    BaseAPI[
        UUID,
        models.AnnotationProject,
        schemas.AnnotationProject,
        schemas.AnnotationProjectCreate,
        schemas.AnnotationProjectUpdate,
    ]
):
    _model = models.AnnotationProject
    _schema = schemas.AnnotationProject

    async def _resolve_user(
        self,
        session: AsyncSession,
        user: models.User | schemas.SimpleUser | None,
    ) -> models.User | None:
        if user is None:
            return None
        if isinstance(user, models.User):
            return user
        db_user = await session.get(models.User, user.id)
        if db_user is None:
            raise exceptions.NotFoundError(
                f"User with id {user.id} not found"
            )
        return db_user

    async def get(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.AnnotationProject:
        db_user = await self._resolve_user(session, user)
        project = await super().get(session, pk)

        if not await can_view_annotation_project(session, project, db_user):
            raise exceptions.NotFoundError(
                f"Annotation project with uuid {pk} not found"
            )

        return project

    async def get_many(
        self,
        session: AsyncSession,
        *,
        limit: int | None = 1000,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "-created_on",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.AnnotationProject], int]:
        db_user = await self._resolve_user(session, user)
        access_filters = await filter_annotation_projects_by_access(session, db_user)

        combined_filters: list[Filter | ColumnExpressionArgument] = []
        if filters:
            combined_filters.extend(filters)
        combined_filters.extend(access_filters)

        return await super().get_many(
            session,
            limit=limit,
            offset=offset,
            filters=combined_filters or None,
            sort_by=sort_by,
        )

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.AnnotationProject,
        data: schemas.AnnotationProjectUpdate,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.AnnotationProject:
        db_user = await self._resolve_user(session, user)

        if not await can_edit_annotation_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to update this annotation project"
            )

        target_visibility = obj.visibility
        if "visibility" in data.model_fields_set:
            target_visibility = data.visibility or obj.visibility

        target_group_id = obj.owner_group_id
        if "owner_group_id" in data.model_fields_set:
            target_group_id = data.owner_group_id

        if (
            target_visibility == models.VisibilityLevel.RESTRICTED
            and target_group_id is None
        ):
            raise exceptions.InvalidDataError(
                "Restricted visibility requires owner_group_id to be set"
            )

        if (
            db_user is not None
            and target_visibility == models.VisibilityLevel.RESTRICTED
            and target_group_id is not None
        ):
            allowed = await can_manage_restricted_annotation_project(
                session,
                target_group_id,
                db_user,
            )
            if not allowed:
                raise exceptions.PermissionDeniedError(
                    "You must be a manager of the selected group"
                )

        return await super().update(session, obj, data)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.AnnotationProject,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.AnnotationProject:
        db_user = await self._resolve_user(session, user)

        if not await can_delete_annotation_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this annotation project"
            )

        return await super().delete(session, obj)

    async def get_base_dir(
        self,
        session: AsyncSession,
        obj: schemas.AnnotationProject,
    ) -> Path:
        """Get the base directory from which to export recordings."""
        stmt = (
            select(models.Dataset.audio_dir)
            .join(
                models.DatasetRecording,
                models.DatasetRecording.dataset_id == models.Dataset.id,
            )
            .join(
                models.Recording,
                models.Recording.id == models.DatasetRecording.recording_id,
            )
            .join(models.Clip, models.Clip.recording_id == models.Recording.id)
            .join(
                models.AnnotationTask,
                models.AnnotationTask.clip_id == models.Clip.id,
            )
            .join(
                models.AnnotationProject,
                models.AnnotationProject.id
                == models.AnnotationTask.annotation_project_id,
            )
            .filter(models.AnnotationProject.uuid == obj.uuid)
            .distinct()
        )
        result = await session.execute(stmt)
        paths = result.fetchall()

        if not paths:
            return get_settings().audio_dir

        return Path(os.path.commonpath([p[0] for p in paths]))

    async def create(
        self,
        session: AsyncSession,
        name: str,
        description: str,
        annotation_instructions: str | None = None,
        *,
        user: models.User | schemas.SimpleUser,
        visibility: models.VisibilityLevel = models.VisibilityLevel.PRIVATE,
        owner_group_id: int | None = None,
        **kwargs,
    ) -> schemas.AnnotationProject:
        """Create an annotation project.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        name
            Name of the annotation project.
        description
            Description of the annotation project.
        annotation_instructions
            Intructions for annotators on how to successfully annotate
            an annotation task. This is important for ensuring that
            annotations are consistent across annotators, and provides
            a unambiguous definition of what a completed annotation
            task should look like.
        **kwargs
            Additional keyword arguments to pass to the creation.

        Returns
        -------
        schemas.AnnotationProject
            Created annotation project.
        """
        db_user = await self._resolve_user(session, user)

        if (
            visibility == models.VisibilityLevel.RESTRICTED
            and owner_group_id is None
        ):
            raise exceptions.InvalidDataError(
                "Restricted visibility requires owner_group_id to be set"
            )

        if (
            visibility == models.VisibilityLevel.RESTRICTED
            and owner_group_id is not None
        ):
            allowed = await can_manage_restricted_annotation_project(
                session,
                owner_group_id,
                db_user,
            )
            if not allowed:
                raise exceptions.PermissionDeniedError(
                    "You must be a manager of the selected group to create a restricted annotation project"
                )

        return await self.create_from_data(
            session,
            schemas.AnnotationProjectCreate(
                name=name,
                description=description,
                annotation_instructions=annotation_instructions,
                visibility=visibility,
                owner_group_id=owner_group_id,
            ),
            created_by_id=db_user.id,
            **kwargs,
        )

    async def add_tag(
        self,
        session: AsyncSession,
        obj: schemas.AnnotationProject,
        tag: schemas.Tag,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.AnnotationProject:
        """Add a tag to an annotation project.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        obj
            Annotation project to add the tag to.
        tag
            Tag to add.

        Returns
        -------
        schemas.AnnotationProject
            Annotation project with the tag added.
        """
        db_user = await self._resolve_user(session, user)

        if not await can_edit_annotation_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this annotation project"
            )

        for t in obj.tags:
            if t.id == tag.id:
                raise exceptions.DuplicateObjectError(
                    f"Tag {tag.id} already exists in annotation "
                    f"project {obj.id}"
                )

        await common.create_object(
            session,
            models.AnnotationProjectTag,
            annotation_project_id=obj.id,
            tag_id=tag.id,
        )

        obj = obj.model_copy(
            update=dict(
                tags=[*obj.tags, tag],
            )
        )
        self._update_cache(obj)
        return obj

    async def remove_tag(
        self,
        session: AsyncSession,
        obj: schemas.AnnotationProject,
        tag: schemas.Tag,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.AnnotationProject:
        """Remove a tag from an annotation project.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        obj
            Annotation project to remove the tag from.
        tag
            Tag to remove.

        Returns
        -------
        schemas.AnnotationProject
            Annotation project with the tag removed.
        """
        db_user = await self._resolve_user(session, user)

        if not await can_edit_annotation_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this annotation project"
            )

        for t in obj.tags:
            if t.id == tag.id:
                break
        else:
            raise exceptions.NotFoundError(
                f"Tag {tag.id} does not exist in annotation project {obj.id}"
            )

        await common.delete_object(
            session,
            models.AnnotationProjectTag,
            and_(
                models.AnnotationProjectTag.annotation_project_id == obj.id,
                models.AnnotationProjectTag.tag_id == tag.id,
            ),
        )

        obj = obj.model_copy(
            update=dict(
                tags=[t for t in obj.tags if t.id != tag.id],
            )
        )
        self._update_cache(obj)
        return obj

    async def add_task(
        self,
        session: AsyncSession,
        obj: schemas.AnnotationProject,
        clip: schemas.Clip,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.AnnotationTask:
        clip_annotation = await clip_annotations.create(session, clip)
        db_user = await self._resolve_user(session, user)
        if not await can_edit_annotation_project(session, obj, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this annotation project"
            )
        return await annotation_tasks.create(
            session,
            obj,
            clip,
            clip_annotation_id=clip_annotation.id,
        )

    async def get_annotations(
        self,
        session: AsyncSession,
        obj: schemas.AnnotationProject,
        *,
        limit: int = 1000,
        offset: int = 0,
        filters: Sequence[Filter] | None = None,
        sort_by: str | None = "-created_on",
    ) -> tuple[Sequence[schemas.ClipAnnotation], int]:
        """Get a list of annotations for an annotation project.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        obj
            Annotation project to get annotations for.
        limit
            Maximum number of annotations to return. By default 1000.
        offset
            Offset of the first annotation to return. By default 0.
        filters
            Filters to apply. Only annotations matching all filters will
            be returned. By default None.
        sort_by
            Field to sort by.

        Returns
        -------
        annotations : list[schemas.ClipAnnotation]
            List of clip annotations.
        count : int
            Total number of annotations matching the given criteria.
            This number may be larger than the number of annotations
            returned if limit is smaller than the total number of annotations
            matching the given criteria.
        """
        return await clip_annotations.get_many(
            session,
            limit=limit,
            offset=offset,
            filters=[
                AnnotationProjectFilter(eq=obj.uuid),
                *(filters or []),
            ],
            sort_by=sort_by,
        )

    async def from_soundevent(
        self,
        session: AsyncSession,
        data: data.AnnotationProject,
    ) -> schemas.AnnotationProject:
        """Convert a soundevent Annotation Project to a Whombat annotation project.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        data
            soundevent annotation project.

        Returns
        -------
        schemas.AnnotationProject
            Whombat annotation project.
        """
        try:
            annotation_project = await self.get(session, data.uuid)
        except exceptions.NotFoundError:
            creator = await ensure_system_user(session)
            raw_visibility = getattr(data, "visibility", None)
            try:
                visibility = (
                    models.VisibilityLevel(raw_visibility)
                    if raw_visibility is not None
                    else models.VisibilityLevel.PRIVATE
                )
            except ValueError:
                visibility = models.VisibilityLevel.PRIVATE
            annotation_project = await self.create(
                session,
                name=data.name,
                description=data.description or "",
                annotation_instructions=data.instructions or "",
                user=creator,
                visibility=visibility,
                uuid=data.uuid,
                created_on=data.created_on,
            )

        for clip_annotation in data.clip_annotations:
            await clip_annotations.from_soundevent(session, clip_annotation)

        return annotation_project

    async def to_soundevent(
        self,
        session: AsyncSession,
        obj: schemas.AnnotationProject,
        audio_dir: Path | None = None,
    ) -> data.AnnotationProject:
        """Convert a Whombat annotation project to a soundevent annotation project.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        obj
            Whombat annotation project.

        Returns
        -------
        data.AnnotationProject
            soundevent annotation project.
        """
        tasks, _ = await annotation_tasks.get_many(
            session,
            limit=-1,
            filters=[AnnotationTaskAnnotationProjectFilter(eq=obj.uuid)],
        )

        stmt = (
            select(models.Clip, models.AnnotationTask.id)
            .join(
                models.AnnotationTask,
                models.Clip.id == models.AnnotationTask.clip_id,
            )
            .where(
                models.AnnotationTask.id.in_({t.id for t in tasks}),
            )
        )
        results = await session.execute(stmt)
        mapping = {r[1]: r[0] for r in results.unique().all()}

        se_tasks = [
            await annotation_tasks.to_soundevent(
                session,
                task,
                audio_dir=audio_dir,
                clip=mapping[task.id],
            )
            for task in tasks
            if task.id in mapping
        ]

        annotations, _ = await self.get_annotations(session, obj, limit=-1)
        se_clip_annotations = [
            await clip_annotations.to_soundevent(
                session, ca, audio_dir=audio_dir
            )
            for ca in annotations
        ]

        return data.AnnotationProject(
            uuid=obj.uuid,
            name=obj.name,
            description=obj.description,
            instructions=obj.annotation_instructions,
            created_on=obj.created_on,
            clip_annotations=se_clip_annotations,
            annotation_tags=[tags.to_soundevent(tag) for tag in obj.tags],
            tasks=se_tasks,
        )


annotation_projects = AnnotationProjectAPI()
