"""Python API for Search Sessions with Active Learning support."""

import datetime
import logging
from typing import Sequence
from uuid import UUID

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI
from echoroo.api.ml_projects import can_edit_ml_project, can_view_ml_project
from echoroo.filters.base import Filter
from echoroo.ml.active_learning import (
    ActiveLearningConfig,
    compute_initial_samples,
    run_active_learning_iteration,
)

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
    """API for managing Search Sessions with Active Learning."""

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
                selectinload(self._model.target_tags).selectinload(
                    models.SearchSessionTargetTag.tag
                ),
                selectinload(self._model.ml_project),
                selectinload(self._model.created_by),
                selectinload(self._model.reference_sounds).selectinload(
                    models.ReferenceSound.ml_project
                ),
                selectinload(self._model.reference_sounds).selectinload(
                    models.ReferenceSound.tag
                ),
                selectinload(self._model.reference_sounds).selectinload(
                    models.ReferenceSound.clip
                ),
                selectinload(self._model.reference_sounds).selectinload(
                    models.ReferenceSound.embeddings
                ),
            )
        )
        result = await session.execute(stmt)
        return result.scalar_one()

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.SearchSession,
    ) -> schemas.SearchSession:
        """Build schema from database object with Active Learning fields."""
        db_obj = await self._eager_load_relationships(session, db_obj)

        # Get result counts
        total_results = await session.scalar(
            select(func.count(models.SearchResult.id)).where(
                models.SearchResult.search_session_id == db_obj.id
            )
        ) or 0

        # Count labeled results (has assigned_tag_id OR is_negative OR is_uncertain OR is_skipped)
        labeled_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(
                (models.SearchResult.assigned_tag_id.isnot(None))
                | (models.SearchResult.is_negative == True)
                | (models.SearchResult.is_uncertain == True)
                | (models.SearchResult.is_skipped == True)
            )
        ) or 0

        negative_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.is_negative == True)
        ) or 0

        uncertain_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.is_uncertain == True)
        ) or 0

        skipped_count = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.is_skipped == True)
        ) or 0

        # Get tag counts (assigned_tag_id -> count)
        tag_counts_query = (
            select(
                models.SearchResult.assigned_tag_id,
                func.count(models.SearchResult.id),
            )
            .where(models.SearchResult.search_session_id == db_obj.id)
            .where(models.SearchResult.assigned_tag_id.isnot(None))
            .group_by(models.SearchResult.assigned_tag_id)
        )
        tag_counts_result = await session.execute(tag_counts_query)
        tag_counts = {row[0]: row[1] for row in tag_counts_result.fetchall()}

        # Build target tags list
        target_tags = []
        for tt in db_obj.target_tags:
            target_tags.append(
                schemas.SearchSessionTargetTag(
                    tag_id=tt.tag_id,
                    tag=schemas.Tag.model_validate(tt.tag),
                    shortcut_key=tt.shortcut_key,
                )
            )

        # Build reference sounds list
        from echoroo.schemas.reference_sounds import ReferenceSound

        reference_sounds = []
        if hasattr(db_obj, "reference_sounds") and db_obj.reference_sounds:
            for ref_sound in db_obj.reference_sounds:
                # Map source enum
                source_map = {
                    models.ReferenceSoundSource.XENO_CANTO: schemas.ReferenceSoundSource.XENO_CANTO,
                    models.ReferenceSoundSource.CUSTOM_UPLOAD: schemas.ReferenceSoundSource.UPLOAD,
                    models.ReferenceSoundSource.DATASET_CLIP: schemas.ReferenceSoundSource.CLIP,
                }
                source = source_map.get(
                    ref_sound.source, schemas.ReferenceSoundSource.UPLOAD
                )

                ref_data = {
                    "uuid": ref_sound.uuid,
                    "id": ref_sound.id,
                    "name": ref_sound.name,
                    "ml_project_id": ref_sound.ml_project_id,
                    "ml_project_uuid": (
                        ref_sound.ml_project.uuid if ref_sound.ml_project else None
                    ),
                    "source": source,
                    "tag_id": ref_sound.tag_id,
                    "tag": (
                        schemas.Tag.model_validate(ref_sound.tag)
                        if ref_sound.tag
                        else None
                    ),
                    "start_time": ref_sound.start_time,
                    "end_time": ref_sound.end_time,
                    "duration": ref_sound.end_time - ref_sound.start_time,
                    "xeno_canto_id": ref_sound.xeno_canto_id,
                    "clip_id": ref_sound.clip_id,
                    "clip": (
                        schemas.Clip.model_validate(ref_sound.clip)
                        if ref_sound.clip
                        else None
                    ),
                    "audio_path": ref_sound.audio_path,
                    "embedding_count": len(ref_sound.embeddings) if ref_sound.embeddings else 0,
                    "is_active": ref_sound.is_active,
                    "created_by_id": ref_sound.created_by_id,
                    "created_on": ref_sound.created_on,
                }
                reference_sounds.append(ReferenceSound.model_validate(ref_data))

        unlabeled_count = total_results - labeled_count

        data = {
            "uuid": db_obj.uuid,
            "id": db_obj.id,
            "name": db_obj.name,
            "description": db_obj.description,
            "ml_project_id": db_obj.ml_project_id,
            "ml_project_uuid": db_obj.ml_project.uuid if db_obj.ml_project else None,
            "target_tags": target_tags,
            "easy_positive_k": db_obj.easy_positive_k,
            "boundary_n": db_obj.boundary_n,
            "boundary_m": db_obj.boundary_m,
            "others_p": db_obj.others_p,
            "distance_metric": db_obj.distance_metric,
            "current_iteration": db_obj.current_iteration,
            "is_search_complete": db_obj.is_search_complete,
            "total_results": total_results,
            "labeled_count": labeled_count,
            "unlabeled_count": unlabeled_count,
            "negative_count": negative_count,
            "uncertain_count": uncertain_count,
            "skipped_count": skipped_count,
            "tag_counts": tag_counts,
            "notes": db_obj.description,
            "reference_sounds": reference_sounds,
            "created_by_id": db_obj.created_by_id,
            "created_on": db_obj.created_on,
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
        """Create a new search session with auto-populated target tags."""
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

        # Validate reference sounds and collect unique tags
        reference_sound_int_ids = []
        unique_tag_ids: dict[int, None] = {}  # Using dict for ordered uniqueness

        for ref_id in data.reference_sound_ids:
            ref = await common.get_object(
                session,
                models.ReferenceSound,
                models.ReferenceSound.uuid == ref_id,
            )

            if ref.ml_project_id != ml_project_id:
                raise exceptions.InvalidDataError(
                    f"Reference sound {ref_id} does not belong to this ML project"
                )
            reference_sound_int_ids.append(ref.id)

            # Collect unique tag IDs
            if ref.tag_id is not None and ref.tag_id not in unique_tag_ids:
                unique_tag_ids[ref.tag_id] = None

        # Limit to 9 tags (for keyboard shortcuts 1-9)
        tag_ids_list = list(unique_tag_ids.keys())[:9]

        if not tag_ids_list:
            raise exceptions.InvalidDataError(
                "Reference sounds must have associated tags"
            )

        # Create the search session
        name = data.name or f"Search {datetime.datetime.now(datetime.UTC).isoformat()}"

        db_obj = await common.create_object(
            session,
            self._model,
            name=name,
            description=data.notes,
            ml_project_id=ml_project_id,
            easy_positive_k=data.easy_positive_k,
            boundary_n=data.boundary_n,
            boundary_m=data.boundary_m,
            others_p=data.others_p,
            distance_metric=data.distance_metric,
            current_iteration=0,
            is_search_complete=False,
            created_by_id=db_user.id,
        )

        # Create target tag entries with shortcut keys
        for shortcut_key, tag_id in enumerate(tag_ids_list, start=1):
            await common.create_object(
                session,
                models.SearchSessionTargetTag,
                search_session_id=db_obj.id,
                tag_id=tag_id,
                shortcut_key=shortcut_key,
            )

        # Link reference sounds
        for ref_id in reference_sound_int_ids:
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

    async def execute_initial_sampling(
        self,
        session: AsyncSession,
        search_session: schemas.SearchSession,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SearchSession:
        """Execute initial sampling: Easy Positives + Boundary + Others.

        Uses the active learning module to compute initial samples based on
        reference sound embeddings and sampling parameters.
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
                "Initial sampling has already been executed for this session"
            )

        # Get reference embeddings grouped by tag
        # Each reference sound can have multiple embeddings from sliding windows
        ref_embeddings_query = (
            select(
                models.ReferenceSound.tag_id,
                models.ReferenceSoundEmbedding.embedding,
            )
            .join(
                models.SearchSessionReferenceSound,
                models.SearchSessionReferenceSound.reference_sound_id
                == models.ReferenceSound.id,
            )
            .join(
                models.ReferenceSoundEmbedding,
                models.ReferenceSoundEmbedding.reference_sound_id
                == models.ReferenceSound.id,
            )
            .where(
                models.SearchSessionReferenceSound.search_session_id == db_obj.id
            )
        )
        result = await session.execute(ref_embeddings_query)
        rows = result.fetchall()

        if not rows:
            raise exceptions.InvalidDataError(
                "No reference sounds with embeddings found. "
                "Please compute embeddings for reference sounds first."
            )

        # Group embeddings by tag_id
        # Each tag may have multiple embeddings from multiple reference sounds
        # and multiple sliding windows per reference sound
        reference_embeddings_by_tag: dict[int, list[np.ndarray]] = {}
        for tag_id, embedding in rows:
            if tag_id not in reference_embeddings_by_tag:
                reference_embeddings_by_tag[tag_id] = []
            reference_embeddings_by_tag[tag_id].append(np.array(embedding))

        # Configure active learning
        config = ActiveLearningConfig(
            easy_positive_k=db_obj.easy_positive_k,
            boundary_n=db_obj.boundary_n,
            boundary_m=db_obj.boundary_m,
            others_p=db_obj.others_p,
        )

        # Compute initial samples
        samples = await compute_initial_samples(
            session=session,
            search_session_id=db_obj.id,
            ml_project_id=db_obj.ml_project_id,
            reference_embeddings_by_tag=reference_embeddings_by_tag,
            config=config,
            distance_metric=db_obj.distance_metric,
        )

        # Create search results from samples
        for rank, sample in enumerate(samples, start=1):
            await common.create_object(
                session,
                models.SearchResult,
                search_session_id=db_obj.id,
                clip_id=sample["clip_id"],
                similarity=sample["similarity"],
                rank=rank,
                sample_type=sample["sample_type"],
                source_tag_id=sample.get("source_tag_id"),
                iteration_added=0,
            )

        # Mark initial sampling as complete
        await common.update_object(
            session,
            self._model,
            self._get_pk_condition(search_session.uuid),
            is_search_complete=True,
        )

        logger.info(
            f"Search session {search_session.uuid} initial sampling completed "
            f"with {len(samples)} results"
        )

        return await self._build_schema(session, db_obj)

    async def run_iteration(
        self,
        session: AsyncSession,
        search_session: schemas.SearchSession,
        *,
        uncertainty_low: float = 0.25,
        uncertainty_high: float = 0.75,
        samples_per_iteration: int = 20,
        selected_tag_ids: list[int] | None = None,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SearchSession:
        """Run one iteration of active learning.

        Trains classifiers on labeled data and selects new samples from
        the uncertainty region.

        Parameters
        ----------
        uncertainty_low
            Lower bound of uncertainty region (default 0.25).
        uncertainty_high
            Upper bound of uncertainty region (default 0.75).
        samples_per_iteration
            Number of samples to add in this iteration (default 20).
        """
        db_user = await self._resolve_user(session, user)

        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(search_session.uuid),
        )
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to run iterations on this search"
            )

        if not db_obj.is_search_complete:
            raise exceptions.InvalidDataError(
                "Initial sampling must be completed before running iterations"
            )

        # Configure active learning with user-specified parameters
        config = ActiveLearningConfig(
            easy_positive_k=db_obj.easy_positive_k,
            boundary_n=db_obj.boundary_n,
            boundary_m=db_obj.boundary_m,
            others_p=db_obj.others_p,
            uncertainty_low=uncertainty_low,
            uncertainty_high=uncertainty_high,
            samples_per_iteration=samples_per_iteration,
        )

        # Run active learning iteration
        selected_tag_set = set(selected_tag_ids) if selected_tag_ids else None
        new_samples, metrics, score_distributions = await run_active_learning_iteration(
            session=session,
            search_session_id=db_obj.id,
            ml_project_id=db_obj.ml_project_id,
            config=config,
            selected_tag_ids=selected_tag_set,
        )

        # Get current max rank
        max_rank = await session.scalar(
            select(func.max(models.SearchResult.rank)).where(
                models.SearchResult.search_session_id == db_obj.id
            )
        ) or 0

        # Create new search results
        next_iteration = db_obj.current_iteration + 1
        for i, sample in enumerate(new_samples, start=1):
            await common.create_object(
                session,
                models.SearchResult,
                search_session_id=db_obj.id,
                clip_id=sample["clip_id"],
                similarity=0.0,  # Not similarity-based for AL samples
                rank=max_rank + i,
                sample_type=sample["sample_type"],
                source_tag_id=sample.get("source_tag_id"),
                model_score=sample.get("model_score"),
                iteration_added=next_iteration,
            )

        # Save score distributions to DB
        for dist in score_distributions:
            # Check if a distribution already exists for this tag and iteration
            existing_dist = await session.scalar(
                select(models.IterationScoreDistribution)
                .where(models.IterationScoreDistribution.search_session_id == db_obj.id)
                .where(models.IterationScoreDistribution.tag_id == dist["tag_id"])
                .where(models.IterationScoreDistribution.iteration == next_iteration)
            )

            if existing_dist:
                # Update existing record
                await common.update_object(
                    session,
                    models.IterationScoreDistribution,
                    models.IterationScoreDistribution.id == existing_dist.id,
                    None,
                    bin_counts=dist["bin_counts"],
                    bin_edges=dist["bin_edges"],
                    positive_count=dist["positive_count"],
                    negative_count=dist["negative_count"],
                    mean_score=dist["mean_score"],
                )
            else:
                # Create new record
                await common.create_object(
                    session,
                    models.IterationScoreDistribution,
                    search_session_id=db_obj.id,
                    tag_id=dist["tag_id"],
                    iteration=next_iteration,
                    bin_counts=dist["bin_counts"],
                    bin_edges=dist["bin_edges"],
                    positive_count=dist["positive_count"],
                    negative_count=dist["negative_count"],
                    mean_score=dist["mean_score"],
                )

        # Increment iteration counter
        await common.update_object(
            session,
            self._model,
            self._get_pk_condition(search_session.uuid),
            current_iteration=next_iteration,
        )

        logger.info(
            f"Search session {search_session.uuid} iteration {next_iteration} "
            f"completed with {len(new_samples)} new samples"
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

        from sqlalchemy.orm import selectinload

        combined_filters: list[Filter | ColumnExpressionArgument] = [
            models.SearchResult.search_session_id == search_session_id
        ]
        if filters:
            combined_filters.extend(filters)

        # Use eager loading to avoid N+1 queries
        db_objs, count = await common.get_objects(
            session,
            models.SearchResult,
            limit=limit,
            offset=offset,
            filters=combined_filters,
            sort_by=sort_by,
            options=[
                selectinload(models.SearchResult.clip).selectinload(
                    models.Clip.recording
                ),
                selectinload(models.SearchResult.assigned_tag),
                selectinload(models.SearchResult.source_tag),
            ],
        )

        results = []
        for db_obj in db_objs:
            clip_schema = schemas.Clip.model_validate(db_obj.clip)

            data = {
                "uuid": db_obj.uuid,
                "id": db_obj.id,
                "search_session_id": db_obj.search_session_id,
                "search_session_uuid": search_session.uuid,
                "clip_id": db_obj.clip_id,
                "clip": clip_schema,
                "similarity": db_obj.similarity,
                "rank": db_obj.rank,
                "assigned_tag_id": db_obj.assigned_tag_id,
                "assigned_tag": (
                    schemas.Tag.model_validate(db_obj.assigned_tag)
                    if db_obj.assigned_tag
                    else None
                ),
                "is_negative": db_obj.is_negative,
                "is_uncertain": db_obj.is_uncertain,
                "is_skipped": db_obj.is_skipped,
                "sample_type": db_obj.sample_type,
                "iteration_added": db_obj.iteration_added,
                "model_score": db_obj.model_score,
                "source_tag_id": db_obj.source_tag_id,
                "source_tag": (
                    schemas.Tag.model_validate(db_obj.source_tag)
                    if db_obj.source_tag
                    else None
                ),
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
        label_data: schemas.SearchResultLabelData,
        *,
        user: models.User | schemas.SimpleUser | None = None,
    ) -> schemas.SearchResult:
        """Label a search result with Active Learning label data."""
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

        # Validate assigned_tag_id if provided
        if label_data.assigned_tag_id is not None:
            tag = await session.get(models.Tag, label_data.assigned_tag_id)
            if tag is None:
                raise exceptions.NotFoundError(
                    f"Tag with id {label_data.assigned_tag_id} not found"
                )

        # Build update data
        update_data = {
            "assigned_tag_id": label_data.assigned_tag_id,
            "is_negative": label_data.is_negative,
            "is_uncertain": label_data.is_uncertain,
            "is_skipped": label_data.is_skipped,
            "labeled_by_id": db_user.id,
            "labeled_on": datetime.datetime.now(datetime.UTC),
        }
        if label_data.notes is not None:
            update_data["notes"] = label_data.notes

        db_result = await common.update_object(
            session,
            models.SearchResult,
            models.SearchResult.uuid == result_uuid,
            None,
            **update_data,
        )

        # Build and return schema
        await session.refresh(
            db_result, ["clip", "search_session", "assigned_tag", "source_tag"]
        )
        if db_result.clip:
            await session.refresh(db_result.clip, ["recording"])
        clip_schema = schemas.Clip.model_validate(db_result.clip)

        data = {
            "uuid": db_result.uuid,
            "id": db_result.id,
            "search_session_id": db_result.search_session_id,
            "search_session_uuid": search_session.uuid,
            "clip_id": db_result.clip_id,
            "clip": clip_schema,
            "similarity": db_result.similarity,
            "rank": db_result.rank,
            "assigned_tag_id": db_result.assigned_tag_id,
            "assigned_tag": (
                schemas.Tag.model_validate(db_result.assigned_tag)
                if db_result.assigned_tag
                else None
            ),
            "is_negative": db_result.is_negative,
            "is_uncertain": db_result.is_uncertain,
            "is_skipped": db_result.is_skipped,
            "sample_type": db_result.sample_type,
            "iteration_added": db_result.iteration_added,
            "model_score": db_result.model_score,
            "source_tag_id": db_result.source_tag_id,
            "source_tag": (
                schemas.Tag.model_validate(db_result.source_tag)
                if db_result.source_tag
                else None
            ),
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
        label_data: schemas.SearchResultLabelData,
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
                    session, result_uuid, label_data, user=db_user
                )
                updated_count += 1
            except exceptions.NotFoundError:
                logger.warning(
                    f"Search result {result_uuid} not found during bulk label"
                )
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

        # Labeled = has any label (tag, negative, uncertain, or skipped)
        labeled = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(
                (models.SearchResult.assigned_tag_id.isnot(None))
                | (models.SearchResult.is_negative == True)
                | (models.SearchResult.is_uncertain == True)
                | (models.SearchResult.is_skipped == True)
            )
        ) or 0

        negative = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.is_negative == True)
        ) or 0

        uncertain = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.is_uncertain == True)
        ) or 0

        skipped = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.is_skipped == True)
        ) or 0

        # Get tag counts
        tag_counts_query = (
            select(
                models.SearchResult.assigned_tag_id,
                func.count(models.SearchResult.id),
            )
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(models.SearchResult.assigned_tag_id.isnot(None))
            .group_by(models.SearchResult.assigned_tag_id)
        )
        tag_counts_result = await session.execute(tag_counts_query)
        tag_counts = {row[0]: row[1] for row in tag_counts_result.fetchall()}

        unlabeled = total - labeled
        progress_percent = (labeled / total * 100) if total > 0 else 0.0

        return schemas.SearchProgress(
            total=total,
            labeled=labeled,
            unlabeled=unlabeled,
            negative=negative,
            uncertain=uncertain,
            skipped=skipped,
            tag_counts=tag_counts,
            progress_percent=progress_percent,
        )

    async def bulk_curate(
        self,
        session: AsyncSession,
        search_session: schemas.SearchSession,
        result_uuids: list[UUID],
        assigned_tag_id: int,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> list[schemas.SearchResult]:
        """Bulk curate search results by assigning a tag.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        search_session
            The search session containing the results.
        result_uuids
            UUIDs of results to curate.
        assigned_tag_id
            Tag ID to assign to all results.
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

        # Validate tag exists
        tag = await session.get(models.Tag, assigned_tag_id)
        if tag is None:
            raise exceptions.NotFoundError(
                f"Tag with id {assigned_tag_id} not found"
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

        # Create label data with assigned tag
        label_data = schemas.SearchResultLabelData(
            assigned_tag_id=assigned_tag_id,
            is_negative=False,
            is_uncertain=False,
            is_skipped=False,
        )

        # Update results
        curated_results = []
        for result_uuid in result_uuids:
            try:
                result = await self.label_result(
                    session,
                    result_uuid,
                    label_data,
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
        include_labeled: bool = True,
        include_tag_ids: list[int] | None = None,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.ExportToAnnotationProjectResponse:
        """Export labeled search results to a new annotation project.

        Creates a new annotation project and annotation tasks for each
        clip from results with assigned tags.

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
        include_labeled
            Whether to include results with assigned tags.
        include_tag_ids
            Optional list of specific tag IDs to include.
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

        # Build query for results to export
        results_query = select(models.SearchResult).where(
            models.SearchResult.search_session_id == db_session.id
        )

        if include_labeled:
            if include_tag_ids:
                # Filter to specific tags
                results_query = results_query.where(
                    models.SearchResult.assigned_tag_id.in_(include_tag_ids)
                )
            else:
                # Include all results with assigned tags
                results_query = results_query.where(
                    models.SearchResult.assigned_tag_id.isnot(None)
                )

        result = await session.execute(results_query)
        db_results = result.scalars().all()

        if not db_results:
            raise exceptions.InvalidDataError(
                "No results found matching the export criteria"
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
            ),
            user=db_user,
            dataset_id=dataset_id,
        )

        # Add target tags to the annotation project
        for tt in db_session.target_tags:
            tag_schema = schemas.Tag.model_validate(tt.tag)
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
                # Load the clip
                await session.refresh(db_result, ["clip"])

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
                    f"Failed to export result {db_result.uuid} "
                    f"to annotation project: {e}"
                )

        logger.info(
            f"Exported {exported_count} results from search session "
            f"{search_session.uuid} to annotation project {annotation_project.uuid}"
        )

        return schemas.ExportToAnnotationProjectResponse(
            annotation_project_uuid=annotation_project.uuid,
            annotation_project_name=annotation_project.name,
            exported_count=exported_count,
            message=(
                f"Successfully exported {exported_count} clips "
                f"to annotation project '{name}'"
            ),
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

    async def get_score_distribution(
        self,
        session: AsyncSession,
        ml_project_uuid: UUID,
        search_session_uuid: UUID,
        *,
        user: models.User | None = None,
    ) -> schemas.ScoreDistributionResponse:
        """Get saved score distributions from DB.

        Retrieves the score distributions computed during active learning
        iterations, providing histogram data for visualization.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        ml_project_uuid
            UUID of the ML project (used for access control).
        search_session_uuid
            UUID of the search session.
        user
            Optional user for access control.

        Returns
        -------
        schemas.ScoreDistributionResponse
            Response containing score distributions for each tag and iteration.
        """
        db_user = await self._resolve_user(session, user)

        # Get the search session
        db_obj = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(search_session_uuid),
        )

        # Verify access
        ml_project = await self._get_ml_project(session, db_obj.ml_project_id)
        if not await can_view_ml_project(session, ml_project, db_user):
            raise exceptions.NotFoundError(
                f"Search session with uuid {search_session_uuid} not found"
            )

        # Fetch score distributions from DB
        query = (
            select(models.IterationScoreDistribution)
            .where(models.IterationScoreDistribution.search_session_id == db_obj.id)
            .order_by(
                models.IterationScoreDistribution.iteration,
                models.IterationScoreDistribution.tag_id,
            )
            .options(selectinload(models.IterationScoreDistribution.tag))
        )

        result = await session.execute(query)
        db_distributions = result.scalars().all()

        # Build response
        distributions = []
        for dist in db_distributions:
            tag_dist = schemas.TagScoreDistribution(
                tag_id=dist.tag_id,
                tag_name=dist.tag.value,
                iteration=dist.iteration,
                bin_counts=dist.bin_counts,
                bin_edges=dist.bin_edges,
                positive_count=dist.positive_count,
                negative_count=dist.negative_count,
                mean_score=dist.mean_score,
            )
            distributions.append(tag_dist)

        return schemas.ScoreDistributionResponse(distributions=distributions)


search_sessions = SearchSessionAPI()
