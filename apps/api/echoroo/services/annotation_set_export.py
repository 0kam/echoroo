"""Annotation-set CSV export service (CamtrapDP + ToriTore extension).

This mirrors :mod:`echoroo.services.detection_export` so that ground-truth
``TimeRangeAnnotation`` rows can be exported with the SAME CamtrapDP
``observations.csv`` column shape used by the BirdNET / detection export. The
only difference is three trailing ToriTore per-annotator proficiency columns
appended **after** the detection export's FR-086 block:

* ``annotator_species_score``  — the annotator's per-species correct rate at
  annotation time.
* ``annotator_total_score``    — the annotator's latest ToriTore total score.
* ``annotator_test_reference`` — a human-readable reference to the ToriTore
  test that produced the snapshot.

CamtrapDP-compliant readers ignore unknown trailing columns, so the extension
is non-breaking. Raw lat / lng / GPS columns are intentionally absent (FR-028 /
SC-016); the row's location precision is disclosed via the reused
``location_generalization`` / ``withheld_reason`` helpers.

The export is **read-only** — no migration is introduced. All FR-086 license /
H3-resolution / generalization logic is REUSED from
:class:`echoroo.services.detection_export.DetectionExportService` rather than
duplicated, so the two exports stay consistent.
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
from echoroo.services.detection_export import (
    _CAMTRAPDP_COLUMNS,
    _DEFAULT_MEMBER_H3_RESOLUTION,
    DetectionExportService,
    _format_event_datetime,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from echoroo.models.project import Project

# Three ToriTore per-annotator proficiency columns appended AFTER the detection
# export's CamtrapDP + FR-086 block. Kept module-level so the streaming header
# row and each data row share EXACTLY the same field order.
_TORITORE_COLUMNS = [
    "annotator_species_score",
    "annotator_total_score",
    "annotator_test_reference",
]

# Full ordered column list = detection export's CamtrapDP/FR-086 columns plus
# the three ToriTore trailing columns.
_ANNOTATION_SET_COLUMNS = [*_CAMTRAPDP_COLUMNS, *_TORITORE_COLUMNS]


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

    def __init__(self, db: AsyncSession) -> None:
        """Initialise with an async database session."""
        self.db = db
        # Reuse the detection export helpers (license, H3 map, generalization).
        self._detection = DetectionExportService(db)

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
        self, set_id: UUID
    ) -> list[TimeRangeAnnotation]:
        """Load all TimeRangeAnnotations in a set with relationships for export.

        Eager-loads:

        * ``segment.recording`` (+ ``recording.dataset`` for deploymentID),
        * ``taxon`` (for ``scientificName``),
        * ``created_by`` (for the annotator display name).
        """
        result = await self.db.execute(
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
        """Render one CamtrapDP + FR-086 + ToriTore row for ``ann``."""
        segment = ann.segment
        recording = segment.recording if segment else None
        dataset_name = (
            recording.dataset.name if recording and recording.dataset else ""
        )
        recording_uuid = str(recording.id) if recording else ""
        recording_datetime = recording.datetime if recording else None
        recording_id = recording.id if recording else None

        # Absolute event datetime = recording start + segment offset + annotation
        # offset (start / end). Reuses the detection export formatter.
        segment_offset = segment.start_time_sec if segment else 0.0
        event_start = _format_event_datetime(
            recording_datetime, segment_offset + ann.start_time_sec
        )
        event_end = _format_event_datetime(
            recording_datetime, segment_offset + ann.end_time_sec
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
            "observationID": str(ann.id),
            "deploymentID": dataset_name,
            "mediaID": recording_uuid,
            "eventID": str(ann.id),
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
            # ToriTore per-annotator proficiency snapshot columns.
            "annotator_species_score": _format_float(ann.annotator_species_score),
            "annotator_total_score": _format_float(ann.annotator_total_score),
            "annotator_test_reference": ann.annotator_test_reference or "",
        }

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
        # 404 mapping happens at the caller; raising before the first yield
        # keeps the response status uncommitted.
        await self._require_set(set_id)

        annotations = await self._fetch_annotations(set_id)
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

        # ----- header row (commits the response) --------------------------
        header_buf = io.StringIO()
        header_writer = csv.DictWriter(
            header_buf, fieldnames=_ANNOTATION_SET_COLUMNS
        )
        header_writer.writeheader()
        yield header_buf.getvalue().encode("utf-8")

        # ----- data rows --------------------------------------------------
        for ann in annotations:
            row_buf = io.StringIO()
            row_writer = csv.DictWriter(
                row_buf, fieldnames=_ANNOTATION_SET_COLUMNS
            )
            row_writer.writerow(
                self._build_row(
                    ann,
                    project=project,
                    license_value=license_value,
                    license_history_url=license_history_url,
                    recording_h3_map=recording_h3_map,
                )
            )
            yield row_buf.getvalue().encode("utf-8")
