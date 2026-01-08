"""Python API for Search Sessions with Active Learning support."""

import datetime
import logging
from typing import Sequence
from uuid import UUID

import numpy as np
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnExpressionArgument

from echoroo import exceptions, models, schemas
from echoroo.api import common
from echoroo.api.common import BaseAPI, UserResolutionMixin
from echoroo.api.ml_projects import can_edit_ml_project, can_view_ml_project
from echoroo.filters.base import Filter
from echoroo.ml.active_learning import (
    ActiveLearningConfig,
    MIN_EMBEDDING_NORM,
    compute_initial_samples,
    run_active_learning_iteration,
)

__all__ = [
    "SearchSessionAPI",
    "search_sessions",
]

logger = logging.getLogger(__name__)


async def compute_percentiles_for_session(
    session: AsyncSession,
    search_session_id: int,
) -> dict[int, float]:
    """Compute percentile ranks for all results in a session.

    Uses the dataset_rank (stored in rank column) to calculate percentile
    relative to the full dataset, not just the selected samples.

    rank=1 means top 0.x% (most similar to references)
    Higher rank = lower percentile (less similar)

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession.
    search_session_id
        ID of the search session.

    Returns
    -------
    dict[int, float]
        Mapping from result ID to percentile (0-100).
        Higher percentile = more similar to references.
    """
    # Get search session to find ml_project_id
    search_session_query = select(models.SearchSession.ml_project_id).where(
        models.SearchSession.id == search_session_id
    )
    result = await session.execute(search_session_query)
    row = result.fetchone()
    if not row:
        return {}

    ml_project_id = row[0]

    # Count total clips in the dataset (using the same query as active_learning)
    count_query = text("""
        SELECT COUNT(DISTINCT ce.clip_id)
        FROM clip_embedding ce
        JOIN clip c ON ce.clip_id = c.id
        JOIN recording r ON c.recording_id = r.id
        JOIN dataset_recording dr ON r.id = dr.recording_id
        JOIN ml_project_dataset_scope mpds ON dr.dataset_id = mpds.dataset_id
        JOIN foundation_model_run fmr ON mpds.foundation_model_run_id = fmr.id
        WHERE mpds.ml_project_id = :ml_project_id
          AND fmr.model_run_id = ce.model_run_id
    """)
    result = await session.execute(count_query, {"ml_project_id": ml_project_id})
    total_clips = result.scalar() or 1  # Avoid division by zero

    # Get all results with their dataset rank
    query = select(
        models.SearchResult.id,
        models.SearchResult.rank,  # This is dataset_rank
    ).where(
        models.SearchResult.search_session_id == search_session_id
    )

    result = await session.execute(query)
    all_results = [(row[0], row[1]) for row in result.fetchall()]

    if not all_results:
        return {}

    # Calculate percentile based on dataset rank
    # rank=1 -> percentile close to 100 (top of dataset)
    # rank=total_clips -> percentile close to 0 (bottom of dataset)
    percentiles = {}
    for result_id, dataset_rank in all_results:
        # Percentile: (total_clips - rank + 1) / total_clips * 100
        percentile = (total_clips - dataset_rank + 1) / total_clips * 100
        percentiles[result_id] = percentile

    return percentiles


