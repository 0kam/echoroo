"""Annotation-set CSV export service (CamtrapDP + FR-086 + offset columns).

This mirrors :mod:`echoroo.services.detection_export` so that ground-truth
``TimeRangeAnnotation`` rows can be exported with the SAME CamtrapDP
``observations.csv`` column shape used by the BirdNET / detection export.

Six segment / recording offset columns are appended after the CamtrapDP /
FR-086 block so a consumer can locate each annotation both inside its
segment/clip and inside the source recording: ``segment_id``, ``recording_id``,
``segment_start_sec``, ``segment_end_sec``, ``recording_start_sec``,
``recording_end_sec``. ``mediaID``
carries the canonical source-recording UUID (approved 2026-06-09; sourced from
:mod:`echoroo.services.camtrap` like every other export surface), so the
segment linkage is preserved via the trailing ``segment_id`` / ``recording_id``
+ offset extension columns rather than folded into ``mediaID``.

CamtrapDP-compliant readers ignore unknown trailing columns, so the extension
is non-breaking. Raw lat / lng / GPS columns are intentionally absent (FR-028 /
SC-016); the row's location precision is disclosed via the reused
``location_generalization`` / ``withheld_reason`` helpers.

The export is **read-only** — no migration is introduced. The shared CamtrapDP
column list, event-datetime formatter, and identifier functions come from
:mod:`echoroo.services.camtrap`; the FR-086 license / H3-resolution /
generalization logic is REUSED from
:class:`echoroo.services.detection_export.DetectionExportService` rather than
duplicated, so the exports stay consistent.
"""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.annotation_set import (
    AnnotationSegment,
    AnnotationSet,
    TimeRangeAnnotation,
)
from echoroo.models.enums import AnnotationSegmentStatus
from echoroo.services.camtrap import (
    CAMTRAPDP_OBSERVATION_COLUMNS,
    deployment_id,
    event_id,
    format_event_datetime,
    media_id,
    observation_id,
)
from echoroo.services.detection_export import (
    _DEFAULT_MEMBER_H3_RESOLUTION,
    DetectionExportService,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from echoroo.models.project import Project

# Segment / recording offset columns appended AFTER the CamtrapDP / FR-086
# block so a consumer can locate the annotation both inside the segment/clip and
# inside the source recording. ``mediaID`` carries the canonical recording UUID
# (single source of truth), so the segment linkage is preserved here via
# ``segment_id`` + ``recording_id`` + the segment/recording offset columns.
_OFFSET_COLUMNS = [
    "segment_id",
    "recording_id",
    "segment_start_sec",
    "segment_end_sec",
    "recording_start_sec",
    "recording_end_sec",
]

# Full ordered column list = the shared CamtrapDP/FR-086 columns, then the
# six segment/recording offset columns.
_ANNOTATION_SET_COLUMNS = [
    *CAMTRAPDP_OBSERVATION_COLUMNS,
    *_OFFSET_COLUMNS,
]


def _format_float(value: float | None) -> str:
    """Render a nullable float, blank when ``None``."""
    if value is None:
        return ""
    return f"{value:.4f}"


class AnnotationSetExportService:
    """Export an :class:`AnnotationSet`'s annotations as a CamtrapDP CSV.

    Reuses :class:`DetectionExportService` for the FR-086 license / H3
    resolution / location-generalization helpers so the annotation-set export
    is consistent with the detection export.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        detection_service: DetectionExportService | None = None,
    ) -> None:
        """Initialise with an async database session.

        Args:
            db: Async database session.
            detection_service: Optional pre-built :class:`DetectionExportService`
                (dependency-injection seam for tests). Defaults to a new
                instance bound to the SAME ``db`` session, preserving the
                previous behaviour.
        """
        self.db = db
        # Reuse the detection export helpers (license, H3 map, generalization).
        self._detection = detection_service or DetectionExportService(db)

    async def _require_set(self, set_id: UUID) -> AnnotationSet:
        """Load the set (no relationships) — caller validates project scope."""
        result = await self.db.execute(
            select(AnnotationSet).where(AnnotationSet.id == set_id)
        )
        anno_set: AnnotationSet | None = result.scalar_one_or_none()
        if anno_set is None:
            msg = f"Annotation set not found: {set_id}"
            raise ValueError(msg)
        return anno_set

    async def _fetch_annotations(
        self, set_id: UUID, *, finalized_only: bool = False
    ) -> list[TimeRangeAnnotation]:
        """Load all TimeRangeAnnotations in a set with relationships for export.

        Eager-loads:

        * ``segment.recording`` (+ ``recording.dataset`` for deploymentID),
        * ``taxon`` (for ``scientificName``),
        * ``created_by`` (for the annotator display name).

        When ``finalized_only`` is True the rows are scoped to segments with
        ``status == AnnotationSegmentStatus.ANNOTATED`` — the SAME finalized
        universe the evaluation worker uses (see
        :func:`echoroo.workers.evaluation_tasks._load_ground_truths`). The
        dataset ZIP export uses this so every CSV row's segment has a clip in
        the bundle.
        """
        query = (
            select(TimeRangeAnnotation)
            .join(
                AnnotationSegment,
                TimeRangeAnnotation.segment_id == AnnotationSegment.id,
            )
            .where(AnnotationSegment.annotation_set_id == set_id)
            .options(
                selectinload(TimeRangeAnnotation.segment)
                .selectinload(AnnotationSegment.recording),
                selectinload(TimeRangeAnnotation.taxon),
                selectinload(TimeRangeAnnotation.created_by),
            )
            .order_by(
                AnnotationSegment.recording_id,
                AnnotationSegment.start_time_sec,
                TimeRangeAnnotation.start_time_sec,
            )
        )
        if finalized_only:
            query = query.where(
                AnnotationSegment.status == AnnotationSegmentStatus.ANNOTATED
            )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _build_recording_h3_map(
        self, annotations: list[TimeRangeAnnotation]
    ) -> dict[UUID, int]:
        """Pre-load the Site H3 resolution per recording for the export.

        Reuses the detection export's recording-keyed H3 resolution loader by
        adapting the TimeRangeAnnotation rows to the lightweight ``recording_id``
        shape the helper consumes. We construct tiny stand-in objects exposing
        only ``recording_id`` so the shared helper (which reads nothing else)
        can be reused verbatim without copy-pasting its h3 logic.
        """

        class _RecRef:
            __slots__ = ("recording_id",)

            def __init__(self, recording_id: UUID | None) -> None:
                self.recording_id = recording_id

        refs = [
            _RecRef(ann.segment.recording_id if ann.segment else None)
            for ann in annotations
        ]
        # The helper is typed for the detection ``Annotation`` shape but only
        # accesses ``.recording_id``; the stand-ins satisfy that contract.
        return await self._detection._build_recording_h3_resolution_map(refs)  # type: ignore[arg-type]

    def _build_row(
        self,
        ann: TimeRangeAnnotation,
        *,
        project: Project | None,
        license_value: str,
        license_history_url: str,
        recording_h3_map: dict[UUID, int],
    ) -> dict[str, str]:
        """Render one CamtrapDP + FR-086 + offset row for ``ann``."""
        segment = ann.segment
        recording = segment.recording if segment else None
        dataset = recording.dataset if recording and recording.dataset else None
        # Canonical CamtrapDP join keys (approved 2026-06-09): deploymentID is
        # the dataset UUID and mediaID is the recording UUID (NOT the segment
        # id) — both sourced from echoroo.services.camtrap so this export emits
        # the same keys as the detection / deployments / media exports. The
        # segment linkage is preserved via the trailing extension columns.
        deployment_value = deployment_id(dataset.id) if dataset else ""
        media_value = media_id(recording.id) if recording else ""
        recording_uuid = str(recording.id) if recording else ""
        segment_uuid = str(segment.id) if segment else ""
        recording_datetime = recording.datetime if recording else None
        recording_id = recording.id if recording else None

        # Offsets: inside the segment/clip (annotation-relative) and inside the
        # recording (segment.start_time_sec + annotation offset).
        segment_offset_base = segment.start_time_sec if segment else 0.0
        segment_start_sec = ann.start_time_sec
        segment_end_sec = ann.end_time_sec
        recording_start_sec = segment_offset_base + ann.start_time_sec
        recording_end_sec = segment_offset_base + ann.end_time_sec

        # eventStart/eventEnd are the ANNOTATION's recording-relative time
        # (segment offset + annotation offset), NOT the segment window. Reuses
        # the shared formatter, which preserves sub-second (millisecond)
        # precision so short / fractional-offset annotations keep their real
        # boundaries.
        event_start = format_event_datetime(
            recording_datetime, recording_start_sec
        )
        event_end = format_event_datetime(
            recording_datetime, recording_end_sec
        )

        classification_timestamp = (
            ann.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            if ann.created_at is not None
            else ""
        )
        classified_by = ""
        if ann.created_by is not None:
            classified_by = (
                ann.created_by.display_name or ann.created_by.email or ""
            )

        site_res = (
            recording_h3_map.get(recording_id, _DEFAULT_MEMBER_H3_RESOLUTION)
            if recording_id is not None
            else _DEFAULT_MEMBER_H3_RESOLUTION
        )
        location_generalization, withheld_reason = (
            DetectionExportService._compute_export_location_generalization(
                project=project,
                site_resolution=site_res,
            )
        )

        return {
            "observationID": observation_id(ann.id),
            "deploymentID": deployment_value,
            # mediaID is the source recording UUID (single source of truth).
            # The segment linkage is preserved in the trailing ``segment_id`` /
            # ``recording_id`` + offset extension columns below.
            "mediaID": media_value,
            "eventID": event_id(),
            "eventStart": event_start,
            "eventEnd": event_end,
            "observationLevel": "event",
            "observationType": "observation",
            "deviceSetupType": "",
            "scientificName": ann.taxon.scientific_name if ann.taxon else "",
            "count": "1",
            "lifeStage": "",
            "sex": "",
            "behavior": "",
            "individualID": "",
            "individualPositionRadius": "",
            "individualPositionAngle": "",
            "individualSpeed": "",
            "bboxX": "",
            "bboxY": "",
            "bboxWidth": "",
            "bboxHeight": "",
            # TimeRangeAnnotation carries no frequency bounds.
            "frequencyLow": "",
            "frequencyHigh": "",
            "classificationMethod": "human",
            "classifiedBy": classified_by,
            "classificationTimestamp": classification_timestamp,
            "classificationProbability": (
                f"{ann.confidence:.4f}" if ann.confidence is not None else ""
            ),
            "classificationConfirmation": "",
            "observationTags": "",
            "observationComments": "",
            # FR-086 trailing extensions (shared semantics with detection export)
            "license": license_value,
            "license_history_url": license_history_url,
            "location_generalization": str(location_generalization),
            "withheld_reason": withheld_reason if withheld_reason is not None else "",
            # Segment / recording identity + offset columns. ``segment_start_sec``
            # is the annotation offset INSIDE the segment/clip; ``recording_*``
            # adds the segment's own offset to locate it inside the recording.
            "segment_id": segment_uuid,
            "recording_id": recording_uuid,
            "segment_start_sec": _format_float(segment_start_sec),
            "segment_end_sec": _format_float(segment_end_sec),
            "recording_start_sec": _format_float(recording_start_sec),
            "recording_end_sec": _format_float(recording_end_sec),
        }

    async def build_csv_rows(
        self,
        *,
        project_id: UUID,
        set_id: UUID,
        finalized_only: bool = False,
    ) -> list[dict[str, str]]:
        """Build every CamtrapDP + offset row dict for a set (no header).

        Shared by :meth:`export_csv_stream` (streaming CSV endpoint) and the
        dataset ZIP export so the column logic is defined exactly once.

        Raises :class:`ValueError` if the set does not exist (caller maps 404).
        When ``finalized_only`` is True the rows are scoped to finalized
        (``ANNOTATED``) segments only.
        """
        await self._require_set(set_id)

        annotations = await self._fetch_annotations(
            set_id, finalized_only=finalized_only
        )
        project = await self._detection._load_project(project_id)
        license_value = (
            project.license
            if project is not None and project.license is not None
            else ""
        )
        license_history_url = DetectionExportService._build_license_history_url(
            project_id
        )
        recording_h3_map = await self._build_recording_h3_map(annotations)

        return [
            self._build_row(
                ann,
                project=project,
                license_value=license_value,
                license_history_url=license_history_url,
                recording_h3_map=recording_h3_map,
            )
            for ann in annotations
        ]

    @staticmethod
    def render_csv(rows: list[dict[str, str]]) -> str:
        """Render header + rows to a CamtrapDP + offset CSV string.

        Used by the dataset ZIP export to embed ``annotations.csv``. The column
        order matches the streaming endpoint's header exactly.
        """
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_ANNOTATION_SET_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buf.getvalue()

    async def export_csv_stream(
        self,
        *,
        project_id: UUID,
        set_id: UUID,
    ) -> AsyncIterator[bytes]:
        """Stream the annotation-set CSV row-by-row.

        Yields the header row first (committing the response headers), then one
        row per ``TimeRangeAnnotation``. Raises :class:`ValueError` BEFORE the
        first yield if the set does not exist (the caller maps this to 404).
        """
        # build_csv_rows raises ValueError BEFORE the first yield if the set
        # does not exist, keeping the response status uncommitted (404 mapping
        # happens at the caller).
        rows = await self.build_csv_rows(project_id=project_id, set_id=set_id)

        # ----- header row (commits the response) --------------------------
        header_buf = io.StringIO()
        header_writer = csv.DictWriter(
            header_buf, fieldnames=_ANNOTATION_SET_COLUMNS
        )
        header_writer.writeheader()
        yield header_buf.getvalue().encode("utf-8")

        # ----- data rows --------------------------------------------------
        for row in rows:
            row_buf = io.StringIO()
            row_writer = csv.DictWriter(
                row_buf, fieldnames=_ANNOTATION_SET_COLUMNS
            )
            row_writer.writerow(row)
            yield row_buf.getvalue().encode("utf-8")
