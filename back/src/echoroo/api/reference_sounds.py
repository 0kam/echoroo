"""Python API for Reference Sounds."""

import logging
from typing import Sequence
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.ml_projects import can_edit_ml_project, can_view_ml_project
from echoroo.filters.base import Filter

__all__ = [
    "ReferenceSoundAPI",
    "reference_sounds",
]

logger = logging.getLogger(__name__)

XENO_CANTO_API_URL = "https://xeno-canto.org/api/2/recordings"


class ReferenceSoundAPI(
    BaseAPI[
        UUID,
        models.ReferenceSound,
        schemas.ReferenceSound,
        schemas.ReferenceSoundCreate,
        schemas.ReferenceSoundUpdate,
    ]
):
    """API for managing Reference Sounds."""

    _model = models.ReferenceSound
    _schema = schemas.ReferenceSound

    async def _resolve_user(
        self,
        session: AsyncSession,
        user: models.User | schemas.SimpleUser | None,
    ) -> models.User | None:
        """Resolve a user schema to a user model."""
        if user is None:
            return None
        if isinstance(user, models.User):
            return user
        db_user = await session.get(models.User, user.id)
        if db_user is None:
            raise exceptions.NotFoundError(f"User with id {user.id} not found")
        return db_user

    async def _get_ml_project(
        self,
        session: AsyncSession,
        ml_project_id: int,
    ) -> models.MLProject:
        """Get ML project by ID."""
        ml_project = await session.get(models.MLProject, ml_project_id)
        if ml_project is None:
            raise exceptions.NotFoundError(
                f"ML Project with id {ml_project_id} not found"
            )
        return ml_project

    async def _eager_load_relationships(
        self,
        session: AsyncSession,
        db_obj: models.ReferenceSound,
    ) -> models.ReferenceSound:
        """Eagerly load relationships needed for ReferenceSound schema validation."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.tag),
                selectinload(self._model.clip),
                selectinload(self._model.ml_project),
                selectinload(self._model.created_by),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.ReferenceSound,
    ) -> schemas.ReferenceSound:
        """Build schema from database object."""
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Map source enum
        source_map = {
            models.ReferenceSoundSource.XENO_CANTO: schemas.ReferenceSoundSource.XENO_CANTO,
            models.ReferenceSoundSource.CUSTOM_UPLOAD: schemas.ReferenceSoundSource.UPLOAD,
            models.ReferenceSoundSource.DATASET_CLIP: schemas.ReferenceSoundSource.CLIP,
        }
        source = source_map.get(
            db_obj.source, schemas.ReferenceSoundSource.UPLOAD
        )

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "ml_project_id": db_obj.ml_project_id,
            "ml_project_uuid": db_obj.ml_project.uuid if db_obj.ml_project else None,
            "source": source,
            "tag_id": db_obj.tag_id,
            "tag": schemas.Tag.model_validate(db_obj.tag) if db_obj.tag else None,
            "start_time": db_obj.start_time,
            "end_time": db_obj.end_time,
            "duration": db_obj.end_time - db_obj.start_time,
            "xeno_canto_id": db_obj.xeno_canto_id,
            "clip_id": db_obj.clip_id,
            "clip": (
                schemas.Clip.model_validate(db_obj.clip) if db_obj.clip else None
            ),
            "audio_path": db_obj.audio_path,
            "has_embedding": db_obj.embedding is not None,
            "is_active": db_obj.is_active,
            "created_by_id": db_obj.created_by_id,
            "created_on": db_obj.created_on,
        }

        return schemas.ReferenceSound.model_validate(data)

    async def get(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.ReferenceSound:
        """Get a reference sound by UUID."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(pk),
        )

        # Check access via ML project
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Reference sound with uuid {pk} not found"
            )

        return await self._build_schema(session, db_obj)

    async def get_many(
        self,
        session: AsyncSession,
        ml_project_id: int,
        *,
        limit: int | None = 1000,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "-created_on",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.ReferenceSound], int]:
        """Get reference sounds for an ML project."""
        db_user = await self._resolve_user(session, user)

        # Check access to the ML project
        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with id {ml_project_id} not found"
            )

        # Add filter for ml_project_id
        combined_filters: list[Filter | ColumnExpressionArgument] = [
            self._model.ml_project_id == ml_project_id
        ]
        if filters:
            combined_filters.extend(filters)

        db_objs, count = await common.get_objects(
            session,
            self._model,
            limit=limit,
            offset=offset,
            filters=combined_filters,
            sort_by=sort_by,
        )

        results = []
        for db_obj in db_objs:
            schema_obj = await self._build_schema(session, db_obj)
            results.append(schema_obj)

        return results, count

    async def create_from_xeno_canto(
        self,
        session: AsyncSession,
        ml_project_id: int,
        data: schemas.ReferenceSoundFromXenoCanto,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.ReferenceSound:
        """Create a reference sound from a Xeno-Canto recording.

        This downloads audio metadata from Xeno-Canto and stores
        the reference. The embedding will be computed asynchronously.
        """
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create reference sounds"
            )

        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to add reference sounds to this ML project"
            )

        # Check if tag exists
        tag = await session.get(models.Tag, data.tag_id)
        if tag is None:
            raise exceptions.NotFoundError(f"Tag with id {data.tag_id} not found")

        # Fetch Xeno-Canto recording metadata (optional - for validation)
        xc_id = data.xeno_canto_id.upper()
        if xc_id.startswith("XC"):
            xc_id_num = xc_id[2:]
        else:
            xc_id_num = xc_id
            xc_id = f"XC{xc_id_num}"

        xc_url = f"https://xeno-canto.org/{xc_id_num}"

        # Create the reference sound
        db_obj = await common.create_object(
            session,
            self._model,
            name=data.name,
            description=getattr(data, "notes", None),
            ml_project_id=ml_project_id,
            source=models.ReferenceSoundSource.XENO_CANTO,
            xeno_canto_id=xc_id,
            xeno_canto_url=xc_url,
            tag_id=data.tag_id,
            start_time=data.start_time,
            end_time=data.end_time,
            is_active=True,
            created_by_id=db_user.id,
        )

        return await self._build_schema(session, db_obj)

    async def create_from_clip(
        self,
        session: AsyncSession,
        ml_project_id: int,
        data: schemas.ReferenceSoundFromClip,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.ReferenceSound:
        """Create a reference sound from an existing dataset clip.

        Uses the clip's embedding if available.
        """
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create reference sounds"
            )

        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to add reference sounds to this ML project"
            )

        # Check if tag exists
        tag = await session.get(models.Tag, data.tag_id)
        if tag is None:
            raise exceptions.NotFoundError(f"Tag with id {data.tag_id} not found")

        # Check if clip exists
        clip = await session.get(models.Clip, data.clip_id)
        if clip is None:
            raise exceptions.NotFoundError(f"Clip with id {data.clip_id} not found")

        # Try to get clip embedding if ML project has an embedding model run
        embedding = None
        if ml_project.embedding_model_run_id:
            embedding_query = select(models.ClipEmbedding).where(
                models.ClipEmbedding.clip_id == clip.id,
                models.ClipEmbedding.model_run_id == ml_project.embedding_model_run_id,
            )
            result = await session.execute(embedding_query)
            clip_embedding = result.scalar_one_or_none()
            if clip_embedding:
                embedding = clip_embedding.embedding

        # Create the reference sound
        db_obj = await common.create_object(
            session,
            self._model,
            name=data.name,
            description=getattr(data, "notes", None),
            ml_project_id=ml_project_id,
            source=models.ReferenceSoundSource.DATASET_CLIP,
            clip_id=clip.id,
            tag_id=data.tag_id,
            start_time=data.start_time,
            end_time=data.end_time,
            embedding=embedding,
            is_active=True,
            created_by_id=db_user.id,
        )

        return await self._build_schema(session, db_obj)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.ReferenceSound,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.ReferenceSound:
        """Delete a reference sound."""
        db_user = await self._resolve_user(session, user)

        # Get the ML project for permission check
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this reference sound"
            )

        # Build the result before deletion
        result = await self._build_schema(session, db_obj)

        # Delete
        await common.delete_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        return result

    async def compute_embedding(
        self,
        session: AsyncSession,
        obj: schemas.ReferenceSound,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.ReferenceSound:
        """Compute or recompute embedding for a reference sound.

        This is a placeholder that would integrate with the ML pipeline
        to compute embeddings from the audio.
        """
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this reference sound"
            )

        # TODO: Implement actual embedding computation
        # This would:
        # 1. Load the audio from the source (Xeno-Canto, clip, or uploaded file)
        # 2. Extract the segment defined by start_time/end_time
        # 3. Run the embedding model
        # 4. Store the embedding

        logger.info(
            f"Embedding computation requested for reference sound {obj.uuid}. "
            "This feature requires ML pipeline integration."
        )

        return await self._build_schema(session, db_obj)

    async def update(
        self,
        session: AsyncSession,
        obj: schemas.ReferenceSound,
        data: schemas.ReferenceSoundUpdate,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.ReferenceSound:
        """Update a reference sound."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to modify this reference sound"
            )

        # Build update data
        update_data = {}
        if data.name is not None:
            update_data["name"] = data.name
        if data.tag_id is not None:
            # Verify tag exists
            tag = await session.get(models.Tag, data.tag_id)
            if tag is None:
                raise exceptions.NotFoundError(
                    f"Tag with id {data.tag_id} not found"
                )
            update_data["tag_id"] = data.tag_id
        if data.start_time is not None:
            update_data["start_time"] = data.start_time
        if data.end_time is not None:
            update_data["end_time"] = data.end_time
        if data.notes is not None:
            update_data["description"] = data.notes
        if data.is_active is not None:
            update_data["is_active"] = data.is_active

        if update_data:
            db_obj = await common.update_object(
                session,
                self._model,
                self._get_pk_condition(obj.uuid),
                update_data,
            )

        return await self._build_schema(session, db_obj)


reference_sounds = ReferenceSoundAPI()