class SearchSessionAPI(
    BaseAPI[
        UUID,
        models.SearchSession,
        schemas.SearchSession,
        schemas.SearchSessionCreate,
        schemas.SearchSession,
    ],
    UserResolutionMixin,
):
    """API for managing Search Sessions with Active Learning."""

    _model = models.SearchSession
    _schema = schemas.SearchSession

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

    async def _build_schema(
        self,
        session: AsyncSession,
        db_obj: models.SearchSession,
    ) -> schemas.SearchSession:
        """Build schema using SchemaBuilder service."""
        from echoroo.services.search_sessions.schema_builder import SearchSessionSchemaBuilder

        builder = SearchSessionSchemaBuilder(session)
        return await builder.build_schema(db_obj)

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
        samples, total_clips = await compute_initial_samples(
            session=session,
            search_session_id=db_obj.id,
            ml_project_id=db_obj.ml_project_id,
            reference_embeddings_by_tag=reference_embeddings_by_tag,
            config=config,
            distance_metric=db_obj.distance_metric,
        )

        # Create search results from samples
        # Use dataset_rank (rank in full dataset) for percentile calculation
        for sample in samples:
            await common.create_object(
                session,
                models.SearchResult,
                search_session_id=db_obj.id,
                clip_id=sample["clip_id"],
                similarity=sample["similarity"],
                rank=sample["dataset_rank"],  # Store dataset rank for percentile
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
        classifier_type: str = "logistic_regression",
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
        classifier_type
            Classifier type to use for this iteration (default logistic_regression).
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
            classifier_type=classifier_type,
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
                selectinload(models.SearchResult.source_tag),
                selectinload(models.SearchResult.assigned_tags_rel).selectinload(
                    models.SearchResultTag.tag
                ),
            ],
        )

        # Compute percentiles for all results in this session
        percentiles = await compute_percentiles_for_session(
            session, search_session_id
        )

        # Get distance metric for this session
        distance_metric = search_session.distance_metric

        results = []
        for db_obj in db_objs:
            clip_schema = schemas.Clip.model_validate(db_obj.clip)

            # Build multi-label tag data
            assigned_tag_ids = [rel.tag_id for rel in db_obj.assigned_tags_rel]
            assigned_tags = [
                schemas.Tag.model_validate(rel.tag) for rel in db_obj.assigned_tags_rel
            ]

            # Compute raw_score from similarity
            # For cosine: raw_score = similarity (already 0-1)
            # For euclidean: similarity = 1/(1+d), so d = 1/similarity - 1
            raw_score = db_obj.raw_score
            if raw_score is None:
                if distance_metric == "euclidean" and db_obj.similarity > 0:
                    # Reverse the transformation to get original distance
                    raw_score = (1.0 / db_obj.similarity) - 1.0
                else:
                    # For cosine, raw_score equals similarity
                    raw_score = db_obj.similarity

            data = {
                "uuid": db_obj.uuid,
                "id": db_obj.id,
                "search_session_id": db_obj.search_session_id,
                "search_session_uuid": search_session.uuid,
                "clip_id": db_obj.clip_id,
                "clip": clip_schema,
                "similarity": db_obj.similarity,
                "rank": db_obj.rank,
                # Multi-label support
                "assigned_tag_ids": assigned_tag_ids,
                "assigned_tags": assigned_tags,
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
                # Score display fields
                "raw_score": raw_score,
                "score_percentile": percentiles.get(db_obj.id),
                "result_distance_metric": distance_metric,
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

        # Get all tag IDs to assign (multi-label support)
        tag_ids = label_data.get_tag_ids()

        # Validate all tag IDs
        for tag_id in tag_ids:
            tag = await session.get(models.Tag, tag_id)
            if tag is None:
                raise exceptions.NotFoundError(f"Tag with id {tag_id} not found")

        # Build update data
        update_data = {
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

        # Update search_result_tag junction table for multi-label support
        # Delete existing tag assignments
        await session.execute(
            delete(models.SearchResultTag).where(
                models.SearchResultTag.search_result_id == db_result.id
            )
        )

        # Add new tag assignments
        for tag_id in tag_ids:
            new_tag_rel = models.SearchResultTag(
                search_result_id=db_result.id,
                tag_id=tag_id,
            )
            session.add(new_tag_rel)

        # Build and return schema
        await session.refresh(
            db_result,
            ["clip", "search_session", "assigned_tag", "source_tag", "assigned_tags_rel"],
        )
        if db_result.clip:
            await session.refresh(db_result.clip, ["recording"])
        clip_schema = schemas.Clip.model_validate(db_result.clip)

        # Build multi-label tag data
        assigned_tag_ids = [rel.tag_id for rel in db_result.assigned_tags_rel]
        assigned_tags = [
            schemas.Tag.model_validate(rel.tag) for rel in db_result.assigned_tags_rel
        ]

        data = {
            "uuid": db_result.uuid,
            "id": db_result.id,
            "search_session_id": db_result.search_session_id,
            "search_session_uuid": search_session.uuid,
            "clip_id": db_result.clip_id,
            "clip": clip_schema,
            "similarity": db_result.similarity,
            "rank": db_result.rank,
            # Multi-label support
            "assigned_tag_ids": assigned_tag_ids,
            "assigned_tags": assigned_tags,
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

        # Labeled = has any label (tag via junction table, negative, uncertain, or skipped)
        has_tags_subquery = (
            select(models.SearchResultTag.search_result_id)
            .where(
                models.SearchResultTag.search_result_id == models.SearchResult.id
            )
            .exists()
        )
        labeled = await session.scalar(
            select(func.count(models.SearchResult.id))
            .where(models.SearchResult.search_session_id == search_session_id)
            .where(
                has_tags_subquery
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

        # Get tag counts from junction table
        tag_counts_query = (
            select(
                models.SearchResultTag.tag_id,
                func.count(func.distinct(models.SearchResultTag.search_result_id)),
            )
            .join(
                models.SearchResult,
                models.SearchResultTag.search_result_id == models.SearchResult.id,
            )
            .where(models.SearchResult.search_session_id == search_session_id)
            .group_by(models.SearchResultTag.tag_id)
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
            assigned_tag_ids=[assigned_tag_id],
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
        from echoroo.services.search_sessions.export import SearchSessionExportService

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
            options=[
                selectinload(self._model.target_tags).selectinload(
                    models.SearchSessionTargetTag.tag
                ),
            ],
        )
        ml_project = await self._get_ml_project(session, db_session.ml_project_id)

        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to export results from this session"
            )

        # Create export request data
        export_data = schemas.ExportToAnnotationProjectRequest(
            name=name,
            description=description,
            include_labeled=include_labeled,
            include_tag_ids=include_tag_ids,
        )

        # Use service for business logic
        service = SearchSessionExportService(session)
        return await service.export_to_annotation_project(
            search_session=db_session,
            data=export_data,
            user=db_user,
            ml_project=ml_project,
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

    async def finalize(
        self,
        session: AsyncSession,
        search_session: schemas.SearchSession,
        request: schemas.FinalizeRequest,
        *,
        user: models.User | schemas.SimpleUser,
    ) -> schemas.FinalizeResponse:
        """Finalize a search session using FinalizationService.

        Delegates to SearchSessionFinalizationService for business logic.

        Parameters
        ----------
        session
            SQLAlchemy AsyncSession.
        search_session
            The search session to finalize.
        request
            Finalize request with model name, type, and options.
        user
            The user performing the finalize.

        Returns
        -------
        schemas.FinalizeResponse
            Response with created model details and counts.
        """
        from echoroo.services.search_sessions.finalization import (
            SearchSessionFinalizationService,
        )

        db_user = await self._resolve_user(session, user)
        if db_user is None:
            raise exceptions.PermissionDeniedError(
                "Authentication required to finalize sessions"
            )

        # Get search session model instance
        db_session = await common.get_object(
            session,
            self._model,
            self._get_pk_condition(search_session.uuid),
        )

        # Verify access
        ml_project = await self._get_ml_project(session, db_session.ml_project_id)
        if not await can_edit_ml_project(session, ml_project, db_user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to finalize this search session"
            )

        # Use finalization service for business logic
        service = SearchSessionFinalizationService(session)
        return await service.finalize(
            search_session=db_session,
            data=request,
            user=db_user,
        )


search_sessions = SearchSessionAPI()
