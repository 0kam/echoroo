"""Detection annotation service for detection review business logic."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select as sa_select
from sqlalchemy.exc import IntegrityError

from echoroo.core.pagination import paginate
from echoroo.models.annotation_vote import AnnotationVote
from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.models.enums import (
    DetectionSource,
    DetectionStatus,
    SignalQuality,
    VoteType,
)

# The rich-shape detection review service (list / get / create / confirm /
# reject / change_species / species_summary / temporal_summary) operates on
# the :class:`RecordingAnnotation` ORM, whose table
# ``recording_annotations`` exists and is live at runtime (materialised by
# migration ``0011_recording_annotations_placeholder`` and renamed from its
# transitional ``recording_annotations_DEFERRED`` placeholder name by migration
# ``0029_rename_recording_annotations_final``). The vote
# endpoints (``cast_vote`` / ``delete_vote`` / ``get_vote_summary``) bypass
# this service and go through ``services/annotation_vote.py``, where votes are
# keyed on recording-annotation (``recording_annotations``) ids.
from echoroo.models.recording_annotation import (
    CUSTOM_SVM_DEDUP_INDEX_NAME,
    RecordingAnnotation,
)
from echoroo.repositories.annotation import AnnotationRepository, TemporalSummaryRow
from echoroo.repositories.annotation_vote import AnnotationVoteRepository
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.repositories.recording import RecordingRepository
from echoroo.repositories.tag import TagRepository
from echoroo.schemas.annotation_vote import DetectionVoteCounts
from echoroo.schemas.detection import (
    ChangeSpeciesRequest,
    ConfirmRequest,
    DetectionCreate,
    DetectionListResponse,
    DetectionResponse,
    DetectionTemporalDataResponse,
    HourlyDetection,
    SpeciesSummaryItem,
    SpeciesSummaryResponse,
    SpeciesTemporalData,
)
from echoroo.schemas.tag import TagResponse
from echoroo.services.vernacular import resolve_vernacular_names


class DetectionService:
    """Service for detection annotation management business logic."""

    def __init__(
        self,
        annotation_repo: AnnotationRepository,
        confirmed_region_repo: ConfirmedRegionRepository,
        vote_repo: AnnotationVoteRepository | None = None,
        recording_repo: RecordingRepository | None = None,
        tag_repo: TagRepository | None = None,
        detection_run_repo: DetectionRunRepository | None = None,
    ) -> None:
        """Initialize service with repositories.

        Args:
            annotation_repo: Annotation repository instance
            confirmed_region_repo: ConfirmedRegion repository instance
            vote_repo: Optional AnnotationVoteRepository for loading vote counts
            recording_repo: Optional RecordingRepository for project ownership checks
            tag_repo: Optional TagRepository for project ownership checks
            detection_run_repo: Optional DetectionRunRepository for project ownership checks
        """
        self.annotation_repo = annotation_repo
        self.confirmed_region_repo = confirmed_region_repo
        self.vote_repo = vote_repo
        self.recording_repo = recording_repo or RecordingRepository(annotation_repo.db)
        self.tag_repo = tag_repo or TagRepository(annotation_repo.db)
        self.detection_run_repo = detection_run_repo or DetectionRunRepository(
            annotation_repo.db
        )

    async def list_detections(
        self,
        project_id: UUID,
        tag_id: UUID | None = None,
        status: DetectionStatus | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        dataset_id: UUID | None = None,
        recording_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
        current_user_id: UUID | None = None,
        min_votes: int = 2,
        threshold: float = 0.667,
        locale: str = "en",
    ) -> DetectionListResponse:
        """List detections for a project with optional filtering and pagination.

        Args:
            project_id: Project's UUID
            tag_id: Optional tag filter
            status: Optional review status filter
            confidence_min: Optional minimum confidence filter
            confidence_max: Optional maximum confidence filter
            dataset_id: Optional dataset filter
            recording_id: Optional recording filter
            detection_run_id: Optional detection run filter
            page: Page number (1-indexed)
            page_size: Items per page
            current_user_id: Optional current user ID for including their vote
            min_votes: Minimum votes required for consensus (from project settings)
            threshold: Consensus agreement threshold (from project settings)
            locale: Locale code used to resolve vernacular names on embedded tags

        Returns:
            Paginated detection list response
        """
        pagination = paginate(page, page_size)

        annotations, total = await self.annotation_repo.list_annotations(
            project_id=project_id,
            tag_id=tag_id,
            status=status,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            dataset_id=dataset_id,
            recording_id=recording_id,
            detection_run_id=detection_run_id,
            page=pagination.page,
            page_size=pagination.page_size,
        )

        # Batch-load vote counts for all annotations in one query
        vote_counts_map = await self._batch_load_vote_counts(
            [a.id for a in annotations],
            current_user_id=current_user_id,
            min_votes=min_votes,
            threshold=threshold,
        )

        # Batch-resolve vernacular names for all distinct taxon IDs so the
        # embedded TagResponse objects can be populated without N+1 queries.
        taxon_ids = [
            a.tag.taxon_id
            for a in annotations
            if a.tag is not None and a.tag.taxon_id is not None
        ]
        vernacular_map = await resolve_vernacular_names(
            self.annotation_repo.db, taxon_ids, locale
        )

        items = [
            self._to_response(a, vote_counts_map.get(a.id), vernacular_map)
            for a in annotations
        ]

        return DetectionListResponse(
            items=items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pagination.total_pages(total),
        )

    async def _resolve_vernacular_names(
        self,
        taxon_ids: list[UUID],
        locale: str,
    ) -> dict[UUID, str]:
        """Batch-resolve vernacular names for a list of taxon IDs.

        Thin wrapper around :func:`resolve_vernacular_names` kept for
        backwards compatibility with internal callers.

        Args:
            taxon_ids: List of taxon UUIDs to resolve
            locale: Locale code (e.g. "en", "ja")

        Returns:
            Mapping of taxon_id to vernacular name string
        """
        return await resolve_vernacular_names(
            self.annotation_repo.db, taxon_ids, locale
        )

    async def get_species_summary(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        locale: str = "en",
    ) -> SpeciesSummaryResponse:
        """Get species detection summary grouped by tag.

        When locale is specified, common names are resolved from TaxonVernacularName
        using a single batch query to avoid N+1 database calls.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter
            detection_run_id: Optional detection run filter
            locale: Locale code for common name resolution (default: "en")

        Returns:
            Species summary response with per-species statistics
        """
        rows = await self.annotation_repo.species_summary(
            project_id=project_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
        )

        # Collect taxon IDs for batch vernacular name resolution
        taxon_ids = [row["taxon_id"] for row in rows if row["taxon_id"] is not None]
        vernacular_map = await self._resolve_vernacular_names(taxon_ids, locale)

        items = [
            SpeciesSummaryItem(
                tag_id=row["tag_id"],
                tag_name=row["tag_name"],
                scientific_name=row["scientific_name"],
                # Keep ``common_name`` as the English legacy value and expose
                # the locale-resolved name in ``vernacular_name`` (mirrors
                # TagResponse) so clients can prefer the vernacular and fall
                # back to common_name when no entry exists for the locale.
                common_name=row["common_name"],
                vernacular_name=(
                    vernacular_map.get(row["taxon_id"])
                    if row["taxon_id"] is not None
                    else None
                ),
                taxon_id=row["taxon_id"],
                total_count=row["total_count"],
                unreviewed_count=row["unreviewed_count"],
                confirmed_count=row["confirmed_count"],
                rejected_count=row["rejected_count"],
                avg_confidence=row["avg_confidence"],
            )
            for row in rows
        ]

        return SpeciesSummaryResponse(
            items=items,
            total_species=len(items),
        )

    async def get_temporal_data(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        locale: str = "en",
    ) -> DetectionTemporalDataResponse:
        """Get hourly detection counts grouped by species, date, and hour.

        When locale is specified, common names are resolved from TaxonVernacularName
        using a single batch query to avoid N+1 database calls.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter
            detection_run_id: Optional detection run filter
            locale: Locale code for common name resolution (default: "en")

        Returns:
            Temporal data response with per-species hourly counts
        """
        from datetime import date as DateType

        from echoroo.models.tag import Tag

        rows = await self.annotation_repo.temporal_summary(
            project_id=project_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
        )

        # Group rows by tag_id
        grouped: dict[UUID, list[TemporalSummaryRow]] = {}
        for row in rows:
            tag_id = row["tag_id"]
            if tag_id not in grouped:
                grouped[tag_id] = []
            grouped[tag_id].append(row)

        # Batch fetch all tag records in one query
        tag_ids = list(grouped.keys())
        if tag_ids:
            tags_result = await self.annotation_repo.db.execute(
                sa_select(Tag).where(Tag.id.in_(tag_ids))
            )
            tags_by_id: dict[UUID, Tag] = {tag.id: tag for tag in tags_result.scalars().all()}
        else:
            tags_by_id = {}

        # Batch resolve vernacular names for all taxon IDs
        taxon_ids = [tag.taxon_id for tag in tags_by_id.values() if tag.taxon_id is not None]
        vernacular_map = await self._resolve_vernacular_names(taxon_ids, locale)

        # Build response
        species_list: list[SpeciesTemporalData] = []
        all_dates: list[DateType] = []

        for tag_id, tag_rows in grouped.items():
            tag = tags_by_id.get(tag_id)
            if tag is None:
                continue

            # Resolve common name via vernacular map, fall back to tag.common_name
            resolved_common_name = (
                vernacular_map.get(tag.taxon_id, tag.common_name)
                if tag.taxon_id is not None
                else tag.common_name
            )

            hourly_detections = [
                HourlyDetection(
                    date=row["date"],
                    hour=row["hour"],
                    count=row["count"],
                )
                for row in tag_rows
            ]

            total_detections = sum(row["count"] for row in tag_rows)
            dates_for_tag = [row["date"] for row in tag_rows if isinstance(row["date"], DateType)]
            all_dates.extend(dates_for_tag)

            species_list.append(
                SpeciesTemporalData(
                    tag_id=tag.id,
                    scientific_name=tag.scientific_name or tag.name,
                    common_name=resolved_common_name,
                    total_detections=total_detections,
                    detections=hourly_detections,
                )
            )

        # Sort species by total detections descending
        species_list.sort(key=lambda s: s.total_detections, reverse=True)

        date_range: tuple[DateType, DateType] | None = None
        if all_dates:
            date_range = (min(all_dates), max(all_dates))

        return DetectionTemporalDataResponse(
            project_id=project_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
            date_range=date_range,
            species=species_list,
        )

    async def get(
        self,
        detection_id: UUID,
        current_user_id: UUID | None = None,
        min_votes: int = 2,
        threshold: float = 0.667,
        locale: str = "en",
    ) -> DetectionResponse:
        """Get a detection annotation by ID.

        Args:
            detection_id: Annotation's UUID
            current_user_id: Optional current user ID for including their vote
            min_votes: Minimum votes required for consensus (from project settings)
            threshold: Consensus agreement threshold (from project settings)
            locale: Locale code used to resolve vernacular names on the embedded tag

        Returns:
            Detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )
        vote_counts_map = await self._batch_load_vote_counts(
            [annotation.id],
            current_user_id=current_user_id,
            min_votes=min_votes,
            threshold=threshold,
        )
        taxon_ids: list[UUID] = []
        if annotation.tag is not None and annotation.tag.taxon_id is not None:
            taxon_ids.append(annotation.tag.taxon_id)
        vernacular_map = await resolve_vernacular_names(
            self.annotation_repo.db, taxon_ids, locale
        )
        return self._to_response(
            annotation, vote_counts_map.get(annotation.id), vernacular_map
        )

    async def create(
        self,
        project_id: UUID,
        request: DetectionCreate,
    ) -> DetectionResponse:
        """Create a new detection annotation.

        Args:
            project_id: Project's UUID (for authorization context)
            request: Detection creation data

        Returns:
            Created detection response

        Raises:
            HTTPException: 404 if the referenced recording / tag / detection run
                is not in the project; 422 if a ``custom_svm`` detection omits a
                ``detection_run_id`` (which would bypass the dedupe index); 409
                if it exactly duplicates an existing ``custom_svm`` row.
        """
        # custom_svm rows are deduplicated by the partial unique index
        # ``uq_recording_annotations_custom_svm`` (migration 0031), whose
        # predicate requires ``detection_run_id IS NOT NULL``. A custom_svm row
        # with a NULL detection_run_id falls OUTSIDE the index and could never
        # be deduped, silently defeating the guard. Reject it up front. Scoped
        # narrowly to custom_svm — every other source legitimately allows a NULL
        # detection_run_id (e.g. sampling_round / human / search).
        if (
            request.source == DetectionSource.CUSTOM_SVM
            and request.detection_run_id is None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="custom_svm detections require detection_run_id",
            )

        if not await self.recording_repo.exists_in_project(request.recording_id, project_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="recording not found",
            )

        if request.tag_id is not None and not await self.tag_repo.get_by_id_in_project(
            request.tag_id,
            project_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="tag not found",
            )

        if (
            request.detection_run_id is not None
            and not await self.detection_run_repo.exists_in_project(
                request.detection_run_id,
                project_id,
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="detection run not found",
            )

        annotation = RecordingAnnotation(
            recording_id=request.recording_id,
            tag_id=request.tag_id,
            detection_run_id=request.detection_run_id,
            source=request.source,
            confidence=request.confidence,
            start_time=request.start_time,
            end_time=request.end_time,
            freq_low=request.freq_low,
            freq_high=request.freq_high,
        )

        # ``DetectionCreate.source`` accepts any ``DetectionSource`` value,
        # including ``CUSTOM_SVM``. The partial unique index
        # ``uq_recording_annotations_custom_svm`` (migration 0031) deduplicates
        # custom_svm rows on
        # ``(recording_id, tag_id, start_time, end_time, detection_run_id)``, so
        # an exact-duplicate custom_svm create through this generic path raises
        # ``IntegrityError`` on flush. Map ONLY that specific unique-violation to
        # a clean 409; any OTHER integrity error (FK / NOT NULL / a future
        # constraint) must NOT be mislabeled "Duplicate detection" — rollback
        # and re-raise it so the framework surfaces it correctly (mirrors and
        # improves on ``RecorderService.create``, which string-matches; here we
        # discriminate on the asyncpg sqlstate + constraint/index name).
        # The arbiter is intentionally NOT pushed into the generic
        # ``annotation_repo.create`` (other sources reuse it and must stay
        # unconstrained); the conflict is a true duplicate, so 409 is correct.
        try:
            created = await self.annotation_repo.create(annotation)
        except IntegrityError as exc:
            await self.annotation_repo.db.rollback()
            if self._is_custom_svm_dedup_violation(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Duplicate detection",
                ) from exc
            # Unexpected integrity error (FK / NOT NULL / other unique). Do not
            # mislabel it as a duplicate detection — re-raise the original.
            raise
        return self._to_response(created, None)

    @staticmethod
    def _is_custom_svm_dedup_violation(exc: IntegrityError) -> bool:
        """Return True only for a unique violation on the custom_svm dedup index.

        SQLAlchemy wraps the driver error in ``exc.orig``. Under asyncpg the
        wrapped error exposes ``sqlstate`` (``'23505'`` = ``unique_violation``)
        and, via its ``__cause__`` diagnostics, the offending constraint/index
        name. We require BOTH the unique-violation sqlstate AND the
        ``uq_recording_annotations_custom_svm`` index name so that any other
        integrity error (FK violation, NOT NULL, a future unique constraint) is
        NOT mapped to 409. Falls back to a defensive string match on the index
        name if the structured attributes are unavailable.
        """
        orig = getattr(exc, "orig", None)
        if orig is None:
            return False

        # asyncpg: ``sqlstate`` is on the wrapped error (and/or its cause).
        sqlstate = getattr(orig, "sqlstate", None)
        cause = getattr(orig, "__cause__", None)
        if sqlstate is None and cause is not None:
            sqlstate = getattr(cause, "sqlstate", None)
        if sqlstate != "23505":
            return False

        # asyncpg surfaces the index/constraint name via the exception's
        # ``constraint_name`` diagnostic (on the cause), else fall back to the
        # rendered message text.
        constraint_name = None
        if cause is not None:
            constraint_name = getattr(cause, "constraint_name", None)
        if constraint_name == CUSTOM_SVM_DEDUP_INDEX_NAME:
            return True
        return CUSTOM_SVM_DEDUP_INDEX_NAME in str(orig)

    async def confirm(
        self,
        detection_id: UUID,
        user_id: UUID,
        request: ConfirmRequest | None = None,
    ) -> DetectionResponse:
        """Confirm a detection annotation and create a confirmed region.

        Sets status to confirmed, records the reviewer, and creates a
        ConfirmedRegion for the confirmed time range. When *request* is
        ``None`` or its fields are ``None``, the annotation's existing
        start_time / end_time are preserved (quick-confirm).

        Args:
            detection_id: Annotation's UUID
            user_id: ID of the user confirming the detection
            request: Optional confirm request with adjusted time range

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        # Use provided times or fall back to the annotation's existing values
        start_time = (
            request.start_time
            if request is not None and request.start_time is not None
            else annotation.start_time
        )
        end_time = (
            request.end_time
            if request is not None and request.end_time is not None
            else annotation.end_time
        )

        annotation.status = DetectionStatus.CONFIRMED
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)
        annotation.start_time = start_time
        annotation.end_time = end_time

        updated = await self.annotation_repo.update(annotation)

        # Create a confirmed region for the confirmed time range
        confirmed_region = ConfirmedRegion(
            recording_id=annotation.recording_id,
            start_time=start_time,
            end_time=end_time,
            reviewed_by_id=user_id,
        )
        await self.confirmed_region_repo.create(confirmed_region)

        vote_counts_map = await self._batch_load_vote_counts([updated.id])
        return self._to_response(updated, vote_counts_map.get(updated.id))

    async def reject(
        self,
        detection_id: UUID,
        user_id: UUID,
    ) -> DetectionResponse:
        """Reject a detection annotation.

        Args:
            detection_id: Annotation's UUID
            user_id: ID of the user rejecting the detection

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        annotation.status = DetectionStatus.REJECTED
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)

        updated = await self.annotation_repo.update(annotation)
        vote_counts_map = await self._batch_load_vote_counts([updated.id])
        return self._to_response(updated, vote_counts_map.get(updated.id))

    async def change_species(
        self,
        detection_id: UUID,
        request: ChangeSpeciesRequest,
        user_id: UUID,
        project_id: UUID,
    ) -> DetectionResponse:
        """Change the species tag of a detection annotation.

        Also updates time range if provided, and records the reviewer.

        Args:
            detection_id: Annotation's UUID
            request: Change species request with new tag and optional time range
            user_id: ID of the user making the change
            project_id: Project's UUID for tag ownership validation

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        if not await self.tag_repo.get_by_id_in_project(request.new_tag_id, project_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="tag not found",
            )

        annotation.tag_id = request.new_tag_id
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)

        if request.start_time is not None:
            annotation.start_time = request.start_time
        if request.end_time is not None:
            annotation.end_time = request.end_time

        updated = await self.annotation_repo.update(annotation)
        vote_counts_map = await self._batch_load_vote_counts([updated.id])
        return self._to_response(updated, vote_counts_map.get(updated.id))

    async def delete(self, detection_id: UUID) -> None:
        """Delete a detection annotation.

        Args:
            detection_id: Annotation's UUID

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        await self.annotation_repo.delete(detection_id)

    async def _batch_load_vote_counts(
        self,
        annotation_ids: list[UUID],
        current_user_id: UUID | None = None,
        min_votes: int = 2,
        threshold: float = 0.667,
    ) -> dict[UUID, DetectionVoteCounts]:
        """Batch-load vote counts for a list of annotations in one query.

        Args:
            annotation_ids: List of annotation UUIDs
            current_user_id: Optional user ID to include their vote per annotation

        Returns:
            Mapping of annotation_id to DetectionVoteCounts
        """
        if not annotation_ids or self.vote_repo is None:
            return {}

        from echoroo.services.annotation_vote import AnnotationVoteService

        votes_result = await self.annotation_repo.db.execute(
            sa_select(AnnotationVote).where(
                AnnotationVote.annotation_id.in_(annotation_ids)
            )
        )
        all_votes = list(votes_result.scalars().all())

        # Group votes by annotation_id
        grouped: dict[UUID, list[AnnotationVote]] = {aid: [] for aid in annotation_ids}
        for vote in all_votes:
            if vote.annotation_id in grouped:
                grouped[vote.annotation_id].append(vote)

        result: dict[UUID, DetectionVoteCounts] = {}
        for annotation_id, votes in grouped.items():
            # Phase 13 P1.5 (T804): ``vote`` is now smallint at the DB layer;
            # use the ``vote_enum`` ergonomic property for VoteType compares.
            agree_count = sum(1 for v in votes if v.vote_enum == VoteType.AGREE)
            disagree_count = sum(1 for v in votes if v.vote_enum == VoteType.DISAGREE)
            unsure_count = sum(1 for v in votes if v.vote_enum == VoteType.UNSURE)

            # Phase 13 P1.5: ``signal_quality`` was dropped from the vote
            # row; emit zero counts to preserve the API contract until
            # Phase 14+ recording_annotations reinstates it.
            signal_quality_counts: dict[str, int] = {q.value: 0 for q in SignalQuality}

            user_vote: VoteType | None = None
            user_signal_quality: SignalQuality | None = None
            if current_user_id is not None:
                for v in votes:
                    if v.voter_user_id == current_user_id:
                        user_vote = v.vote_enum
                        # Phase 13 P1.5: signal_quality dropped — None until Phase 14+.
                        user_signal_quality = None
                        break

            consensus_status = AnnotationVoteService.compute_consensus_status(
                agree_count=agree_count,
                disagree_count=disagree_count,
                min_votes=min_votes,
                threshold=threshold,
            )

            result[annotation_id] = DetectionVoteCounts(
                agree_count=agree_count,
                disagree_count=disagree_count,
                unsure_count=unsure_count,
                user_vote=user_vote,
                user_signal_quality=user_signal_quality,
                signal_quality_counts=signal_quality_counts,
                consensus_status=consensus_status,
            )

        return result

    @staticmethod
    def _to_response(
        annotation: RecordingAnnotation,
        vote_counts: DetectionVoteCounts | None = None,
        vernacular_map: dict[UUID, str] | None = None,
    ) -> DetectionResponse:
        """Convert a RecordingAnnotation model to a DetectionResponse schema.

        Args:
            annotation: Annotation model instance
            vote_counts: Optional pre-loaded vote counts for this annotation
            vernacular_map: Optional mapping of ``taxon_id`` to locale-resolved
                vernacular name. When the embedded tag has a ``taxon_id`` that
                is present in the mapping, ``TagResponse.vernacular_name`` is
                populated; otherwise it remains ``None``.

        Returns:
            DetectionResponse instance
        """
        tag_response = None
        if annotation.tag is not None:
            tag_response = TagResponse.model_validate(annotation.tag)
            if (
                vernacular_map is not None
                and annotation.tag.taxon_id is not None
            ):
                tag_response.vernacular_name = vernacular_map.get(
                    annotation.tag.taxon_id
                )

        return DetectionResponse(
            id=annotation.id,
            recording_id=annotation.recording_id,
            tag_id=annotation.tag_id,
            detection_run_id=annotation.detection_run_id,
            source=annotation.source,
            status=annotation.status,
            confidence=annotation.confidence,
            start_time=annotation.start_time,
            end_time=annotation.end_time,
            freq_low=annotation.freq_low,
            freq_high=annotation.freq_high,
            reviewed_by_id=annotation.reviewed_by_id,
            reviewed_at=annotation.reviewed_at,
            created_at=annotation.created_at,
            updated_at=annotation.updated_at,
            tag=tag_response,
            votes=vote_counts if vote_counts is not None else DetectionVoteCounts(),
        )
