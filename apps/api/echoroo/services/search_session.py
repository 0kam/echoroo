"""SearchSession service for persisting and managing batch search sessions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import get_db
from echoroo.models.enums import DetectionStatus, SearchSessionStatus
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.search_query_embedding import SearchQueryEmbedding
from echoroo.models.search_session import SearchSession


def _generate_session_name(species_config: list[dict[str, object]]) -> str:
    """Generate an auto-session-name from the species config.

    Format:
      - 1-3 species: "name1, name2, name3 - YYYY-MM-DD"
      - 4+ species:  "name1, name2, name3... - YYYY-MM-DD"
    Falls back to "Unknown" for any species missing both common_name and
    scientific_name. Date uses UTC.

    Args:
        species_config: List of species configuration dicts

    Returns:
        Auto-generated session name string
    """
    species_names: list[str] = []
    for sp_cfg in species_config:
        raw_label = sp_cfg.get("common_name") or sp_cfg.get("scientific_name", "Unknown")
        label = str(raw_label) if raw_label is not None else "Unknown"
        species_names.append(label)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    if len(species_names) > 3:
        return f"{', '.join(species_names[:3])}... - {date_str}"
    return f"{', '.join(species_names)} - {date_str}"


class SearchSessionService:
    """Service for creating and managing search session records.

    Handles persistence, retrieval, and review count aggregation for
    batch similarity search sessions.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def create_session(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        model_name: str,
        species_config: list[dict[str, object]],
        parameters: dict[str, object],
        celery_job_id: str,
        reference_audio_keys: list[str] | None = None,
        name: str | None = None,
    ) -> SearchSession:
        """Create a new search session record.

        Auto-generates a name from species config if none is provided.
        The name format is "Species1, Species2 - YYYY-MM-DD", truncated
        to three species with "..." if more are present.

        Args:
            project_id: Owning project UUID
            user_id: User initiating the search
            model_name: ML model used for embeddings
            species_config: List of species configuration dicts
            parameters: Search parameters dict
            celery_job_id: Celery task ID for tracking
            reference_audio_keys: Optional S3 keys of uploaded reference audio
            name: Optional custom name; auto-generated if omitted

        Returns:
            Newly created SearchSession (not yet committed)
        """
        if not name:
            name = _generate_session_name(species_config)

        session = SearchSession(
            project_id=project_id,
            user_id=user_id,
            name=name,
            status=SearchSessionStatus.PENDING,
            model_name=model_name,
            parameters=parameters,
            species_config=species_config,
            celery_job_id=celery_job_id,
            reference_audio_keys=reference_audio_keys,
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_session(
        self, session_id: uuid.UUID, project_id: uuid.UUID
    ) -> SearchSession | None:
        """Get a session by ID, scoped to a project.

        Args:
            session_id: Session UUID to look up
            project_id: Project UUID for access scoping

        Returns:
            SearchSession if found, None otherwise
        """
        result = await self.db.execute(
            select(SearchSession).where(
                SearchSession.id == session_id,
                SearchSession.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_sessions(
        self,
        project_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SearchSession], int]:
        """List sessions for a project ordered by creation date descending.

        Args:
            project_id: Project UUID to filter sessions
            limit: Maximum number of results to return
            offset: Number of results to skip for pagination

        Returns:
            Tuple of (sessions list, total count)
        """
        # Count query
        count_result = await self.db.execute(
            select(func.count())
            .select_from(SearchSession)
            .where(SearchSession.project_id == project_id)
        )
        total = count_result.scalar_one()

        # Data query
        result = await self.db.execute(
            select(SearchSession)
            .where(SearchSession.project_id == project_id)
            .order_by(SearchSession.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all()), total

    async def delete_session(
        self, session_id: uuid.UUID, project_id: uuid.UUID
    ) -> bool:
        """Delete a session and all its data.

        Args:
            session_id: Session UUID to delete
            project_id: Project UUID for access scoping

        Returns:
            True if the session existed and was deleted, False if not found
        """
        session = await self.get_session(session_id, project_id)
        if not session:
            return False
        await self.db.delete(session)
        await self.db.flush()
        return True

    async def get_session_results_with_review_status(
        self,
        session_id: uuid.UUID,
        project_id: uuid.UUID,
        session: SearchSession | None = None,
    ) -> dict[str, object] | None:
        """Get results JSONB merged with annotation review statuses.

        Fetches the stored search results and merges per-match review status
        from the annotations table, so the caller gets live review data without
        needing to re-run the search.

        Args:
            session_id: Session UUID to retrieve
            project_id: Project UUID for access scoping
            session: Optional pre-fetched SearchSession to avoid a redundant
                database query when the caller already has the object

        Returns:
            Results dict with review_status and annotation_id fields injected
            into each match, or None if session not found or has no results
        """
        if session is None:
            session = await self.get_session(session_id, project_id)
        if not session or not session.results:
            return None

        # Fetch all annotations linked to this session
        ann_result = await self.db.execute(
            select(
                RecordingAnnotation.recording_id,
                RecordingAnnotation.start_time,
                RecordingAnnotation.end_time,
                RecordingAnnotation.status,
                RecordingAnnotation.tag_id,
                RecordingAnnotation.id,
            ).where(RecordingAnnotation.search_session_id == session_id)
        )
        annotations = ann_result.all()

        # Build lookup: (recording_id, tag_id, start_time_rounded) → review info
        annotation_lookup: dict[tuple[str, str | None, float | None], dict[str, object]] = {}
        for ann in annotations:
            key = (
                str(ann.recording_id),
                str(ann.tag_id) if ann.tag_id else None,
                round(ann.start_time, 2) if ann.start_time is not None else None,
            )
            annotation_lookup[key] = {
                "annotation_id": str(ann.id),
                "status": ann.status.value if ann.status else "unreviewed",
            }

        # Deep-copy results dict and inject review status into each match
        results: dict[str, object] = dict(session.results)
        raw_results = results.get("results")
        if isinstance(raw_results, dict):
            for _species_key, species_data in raw_results.items():
                if isinstance(species_data, dict) and "matches" in species_data:
                    for match in species_data["matches"]:
                        key = (
                            match.get("recording_id"),
                            species_data.get("tag_id"),
                            round(match.get("start_time", 0.0), 2),
                        )
                        review = annotation_lookup.get(key)
                        if review:
                            match["review_status"] = review["status"]
                            match["annotation_id"] = review["annotation_id"]
                        else:
                            match["review_status"] = "unreviewed"

        return results

    async def update_review_counts(self, session_id: uuid.UUID) -> None:
        """Recalculate confirmed and rejected counts from linked annotations.

        Should be called whenever an annotation linked to this session has
        its review status changed.

        Args:
            session_id: Session UUID whose counts should be recalculated
        """
        result = await self.db.execute(
            select(
                func.count()
                .filter(RecordingAnnotation.status == DetectionStatus.CONFIRMED)
                .label("confirmed"),
                func.count()
                .filter(RecordingAnnotation.status == DetectionStatus.REJECTED)
                .label("rejected"),
            ).where(RecordingAnnotation.search_session_id == session_id)
        )
        row = result.one()

        await self.db.execute(
            update(SearchSession)
            .where(SearchSession.id == session_id)
            .values(confirmed_count=row.confirmed, rejected_count=row.rejected)
        )
        await self.db.flush()


    async def update_name(
        self,
        session: SearchSession,
        name: str,
    ) -> SearchSession:
        """Update the name of a search session.

        Args:
            session: SearchSession instance to update
            name: New name for the session

        Returns:
            Updated and refreshed SearchSession instance
        """
        session.name = name
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def get_by_job_id(
        self,
        job_id: str,
        project_id: UUID,
    ) -> SearchSession | None:
        """Find a session by its Celery job ID, scoped to the given project.

        Args:
            job_id: Celery task ID string
            project_id: Project UUID for access scoping

        Returns:
            SearchSession if found, None otherwise
        """
        result = await self.db.execute(
            select(SearchSession).where(
                SearchSession.celery_job_id == job_id,
                SearchSession.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def mark_completed(
        self,
        session: SearchSession,
        raw_results: dict[str, object],
    ) -> None:
        """Transition a session to COMPLETED status and persist results.

        Args:
            session: SearchSession instance to update
            raw_results: Raw Celery task result dict to store
        """
        session.status = SearchSessionStatus.COMPLETED
        session.results = raw_results
        session.result_count = cast(int, raw_results.get("total_matches", 0))
        session.completed_at = datetime.now(UTC)
        await self.db.flush()

    async def mark_failed(
        self,
        session: SearchSession,
        error_message: str,
    ) -> None:
        """Transition a session to FAILED status and record the error.

        Args:
            session: SearchSession instance to update
            error_message: Description of the failure
        """
        session.status = SearchSessionStatus.FAILED
        session.error_message = error_message
        session.completed_at = datetime.now(UTC)
        await self.db.flush()

    async def reset_for_rerun(
        self,
        session: SearchSession,
        job_id: str,
        model_name: str,
        parameters: dict[str, object],
        species_config: list[dict[str, object]],
        reference_audio_keys: list[str] | None,
    ) -> SearchSession:
        """Reset a session's fields for a re-run and clear its prior run state.

        Clears stored results, counters, error state, the session's review
        annotations, and the session's stored query embeddings (the reference-
        audio vectors keyed by ``search_session_id``). The query embeddings are
        regenerated from scratch by the dispatched re-run task, so clearing the
        stale rows here prevents old and new reference vectors from accumulating
        and corrupting downstream search/training reads. Updates the session with
        the new job ID, model, parameters, and species configuration, then auto-
        generates a new name.

        Args:
            session: SearchSession instance to reset
            job_id: New Celery job ID for the re-run
            model_name: ML model name for the new run
            parameters: Updated search parameters dict
            species_config: Updated species configuration list (with s3_keys)
            reference_audio_keys: Updated list of S3 keys for reference audio

        Returns:
            Updated SearchSession (not yet committed)
        """
        # Delete existing annotations linked to this session. Use the ORM model
        # (RecordingAnnotation → "recording_annotations") that the rest
        # of this service queries, so the generated DELETE targets the table that
        # actually carries ``search_session_id``. Scoped to this session only.
        await self.db.execute(
            delete(RecordingAnnotation).where(
                RecordingAnnotation.search_session_id == session.id
            )
        )

        # Clear the session's stored query embeddings (reference-audio vectors).
        # The session row is reused across re-runs, and the re-run task only
        # *appends* fresh vectors, so without this delete the old vectors would
        # accumulate and later be mixed with the new ones by readers that load
        # every row for this search_session_id (api/v1/custom_models.py seed
        # sampling, workers/classifier_tasks.py training). Scoped to this session
        # only; runs in the same transaction before the re-run regenerates them.
        await self.db.execute(
            delete(SearchQueryEmbedding).where(
                SearchQueryEmbedding.search_session_id == session.id
            )
        )

        session.status = SearchSessionStatus.PENDING
        session.results = None
        session.result_count = 0
        session.confirmed_count = 0
        session.rejected_count = 0
        session.error_message = None
        session.started_at = None
        session.completed_at = None
        session.celery_job_id = job_id
        session.model_name = model_name
        session.parameters = parameters
        session.species_config = cast(list[object], species_config)
        session.reference_audio_keys = reference_audio_keys if reference_audio_keys else None

        # Auto-generate a new name from species config
        session.name = _generate_session_name(species_config)

        await self.db.flush()
        return session


async def get_search_session_service(
    db: AsyncSession = Depends(get_db),
) -> SearchSessionService:
    """FastAPI dependency for SearchSessionService.

    Args:
        db: Injected async database session

    Returns:
        SearchSessionService instance bound to the session
    """
    return SearchSessionService(db)


SearchSessionServiceDep = Annotated[SearchSessionService, Depends(get_search_session_service)]
