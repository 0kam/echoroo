"""Python API for Search Sessions."""

import datetime
import logging
from typing import Sequence
from uuid import UUID

import numpy as np
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.ml_projects import can_edit_ml_project, can_view_ml_project
from echoroo.filters.base import Filter

__all__ = [
    "SearchSessionAPI",
    "search_sessions",
]

logger = logging.getLogger(__name__)


class SearchSessionAPI(
    BaseAPI[
        UUID,
        models.SearchSession,
        schemas.SearchSession,
        schemas.SearchSessionCreate,
        schemas.SearchSession,
    ]
):
    """API for managing Search Sessions."""

    _model = models.SearchSession
    _schema = schemas.SearchSession

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
        db_obj: models.SearchSession,
    ) -> models.SearchSession:
        """Eagerly load relationships needed for SearchSession schema validation."""
        stmt = (
            select(self._model)
            .where(self._model.uuid == db_obj.uuid)
            .options(
                selectinload(self._model.target_tag),
                selectinload(self._model.ml_project),
                selectinload(self._model.created_by),
                selectinload(self._model.reference_sounds),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.SearchSession,
    ) -> schemas.SearchSession:
        """Build schema from database object."""
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Get result counts
        total_results = await session.scalar(
            select(func.count(models.SearchResult.id)).where(
                models.SearchResult.search_session_id == db_obj.id
            )
        )

        labeled_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.label != models.SearchResultLabel.UNLABELED)
        )

        positive_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.label == models.SearchResultLabel.POSITIVE)
        )

        negative_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.label == models.SearchResultLabel.NEGATIVE)
        )

        uncertain_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.label == models.SearchResultLabel.UNCERTAIN)
        )

        skipped_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.label == models.SearchResultLabel.SKIPPED)
        )

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "ml_project_id": db_obj.ml_project_id,
            "ml_project_uuid": db_obj.ml_project.uuid if db_obj.ml_project else None,
            "similarity_threshold": db_obj.similarity_threshold,
            "max_results": db_obj.max_results,
            "tag_id": db_obj.target_tag_id,
            "tag": (
                schemas.Tag.model_validate(db_obj.target_tag)
                if db_obj.target_tag
                else None
            ),
            "total_results": total_results or 0,
            "labeled_count": labeled_count or 0,
            "positive_count": positive_count or 0,
            "negative_count": negative_count or 0,
            "uncertain_count": uncertain_count or 0,
            "skipped_count": skipped_count or 0,
            "created_by_id": db_obj.created_by_id,
            "created_on": db_obj.created_on,
            "completed_at": None,  # Could be set when is_labeling_complete is True
        }

        return schemas.SearchSession.model_validate(data)

    async def get(
        self,
        session: AsyncSession,
        pk: UUID,
        user: models.User | None = None,
    ) -> schemas.SearchSession:
        """Get a search session by UUID."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(pk),
        )

        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Search session with uuid {pk} not found"
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
    ) -> tuple[Sequence[schemas.SearchSession], int]:
        """Get search sessions for an ML project."""
        db_user = await self._resolve_user(session, user)

        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with id {ml_project_id} not found"
            )

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

    async def create(
        self,
        session: AsyncSession,
        ml_project_id: int,
        data: schemas.SearchSessionCreate,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.SearchSession:
        """Create a new search session."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to create search sessions"
            )

        ml_project = await self._get_ml_project(session, ml_project_id)
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to create search sessions in this ML project"
            )

        # Validate reference sounds exist and belong to this ML project
        for ref_id in data.reference_sound_ids:
            ref = await session.get(models.ReferenceSound, ref_id)
            if ref is None:
                raise exceptions.NotFoundError(
                    f"Reference sound with id {ref_id} not found"
                )
            if ref.ml_project_id != ml_project_id:
                raise exceptions.InvalidDataError(
                    f"Reference sound {ref_id} does not belong to this ML project"
                )

        # Validate tag if specified
        target_tag_id = data.tag_id
        if target_tag_id:
            tag = await session.get(models.Tag, target_tag_id)
            if tag is None:
                raise exceptions.NotFoundError(
                    f"Tag with id {target_tag_id} not found"
                )
        else:
            # Use the first reference sound's tag
            first_ref = await session.get(
                models.ReferenceSound, data.reference_sound_ids[0]
            )
            target_tag_id = first_ref.tag_id

        # Create the search session
        name = data.name or f"Search {datetime.datetime.now(datetime.UTC).isoformat()}"

        db_obj = await common.create_object(
            session,
            self._model,
            name=name,
            description=data.notes,
            ml_project_id=ml_project_id,
            target_tag_id=target_tag_id,
            similarity_threshold=data.similarity_threshold,
            max_results=data.max_results,
            is_search_complete=False,
            is_labeling_complete=False,
            created_by_id=db_user.id,
        )

        # Link reference sounds
        for ref_id in data.reference_sound_ids:
            await common.create_object(
                session,
                models.SearchSessionReferenceSound,
                search_session_id=db_obj.id,
                reference_sound_id=ref_id,
            )

        return await self._build_schema(session, db_obj)

    async def delete(
        self,
        session: AsyncSession,
        obj: schemas.SearchSession,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SearchSession:
        """Delete a search session."""
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to delete this search session"
            )

        result = await self._build_schema(session, db_obj)

        await common.delete_object(
            session,
            self._model,
            self._get_pk_condition(obj.uuid),
        )

        return result

    async def execute_search(
        self,
        session: AsyncSession,
        search_session: schemas.SearchSession,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SearchSession:
        """Execute the similarity search using pgvector.

        This performs the actual similarity search using reference sound
        embeddings to find similar clips in the dataset.
        """
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(search_session.uuid),
        )
        db_obj = await self._eager_load_relationships(session, db_obj)
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to execute this search"
            )

        if db_obj.is_search_complete:
            raise exceptions.InvalidDataError(
                "Search has already been executed for this session"
            )

        # Get reference embeddings
        ref_embeddings_query = (
            select(models.ReferenceSound.embedding)
            .join(
                models.SearchSessionReferenceSound,
                models.SearchSessionReferenceSound.reference_sound_id
                == models.ReferenceSound.id,
            )
            .where(
                models.SearchSessionReferenceSound.search_session_id == db_obj.id
            )
            .where(models.ReferenceSound.embedding.isnot(None))
        )
        result = await session.execute(ref_embeddings_query)
        embeddings = [row[0] for row in result.fetchall() if row[0] is not None]

        if not embeddings:
            raise exceptions.InvalidDataError(
                "No reference sounds with embeddings found. "
                "Please compute embeddings for reference sounds first."
            )

        # Check that ML project has an embedding model run
        if not ml_project.embedding_model_run_id:
            raise exceptions.InvalidDataError(
                "ML Project does not have an embedding model configured. "
                "Please set an embedding model run for the project."
            )

        # Get the dataset to filter clips
        dataset_id = ml_project.dataset_id

        # Use MAX similarity across all reference embeddings
        # For each clip, we take the maximum similarity score across all reference sounds
        # This ensures clips that match ANY reference sound well will rank high

        # Collect all results with max similarity per clip
        all_results: dict[int, float] = {}  # clip_id -> max_similarity

        for embedding in embeddings:
            # Convert embedding to string format for pgvector
            embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

            # Query for similar clips using pgvector cosine distance
            # We request more results than max_results since we'll merge later
            search_query = text("""
                WITH dataset_clips AS (
                    SELECT DISTINCT c.id as clip_id
                    FROM clip c
                    JOIN recording r ON c.recording_id = r.id
                    JOIN dataset_recording dr ON dr.recording_id = r.id
                    WHERE dr.dataset_id = :dataset_id
                )
                SELECT
                    ce.clip_id,
                    1 - (ce.embedding <=> :query_embedding::vector) as similarity
                FROM clip_embedding ce
                JOIN dataset_clips dc ON dc.clip_id = ce.clip_id
                WHERE ce.model_run_id = :model_run_id
                AND 1 - (ce.embedding <=> :query_embedding::vector) >= :threshold
                ORDER BY ce.embedding <=> :query_embedding::vector
                LIMIT :query_limit
            """)

            search_result = await session.execute(
                search_query,
                {
                    "query_embedding": embedding_str,
                    "model_run_id": ml_project.embedding_model_run_id,
                    "threshold": db_obj.similarity_threshold,
                    # Request more results per embedding to ensure we capture all relevant clips
                    "query_limit": db_obj.max_results * 2,
                    "dataset_id": dataset_id,
                },
            )

            for row in search_result.fetchall():
                clip_id = row.clip_id
                similarity = row.similarity
                # Keep the maximum similarity for each clip
                if clip_id not in all_results:
                    all_results[clip_id] = similarity
                else:
                    all_results[clip_id] = max(all_results[clip_id], similarity)

        # Sort by max similarity and take top N
        sorted_results = sorted(
            all_results.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:db_obj.max_results]

        # Create a simple data class for row results
        from dataclasses import dataclass

        @dataclass
        class SimilarityRow:
            clip_id: int
            similarity: float

        # Convert to rows format for compatibility with existing code
        rows = [
            SimilarityRow(clip_id=clip_id, similarity=similarity)
            for clip_id, similarity in sorted_results
        ]

        # Create search results
        for rank, row in enumerate(rows, start=1):
            await common.create_object(
                session,
                models.SearchResult,
                search_session_id=db_obj.id,
                clip_id=row.clip_id,
                similarity=row.similarity,
                rank=rank,
                label=models.SearchResultLabel.UNLABELED,
            )

        # Mark search as complete
        await common.update_object(
            session,
            self._model,
            self._get_pk_condition(search_session.uuid),
            {"is_search_complete": True},
        )

        logger.info(
            f"Search session {search_session.uuid} completed with {len(rows)} results"
        )

        return await self._build_schema(session, db_obj)

    async def get_search_results(
        self,
        session: AsyncSession,
        search_session_id: int,
        *,
        limit: int | None = 100,
        offset: int | None = 0,
        filters: Sequence[Filter | ColumnExpressionArgument] | None = None,
        sort_by: ColumnExpressionArgument | str | None = "rank",
        user: models.User | None = None,
    ) -> tuple[Sequence[schemas.SearchResult], int]:
        """Get search results for a session."""
        db_user = await self._resolve_user(session, user)

        # Get search session
        search_session = await session.get(models.SearchSession, search_session_id)
        if search_session is None:
            raise exceptions.NotFoundError(
                f"Search session with id {search_session_id} not found"
            )

        ml_project = await self._get_ml_project(
            session, search_session.ml_project_id
        )
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Search session with id {search_session_id} not found"
            )

        combined_filters: list[Filter | ColumnExpressionArgument] = [
            models.SearchResult.search_session_id == search_session_id
        ]
        if filters:
            combined_filters.extend(filters)

        db_objs, count = await common.get_objects(
            session,
            models.SearchResult,
            limit=limit,
            offset=offset,
            filters=combined_filters,
            sort_by=sort_by,
        )

        results = []
        for db_obj in db_objs:
            # Load relationships
            await session.refresh(db_obj, ["clip", "search_session"])
            clip_schema = schemas.Clip.model_validate(db_obj.clip)

            # Get first reference sound for this session
            ref_query = (
                select(models.SearchSessionReferenceSound.reference_sound_id)
                .where(
                    models.SearchSessionReferenceSound.search_session_id
                    == search_session_id
                )
                .limit(1)
            )
            ref_result = await session.execute(ref_query)
            ref_id = ref_result.scalar_one_or_none()

            ref_uuid = None
            if ref_id:
                ref = await session.get(models.ReferenceSound, ref_id)
                if ref:
                    ref_uuid = ref.uuid

            data = {
                "uuid": db_obj.uuid,
                "id": db_obj.id,
                "search_session_id": db_obj.search_session_id,
                "search_session_uuid": search_session.uuid,
                "clip_id": db_obj.clip_id,
                "clip": clip_schema,
                "reference_sound_id": ref_id or 0,
                "reference_sound_uuid": ref_uuid or UUID(int=0),
                "similarity_score": db_obj.similarity,
                "rank": db_obj.rank,
                "label": schemas.SearchResultLabel(db_obj.label.value),
                "labeled_at": db_obj.labeled_on,
                "labeled_by_id": db_obj.labeled_by_id,
                "notes": db_obj.notes,
                "created_on": db_obj.created_on,
            }
            results.append(schemas.SearchResult.model_validate(data))

        return results, count

    async def label_result(
        self,
        session: AsyncSession,
        result_uuid: UUID,
        label: schemas.SearchResultLabel,
        notes: str | None = None,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SearchResult:
        """Label a search result."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to label results"
            )

        db_result = await common.get_object(
            session,
            models.SearchResult,
            models.SearchResult.uuid == result_uuid,
        )

        search_session = await session.get(
            models.SearchSession, db_result.search_session_id
        )
        if search_session is None:
            raise exceptions.NotFoundError("Search session not found")

        ml_project = await self._get_ml_project(
            session, search_session.ml_project_id
        )
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to label results in this session"
            )

        # Update the result
        update_data = {
            "label": models.SearchResultLabel(label.value),
            "labeled_by_id": db_user.id,
            "labeled_on": datetime.datetime.now(datetime.UTC),
        }
        if notes is not None:
            update_data["notes"] = notes

        db_result = await common.update_object(
            session,
            models.SearchResult,
            models.SearchResult.uuid == result_uuid,
            update_data,
        )

        # Build and return schema
        await session.refresh(db_result, ["clip", "search_session"])
        clip_schema = schemas.Clip.model_validate(db_result.clip)

        ref_query = (
            select(models.SearchSessionReferenceSound.reference_sound_id)
            .where(
                models.SearchSessionReferenceSound.search_session_id
                == db_result.search_session_id
            )
            .limit(1)
        )
        ref_result = await session.execute(ref_query)
        ref_id = ref_result.scalar_one_or_none()

        ref_uuid = None
        if ref_id:
            ref = await session.get(models.ReferenceSound, ref_id)
            if ref:
                ref_uuid = ref.uuid

        data = {
            "uuid": db_result.uuid,
            "id": db_result.id,
            "search_session_id": db_result.search_session_id,
            "search_session_uuid": search_session.uuid,
            "clip_id": db_result.clip_id,
            "clip": clip_schema,
            "reference_sound_id": ref_id or 0,
            "reference_sound_uuid": ref_uuid or UUID(int=0),
            "similarity_score": db_result.similarity,
            "rank": db_result.rank,
            "label": schemas.SearchResultLabel(db_result.label.value),
            "labeled_at": db_result.labeled_on,
            "labeled_by_id": db_result.labeled_by_id,
            "notes": db_result.notes,
            "created_on": db_result.created_on,
        }
        return schemas.SearchResult.model_validate(data)

    async def bulk_label_results(
        self,
        session: AsyncSession,
        result_uuids: list[UUID],
        label: schemas.SearchResultLabel,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> int:
        """Label multiple search results at once. Returns count of updated results."""
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to label results"
            )

        updated_count = 0
        for result_uuid in result_uuids:
            try:
                await self.label_result(
                    session, result_uuid, label, user=db_user
                )
                updated_count += 1
            except exceptions.NotFoundError:
                logger.warning(f"Search result {result_uuid} not found during bulk label")
            except exceptions.PermissionDeniedError:
                logger.warning(
                    f"Permission denied for result {result_uuid} during bulk label"
                )

        return updated_count

    async def get_search_progress(
        self,
        session: AsyncSession,
        search_session_id: int,
        *,
        user: models.User | None = None,
    ) -> schemas.SearchProgress:
        """Get progress statistics for a search session."""
        db_user = await self._resolve_user(session, user)

        search_session = await session.get(models.SearchSession, search_session_id)
        if search_session is None:
            raise exceptions.NotFoundError(
                f"Search session with id {search_session_id} not found"
            )

        ml_project = await self._get_ml_project(
            session, search_session.ml_project_id
        )
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Search session with id {search_session_id} not found"
            )

        # Get counts
        total = await session.scalar(
            select(func.count(models.SearchResult.id)).where(
                models.SearchResult.search_session_id == search_session_id
            )
        ) or 0

        labeled = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.label != models.SearchResultLabel.UNLABELED)
        ) or 0

        positive = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.label == models.SearchResultLabel.POSITIVE)
        ) or 0

        negative = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.label == models.SearchResultLabel.NEGATIVE)
        ) or 0

        uncertain = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.label == models.SearchResultLabel.UNCERTAIN)
        ) or 0

        skipped = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.label == models.SearchResultLabel.SKIPPED)
        ) or 0

        unlabeled = total - labeled
        progress_percent = (labeled / total * 100) if total > 0 else 0.0

        return schemas.SearchProgress(
            total=total,
            labeled=labeled,
            positive=positive,
            negative=negative,
            uncertain=uncertain,
            skipped=skipped,
            unlabeled=unlabeled,
            progress_percent=progress_percent,
        )

    async def bulk_curate(
        self,
        session: AsyncSession,
        search_session: schemas.SearchSession,
        result_uuids: list[UUID],
        label: str,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> list[schemas.SearchResult]:
        """Bulk curate search results as positive or negative references.

        This is used to select high-quality examples for further model
        training or as references for active learning.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        search_session
            The search session containing the results.
        result_uuids
            UUIDs of results to curate.
        label
            Curation label ('positive_reference' or 'negative_reference').
        user
            The user performing the curation.

        Returns
        -------
        list[schemas.SearchResult]
            Updated search results.
        """
        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to curate results"
            )

        # Validate label is a valid curation label
        valid_labels = [
            models.SearchResultLabel.POSITIVE_REFERENCE.value,
            models.SearchResultLabel.NEGATIVE_REFERENCE.value,
        ]
        if label not in valid_labels:
            raise exceptions.InvalidDataError(
                f"Invalid curation label '{label}'. Must be one of: {valid_labels}"
            )

        # Verify access
        db_session = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(search_session.uuid),
        )
        ml_project = await self._get_ml_project(session, db_session.ml_project_id)
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to curate results in this session"
            )

        # Update results
        curated_results = []
        for result_uuid in result_uuids:
            try:
                result = await self.label_result(
                    session,
                    result_uuid,
                    schemas.SearchResultLabel(label),
                    user=db_user,
                )
                curated_results.append(result)
            except exceptions.NotFoundError:
                logger.warning(
                    f"Search result {result_uuid} not found during bulk curation"
                )
            except exceptions.PermissionDeniedError:
                logger.warning(
                    f"Permission denied for result {result_uuid} during bulk curation"
                )

        return curated_results

    async def export_to_annotation_project(
        self,
        session: AsyncSession,
        search_session: schemas.SearchSession,
        name: str,
        description: str,
        include_labels: list[str],
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.ExportToAnnotationProjectResponse:
        """Export labeled search results to a new annotation project.

        Creates a new annotation project and annotation tasks for each
        clip from results with the specified labels.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        search_session
            The search session containing the results.
        name
            Name for the new annotation project.
        description
            Description for the annotation project.
        include_labels
            List of labels to include (e.g., ['positive', 'positive_reference']).
        user
            The user performing the export.

        Returns
        -------
        schemas.ExportToAnnotationProjectResponse
            Response with the created annotation project details.
        """
        from echoroo.api.annotation_projects import annotation_projects
        from echoroo.api.clips import clips

        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to export results"
            )

        # Verify access
        db_session = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(search_session.uuid),
        )
        db_session = await self._eager_load_relationships(session, db_session)
        ml_project = await self._get_ml_project(session, db_session.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to export results from this session"
            )

        # Validate labels
        valid_labels = {label.value for label in models.SearchResultLabel}
        for label in include_labels:
            if label not in valid_labels:
                raise exceptions.InvalidDataError(
                    f"Invalid label '{label}'. Valid labels: {valid_labels}"
                )

        # Get results with specified labels
        label_enums = [models.SearchResultLabel(lbl) for lbl in include_labels]
        results_query = (
            select(models.SearchResult)
            .where(models.SearchResult.search_session_id == db_session.id)
            .where(models.SearchResult.label.in_(label_enums))
        )
        result = await session.execute(results_query)
        db_results = result.scalars().all()

        if not db_results:
            raise exceptions.InvalidDataError(
                f"No results found with labels: {include_labels}"
            )

        # Get the dataset_id from the ML project
        dataset_id = ml_project.dataset_id
        if dataset_id is None:
            # Try to get from dataset scopes
            if ml_project.dataset_scopes:
                dataset_id = ml_project.dataset_scopes[0].dataset_id
            else:
                raise exceptions.InvalidDataError(
                    "ML Project has no associated dataset"
                )

        # Create the annotation project
        annotation_project = await annotation_projects.create(
            session,
            name=name,
            description=description,
            annotation_instructions=(
                f"Review clips from search session: {db_session.name}. "
                f"These clips were selected based on labels: {', '.join(include_labels)}"
            ),
            user=db_user,
            dataset_id=dataset_id,
        )

        # Add the target tag to the annotation project
        if db_session.target_tag:
            tag_schema = schemas.Tag.model_validate(db_session.target_tag)
            await annotation_projects.add_tag(
                session,
                annotation_project,
                tag_schema,
                user=db_user,
            )

        # Create annotation tasks for each result's clip
        exported_count = 0
        for db_result in db_results:
            try:
                # Get the clip schema
                clip = await clips.get(session, db_result.clip.uuid)

                # Add task to annotation project
                await annotation_projects.add_task(
                    session,
                    annotation_project,
                    clip,
                    user=db_user,
                )

                # Update the search result to track which AP it was exported to
                await common.update_object(
                    session,
                    models.SearchResult,
                    models.SearchResult.uuid == db_result.uuid,
                    {"saved_to_annotation_project_id": annotation_project.id},
                )

                exported_count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to export result {db_result.uuid} to annotation project: {e}"
                )

        logger.info(
            f"Exported {exported_count} results from search session {search_session.uuid} "
            f"to annotation project {annotation_project.uuid}"
        )

        return schemas.ExportToAnnotationProjectResponse(
            annotation_project_uuid=annotation_project.uuid,
            annotation_project_name=annotation_project.name,
            exported_count=exported_count,
            message=f"Successfully exported {exported_count} clips to annotation project '{name}'",
        )

    async def get_annotation_projects(
        self,
        session: AsyncSession,
        ml_project_id: int,
        *,
        user: models.User | None = None,
    ) -> list[schemas.AnnotationProject]:
        """Get annotation projects created from this ML project's search sessions.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        ml_project_id
            The ML project ID.
        user
            Optional user for access control.

        Returns
        -------
        list[schemas.AnnotationProject]
            List of annotation projects linked to this ML project.
        """
        from echoroo.api.annotation_projects import annotation_projects

        db_user = await self._resolve_user(session, user)
        ml_project = await self._get_ml_project(session, ml_project_id)

        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"ML Project with id {ml_project_id} not found"
            )

        # Find all annotation projects that have search results from this ML project
        query = (
            select(models.AnnotationProject.uuid)
            .distinct()
            .join(
                models.SearchResult,
                models.SearchResult.saved_to_annotation_project_id
                == models.AnnotationProject.id,
            )
            .join(
                models.SearchSession,
                models.SearchSession.id == models.SearchResult.search_session_id,
            )
            .where(models.SearchSession.ml_project_id == ml_project_id)
        )

        result = await session.execute(query)
        ap_uuids = [row[0] for row in result.fetchall()]

        # Fetch full annotation project schemas
        ap_list = []
        for ap_uuid in ap_uuids:
            try:
                ap = await annotation_projects.get(session, ap_uuid, user=db_user)
                ap_list.append(ap)
            except exceptions.NotFoundError:
                pass

        return ap_list


search_sessions = SearchSessionAPI()
