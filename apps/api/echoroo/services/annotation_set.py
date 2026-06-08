"""Service layer for :class:`AnnotationSet` management (spec 003-annotation).

Enforces cross-entity invariants that the repository intentionally leaves to
the service tier:

- Sampling parameters and filters are frozen once sampling has started.
- ``POST /sample`` dispatch is idempotent while a run is in flight and is
  refused when segments already exist.
- Palette additions are validated against the ``taxa`` table.
- Deletion is blocked while sampling is in progress.
- The parent ``AnnotationSet`` status is derived from its children's
  ``AnnotationSegmentStatus`` aggregate (see
  :meth:`AnnotationSetService.recompute_status`).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select

from echoroo.core.pagination import paginate
from echoroo.models.annotation_set import AnnotationSegment, AnnotationSet
from echoroo.models.enums import AnnotationSegmentStatus, AnnotationSetStatus
from echoroo.models.taxon import Taxon
from echoroo.repositories.annotation_set import (
    AnnotationSegmentRepository,
    AnnotationSetRepository,
)
from echoroo.repositories.taxon import normalize_locale
from echoroo.schemas.annotation_set import (
    AnnotationSegmentListResponse,
    AnnotationSegmentResponse,
    AnnotationSetCreate,
    AnnotationSetDetailResponse,
    AnnotationSetListResponse,
    AnnotationSetProgress,
    AnnotationSetResponse,
    AnnotationSetSampleDispatchResponse,
    AnnotationSetUpdate,
    PaletteEntryResponse,
    PaletteItemCreate,
)
from echoroo.services.vernacular import resolve_vernacular_names

logger = logging.getLogger(__name__)


class AnnotationSetService:
    """Business logic for ``AnnotationSet`` CRUD, palette and sampling."""

    def __init__(
        self,
        set_repo: AnnotationSetRepository,
        segment_repo: AnnotationSegmentRepository,
    ) -> None:
        self.set_repo = set_repo
        self.segment_repo = segment_repo

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _db(self) -> Any:
        return self.set_repo.db

    async def _require_set(self, set_id: UUID) -> AnnotationSet:
        anno_set = await self.set_repo.get_by_id(set_id)
        if anno_set is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Annotation set not found",
            )
        return anno_set

    async def _require_taxon(self, taxon_id: UUID) -> Taxon:
        result = await self._db.execute(select(Taxon).where(Taxon.id == taxon_id))
        taxon: Taxon | None = result.scalar_one_or_none()
        if taxon is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=f"Taxon not found: {taxon_id}",
            )
        return taxon

    async def _build_progress(self, set_id: UUID) -> AnnotationSetProgress:
        counts = await self.segment_repo.count_by_status(set_id)
        # Count empty segments (is_empty=True) separately.
        empty_stmt = (
            select(func.count())
            .select_from(AnnotationSegment)
            .where(
                AnnotationSegment.annotation_set_id == set_id,
                AnnotationSegment.is_empty.is_(True),
            )
        )
        empty = int((await self._db.execute(empty_stmt)).scalar_one())

        unannotated = counts.get(AnnotationSegmentStatus.UNANNOTATED, 0)
        annotated = counts.get(AnnotationSegmentStatus.ANNOTATED, 0)
        skipped = counts.get(AnnotationSegmentStatus.SKIPPED, 0)
        total = unannotated + annotated + skipped
        return AnnotationSetProgress(
            total=total,
            unannotated=unannotated,
            annotated=annotated,
            skipped=skipped,
            empty=empty,
        )

    async def _build_palette(
        self, set_id: UUID, locale: str = "en",
    ) -> list[PaletteEntryResponse]:
        """Build the palette, resolving each entry's display ``common_name``.

        The name is resolved from the LOCAL database/cache via
        ``resolve_vernacular_names`` (requested-locale → English fallback). No
        live external lookups happen here — display is a read-only concern and
        the scientific-name floor is applied by the frontend formatter when no
        vernacular row exists.
        """
        rows = await self.set_repo.list_palette_with_taxa(set_id)
        # Normalize the requested locale to its primary subtag so ``ja-JP``/``JA``
        # resolve like ``ja`` (``resolve_vernacular_names`` matches exactly).
        normalized_locale = normalize_locale(locale)
        common_names = await resolve_vernacular_names(
            self._db,
            [taxon.id for taxon, _ in rows],
            normalized_locale,
        )
        return [
            PaletteEntryResponse(
                species_id=taxon.id,
                scientific_name=taxon.scientific_name,
                common_name=common_names.get(taxon.id),
                position=position,
            )
            for taxon, position in rows
        ]

    async def _to_detail(
        self, anno_set: AnnotationSet, locale: str = "en",
    ) -> AnnotationSetDetailResponse:
        progress = await self._build_progress(anno_set.id)
        palette = await self._build_palette(anno_set.id, locale=locale)
        return AnnotationSetDetailResponse(
            id=anno_set.id,
            project_id=anno_set.project_id,
            dataset_id=anno_set.dataset_id,
            created_by_id=anno_set.created_by_id,
            name=anno_set.name,
            filter_date_range=anno_set.filter_date_range,
            filter_time_of_day_range=anno_set.filter_time_of_day_range,
            segment_mode=anno_set.segment_mode,
            segment_length_sec=anno_set.segment_length_sec,
            num_segments=anno_set.num_segments,
            status=anno_set.status.value,
            sampling_warning=anno_set.sampling_warning,
            min_total_score=anno_set.min_total_score,
            created_at=anno_set.created_at,
            updated_at=anno_set.updated_at,
            progress=progress,
            palette=palette,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create(
        self, *, user_id: UUID, request: AnnotationSetCreate,
    ) -> AnnotationSetDetailResponse:
        """Create a new AnnotationSet in ``sampling`` status and dispatch the
        sampling task.

        Create and sample are always performed together from the UX
        standpoint, so this method enqueues the
        :func:`sample_annotation_segments` Celery task before returning. The
        worker is responsible for promoting the set from ``sampling`` ->
        ``ready`` once segments are materialized.

        The ``POST /annotation-sets/{id}/sample`` endpoint remains available
        for manual re-sampling (see :meth:`dispatch_sample`).
        """
        anno_set = await self.set_repo.create(
            project_id=request.project_id,
            dataset_id=request.dataset_id,
            created_by_id=user_id,
            name=request.name,
            segment_mode=request.segment_mode,
            segment_length_sec=request.segment_length_sec,
            num_segments=request.num_segments,
            filter_date_range=(
                request.filter_date_range.model_dump()
                if request.filter_date_range is not None
                else None
            ),
            filter_time_of_day_range=(
                request.filter_time_of_day_range.model_dump()
                if request.filter_time_of_day_range is not None
                else None
            ),
            min_total_score=request.min_total_score,
        )

        # Commit before enqueueing so the worker can fetch the row through a
        # fresh session.
        await self._db.commit()

        # Lazy import to avoid circular dependency at module import time.
        from echoroo.workers.annotation_sampling_tasks import (  # noqa: PLC0415
            sample_annotation_segments,
        )

        async_result = sample_annotation_segments.delay(str(anno_set.id))
        logger.info(
            "Auto-dispatched annotation sampling task on create: "
            "set_id=%s task_id=%s",
            anno_set.id,
            async_result.id,
        )

        return await self._to_detail(anno_set)

    async def list(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID | None,
        status_filter: AnnotationSetStatus | None,
        page: int,
        page_size: int,
    ) -> AnnotationSetListResponse:
        pagination = paginate(page, page_size, default_page_size=20, max_page_size=200)
        items, total = await self.set_repo.list_by_project(
            project_id,
            dataset_id=dataset_id,
            status=status_filter,
            limit=pagination.page_size,
            offset=pagination.offset,
        )

        progress_map = await self._build_progress_map([row.id for row in items])

        return AnnotationSetListResponse(
            items=[
                AnnotationSetResponse.model_validate(row).model_copy(
                    update={"progress": progress_map.get(row.id)},
                )
                for row in items
            ],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    async def _build_progress_map(
        self, set_ids: Sequence[UUID]
    ) -> dict[UUID, AnnotationSetProgress]:
        """Compute per-set :class:`AnnotationSetProgress` for the listed sets.

        Uses TWO grouped queries over all ``set_ids`` (one for per-status
        counts, one for ``is_empty`` counts) regardless of how many sets are
        listed, so the list view avoids the N+1 of calling
        :meth:`_build_progress` per row. Semantics match ``_build_progress``:
        ``total = unannotated + annotated + skipped`` and ``empty`` counts
        segments with ``is_empty=True``.
        """
        if not set_ids:
            return {}

        # Per-status counts: GROUP BY (annotation_set_id, status).
        status_stmt = (
            select(
                AnnotationSegment.annotation_set_id,
                AnnotationSegment.status,
                func.count(),
            )
            .where(AnnotationSegment.annotation_set_id.in_(set_ids))
            .group_by(
                AnnotationSegment.annotation_set_id,
                AnnotationSegment.status,
            )
        )
        per_status: dict[UUID, dict[AnnotationSegmentStatus, int]] = {
            sid: dict.fromkeys(AnnotationSegmentStatus, 0) for sid in set_ids
        }
        for set_id, seg_status, count in (
            await self._db.execute(status_stmt)
        ).all():
            per_status[set_id][seg_status] = int(count)

        # Empty counts (is_empty=True): GROUP BY annotation_set_id.
        empty_stmt = (
            select(AnnotationSegment.annotation_set_id, func.count())
            .where(
                AnnotationSegment.annotation_set_id.in_(set_ids),
                AnnotationSegment.is_empty.is_(True),
            )
            .group_by(AnnotationSegment.annotation_set_id)
        )
        empty_map: dict[UUID, int] = {}
        for set_id, count in (await self._db.execute(empty_stmt)).all():
            empty_map[set_id] = int(count)

        result: dict[UUID, AnnotationSetProgress] = {}
        for set_id in set_ids:
            counts = per_status[set_id]
            unannotated = counts.get(AnnotationSegmentStatus.UNANNOTATED, 0)
            annotated = counts.get(AnnotationSegmentStatus.ANNOTATED, 0)
            skipped = counts.get(AnnotationSegmentStatus.SKIPPED, 0)
            result[set_id] = AnnotationSetProgress(
                total=unannotated + annotated + skipped,
                unannotated=unannotated,
                annotated=annotated,
                skipped=skipped,
                empty=empty_map.get(set_id, 0),
            )
        return result

    async def get_detail(
        self, set_id: UUID, locale: str = "en",
    ) -> AnnotationSetDetailResponse:
        anno_set = await self._require_set(set_id)
        return await self._to_detail(anno_set, locale=locale)

    async def update(
        self, set_id: UUID, request: AnnotationSetUpdate,
    ) -> AnnotationSetDetailResponse:
        anno_set = await self._require_set(set_id)

        # Sampling parameters are frozen while sampling is in progress.
        if anno_set.status == AnnotationSetStatus.SAMPLING and any(
            v is not None
            for v in (
                request.filter_date_range,
                request.filter_time_of_day_range,
                request.segment_mode,
                request.segment_length_sec,
                request.num_segments,
            )
        ):
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "Sampling parameters cannot be changed while sampling is "
                    "in progress."
                ),
            )

        if request.name is not None:
            anno_set.name = request.name
        if request.filter_date_range is not None:
            anno_set.filter_date_range = request.filter_date_range.model_dump()
        if request.filter_time_of_day_range is not None:
            anno_set.filter_time_of_day_range = (
                request.filter_time_of_day_range.model_dump()
            )
        if request.segment_mode is not None:
            anno_set.segment_mode = request.segment_mode
        if request.segment_length_sec is not None:
            anno_set.segment_length_sec = request.segment_length_sec
        if request.num_segments is not None:
            anno_set.num_segments = request.num_segments
        # ToriTore threshold (preview): NULL is a meaningful value ("clear the
        # requirement"), so distinguish "field supplied" from "omitted" via the
        # request's explicitly-set fields rather than a None default.
        if "min_total_score" in request.model_fields_set:
            anno_set.min_total_score = request.min_total_score

        await self._db.flush()
        await self._db.refresh(anno_set)
        return await self._to_detail(anno_set)

    async def delete(self, set_id: UUID) -> None:
        anno_set = await self._require_set(set_id)
        if anno_set.status == AnnotationSetStatus.SAMPLING:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail="Cannot delete an annotation set while sampling is in progress.",
            )
        await self.set_repo.delete(set_id)

    # ------------------------------------------------------------------
    # Sampling dispatch
    # ------------------------------------------------------------------

    async def dispatch_sample(
        self, set_id: UUID,
    ) -> AnnotationSetSampleDispatchResponse:
        """Enqueue the sampling Celery task.

        Raises:
            HTTPException: 409 if segments already exist or sampling is
                already in flight for a different lifecycle state.
        """
        anno_set = await self._require_set(set_id)

        # If the set already has segments, refuse re-sampling.
        seg_count_stmt = (
            select(func.count())
            .select_from(AnnotationSegment)
            .where(AnnotationSegment.annotation_set_id == set_id)
        )
        existing = int((await self._db.execute(seg_count_stmt)).scalar_one())
        if existing > 0:
            raise HTTPException(
                status_code=http_status.HTTP_409_CONFLICT,
                detail=(
                    "Segments already exist for this set; delete them before "
                    "re-sampling."
                ),
            )

        # Ensure status is 'sampling' so the worker can pick up the work.
        anno_set.status = AnnotationSetStatus.SAMPLING
        anno_set.sampling_warning = None
        await self._db.flush()
        await self._db.commit()

        # Lazy import to avoid circular dependency at module import time.
        from echoroo.workers.annotation_sampling_tasks import (  # noqa: PLC0415
            sample_annotation_segments,
        )

        async_result = sample_annotation_segments.delay(str(set_id))
        logger.info(
            "Dispatched annotation sampling task: set_id=%s task_id=%s",
            set_id,
            async_result.id,
        )
        return AnnotationSetSampleDispatchResponse(
            task_id=str(async_result.id),
            status=AnnotationSetStatus.SAMPLING.value,
        )

    # ------------------------------------------------------------------
    # Palette management
    # ------------------------------------------------------------------

    async def add_palette(
        self, set_id: UUID, request: PaletteItemCreate,
    ) -> PaletteEntryResponse:
        await self._require_set(set_id)
        taxon = await self._require_taxon(request.species_id)
        try:
            await self.set_repo.add_palette_entry(
                set_id, request.species_id, request.position,
            )
        except Exception as exc:  # likely a unique-constraint violation
            # Best-effort: classify integrity errors as 409; anything else bubbles.
            message = str(exc).lower()
            if "unique" in message or "duplicate" in message:
                raise HTTPException(
                    status_code=http_status.HTTP_409_CONFLICT,
                    detail="Taxon is already on the palette.",
                ) from exc
            raise
        return PaletteEntryResponse(
            species_id=taxon.id,
            scientific_name=taxon.scientific_name,
            common_name=None,
            position=request.position,
        )

    async def remove_palette(self, set_id: UUID, species_id: UUID) -> None:
        await self._require_set(set_id)
        await self.set_repo.remove_palette_entry(set_id, species_id)

    # ------------------------------------------------------------------
    # Segment listing
    # ------------------------------------------------------------------

    async def list_segments(
        self,
        set_id: UUID,
        *,
        status_filter: AnnotationSegmentStatus | None,
        is_empty: bool | None,
        page: int,
        page_size: int,
    ) -> AnnotationSegmentListResponse:
        await self._require_set(set_id)
        pagination = paginate(page, page_size, default_page_size=50, max_page_size=500)
        items, total = await self.segment_repo.list_by_set(
            set_id,
            status=status_filter,
            is_empty=is_empty,
            limit=pagination.page_size,
            offset=pagination.offset,
        )

        # Attach auxiliary fields (recording_filename, annotation_count) in
        # single batch queries to avoid N+1.
        recording_ids = list({row.recording_id for row in items})
        filename_map: dict[UUID, str] = {}
        if recording_ids:
            from echoroo.models.recording import Recording  # noqa: PLC0415

            filename_stmt = select(Recording.id, Recording.filename).where(
                Recording.id.in_(recording_ids)
            )
            for rec_id, filename in (await self._db.execute(filename_stmt)).all():
                filename_map[rec_id] = filename

        count_map: dict[UUID, int] = {}
        if items:
            from echoroo.models.annotation_set import TimeRangeAnnotation  # noqa: PLC0415

            count_stmt = (
                select(TimeRangeAnnotation.segment_id, func.count())
                .where(
                    TimeRangeAnnotation.segment_id.in_([row.id for row in items])
                )
                .group_by(TimeRangeAnnotation.segment_id)
            )
            for seg_id, count in (await self._db.execute(count_stmt)).all():
                count_map[seg_id] = int(count)

        response_items = [
            AnnotationSegmentResponse(
                id=row.id,
                annotation_set_id=row.annotation_set_id,
                recording_id=row.recording_id,
                recording_filename=filename_map.get(row.recording_id),
                start_time_sec=row.start_time_sec,
                end_time_sec=row.end_time_sec,
                is_empty=row.is_empty,
                status=row.status.value,
                annotated_by_id=row.annotated_by_id,
                annotated_at=row.annotated_at,
                annotation_count=count_map.get(row.id, 0),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in items
        ]
        return AnnotationSegmentListResponse(
            items=response_items,
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    # ------------------------------------------------------------------
    # Status recomputation
    # ------------------------------------------------------------------

    async def recompute_status(self, set_id: UUID) -> AnnotationSet:
        """Recompute the parent AnnotationSet status based on child segments.

        Rules:
            - No children: no change.
            - All children ``annotated`` or ``skipped``: ``COMPLETED``.
            - At least one ``annotated`` or ``skipped`` but not all:
              ``IN_PROGRESS``.
            - Otherwise (fresh set, all ``unannotated``): ``READY``.
        """
        anno_set = await self._require_set(set_id)
        counts = await self.segment_repo.count_by_status(set_id)
        total = sum(counts.values())
        if total == 0:
            return anno_set

        finalized = (
            counts.get(AnnotationSegmentStatus.ANNOTATED, 0)
            + counts.get(AnnotationSegmentStatus.SKIPPED, 0)
        )
        if finalized == 0:
            new_status = AnnotationSetStatus.READY
        elif finalized < total:
            new_status = AnnotationSetStatus.IN_PROGRESS
        else:
            new_status = AnnotationSetStatus.COMPLETED

        # Never regress out of SAMPLING here — only the worker may promote
        # SAMPLING -> READY.
        if anno_set.status == AnnotationSetStatus.SAMPLING:
            return anno_set
        if anno_set.status != new_status:
            anno_set.status = new_status
            await self._db.flush()
            await self._db.refresh(anno_set)
        return anno_set
