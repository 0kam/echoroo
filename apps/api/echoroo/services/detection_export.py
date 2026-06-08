"""Detection export service for CSV and ML dataset generation.

Phase 6 (US2 / FR-086 / SC-016) extensions:

* CSV exports include four new trailing columns — ``license``,
  ``license_history_url``, ``location_generalization``, and
  ``withheld_reason`` — appended **after** the CamtrapDP standard columns to
  preserve CamtrapDP compatibility while satisfying FR-086 disclosure
  requirements. Consumers reading only the canonical CamtrapDP columns are
  unaffected.
* The export path **never** emits raw latitude / longitude / lat / lng / GPS
  fields (FR-028 / FR-030 / FR-031 / SC-016). The schema simply does not
  include those columns; defence in depth is provided by the
  ``lint_no_raw_coordinates`` CI step.
* ``location_generalization`` is the effective H3 resolution applied to the
  row's site. For Restricted projects it falls back to the project's
  ``public_location_precision_h3_res`` toggle, otherwise it is derived from
  the Site's H3 index resolution (or ``H3_RES_9`` when no Site is attached).
* ``withheld_reason`` is one of ``None`` / ``project_toggle`` /
  ``taxon_sensitivity:<category>``. The Phase 11 taxon-sensitivity preload
  pipeline will refine this; Phase 6 emits ``project_toggle`` when the
  Restricted toggle clamped the resolution and ``None`` otherwise.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.core.stream_guard import (
    CSV_RECHECK_INTERVAL,
    SENTINEL_BYTES,
    PermissionRevokedMidStream,
    audit_stream_revoked,
    recheck_action_permission,
)
from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DetectionSource, DetectionStatus, ProjectVisibility
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.recording_annotation import (
    RecordingAnnotation as Annotation,  # Phase 14+ deferred (was rich-shape Annotation)
)
from echoroo.models.site import Site

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import Request

    from echoroo.core.permissions import Action

logger = logging.getLogger(__name__)


class _AnnotationEntry(TypedDict):
    """Internal annotation entry for ML dataset export."""

    recording_filename: str
    recording_path: str
    start_time: float
    end_time: float
    species: str
    confidence: float | None
    label: str


# CamtrapDP observations.csv columns in standard order. Extended with four
# Phase 6 / FR-086 trailing columns appended **after** the CamtrapDP block —
# CamtrapDP-compliant readers ignore unknown trailing columns, so the
# extension is non-breaking. NOTE: raw lat/lng / latitude / longitude
# columns are intentionally absent (FR-028 / SC-016).
_CAMTRAPDP_COLUMNS = [
    "observationID",
    "deploymentID",
    "mediaID",
    "eventID",
    "eventStart",
    "eventEnd",
    "observationLevel",
    "observationType",
    "deviceSetupType",
    "scientificName",
    "count",
    "lifeStage",
    "sex",
    "behavior",
    "individualID",
    "individualPositionRadius",
    "individualPositionAngle",
    "individualSpeed",
    "bboxX",
    "bboxY",
    "bboxWidth",
    "bboxHeight",
    "frequencyLow",
    "frequencyHigh",
    "classificationMethod",
    "classifiedBy",
    "classificationTimestamp",
    "classificationProbability",
    "classificationConfirmation",
    "observationTags",
    "observationComments",
    # FR-086 trailing extensions (non-CamtrapDP):
    "license",
    "license_history_url",
    "location_generalization",
    "withheld_reason",
]

# Default H3 resolution exposed to a Member-equivalent exporter when no
# Site / Recording-level resolution is recorded. Matches the response-filter
# fallback (echoroo.core.permissions.H3_RES_9) for consistency.
_DEFAULT_MEMBER_H3_RESOLUTION = 9


def _format_event_datetime(
    recording_datetime: datetime | None,
    offset_seconds: float,
) -> str:
    """Format an absolute ISO 8601 datetime from recording start + offset.

    Sub-second precision is preserved: the offset is added as a float (no int
    truncation) and the output carries a millisecond fraction, uniformly — a
    whole-second value renders as ``.000``. Audio detections / annotations often
    have fractional-second boundaries (many are shorter than one second), so
    truncating to whole seconds would drop their real duration. The trailing
    ``Z`` (UTC) suffix style is preserved from the previous implementation.

    Args:
        recording_datetime: Base datetime of the recording (timezone-aware or naive).
        offset_seconds: Offset in seconds from the recording start (float;
            fractional part preserved).

    Returns:
        ISO 8601 string with millisecond fraction and ``Z`` suffix
        (e.g. ``2026-06-04T05:23:25.450Z``), or empty string if datetime is None.
    """
    if recording_datetime is None:
        return ""
    result = recording_datetime + timedelta(seconds=float(offset_seconds))
    # Emit millisecond (3 fractional-digit) precision while keeping the existing
    # ``Z`` UTC suffix; recording datetimes are stored UTC.
    return result.strftime("%Y-%m-%dT%H:%M:%S.") + f"{result.microsecond // 1000:03d}Z"


class DetectionExportService:
    """Service for exporting detection data as CSV or ML training datasets."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            db: Async database session
        """
        self.db = db

    async def _load_project(self, project_id: UUID) -> Project | None:
        """Fetch the project row used to populate FR-086 license/toggle fields."""
        result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def _build_recording_h3_resolution_map(
        self,
        annotations: list[Annotation],
    ) -> dict[UUID, int]:
        """Pre-load the Site H3 resolution for every recording in the export.

        Returns a mapping ``{recording_id -> h3_resolution}``. Recordings
        without an attached Site (or with an unparseable H3 index) fall back
        to :data:`_DEFAULT_MEMBER_H3_RESOLUTION`.

        We intentionally **do not** read raw lat / lng — FR-028 keeps those
        out of the schema entirely. The Site stores only the H3 index, which
        is privacy-safe because H3 cells are fixed grid identifiers.
        """
        recording_ids = {ann.recording_id for ann in annotations if ann.recording_id is not None}
        if not recording_ids:
            return {}

        result = await self.db.execute(
            select(Recording.id, Site.h3_index_member)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .join(Site, Dataset.site_id == Site.id, isouter=True)
            .where(Recording.id.in_(recording_ids))
        )

        try:
            import h3 as _h3
        except ImportError:  # pragma: no cover - defensive when h3 missing
            _h3 = None

        out: dict[UUID, int] = {}
        for rec_id, h3_index_member in result.all():
            res = _DEFAULT_MEMBER_H3_RESOLUTION
            if h3_index_member and _h3 is not None:
                try:
                    res = int(_h3.get_resolution(h3_index_member))
                except Exception:  # noqa: BLE001 - treat malformed as default
                    res = _DEFAULT_MEMBER_H3_RESOLUTION
            out[rec_id] = res
        return out

    @staticmethod
    def _compute_export_location_generalization(
        *,
        project: Project | None,
        site_resolution: int,
    ) -> tuple[int, str | None]:
        """Compute ``(location_generalization, withheld_reason)`` for one row.

        FR-086 disclosure: the export consumer sees the H3 resolution that
        was applied to this row's location, plus a reason when the value
        was clamped below the Site's natural resolution.

        Phase 6 scope:

        * **Restricted** projects honour ``public_location_precision_h3_res``;
          if that value is below ``site_resolution`` the row is clamped and
          ``withheld_reason='project_toggle'``.
        * **Public** projects expose the Site's natural H3 resolution and
          report ``withheld_reason=None``.
        * Per-recording / per-taxon sensitivity (FR-035 / FR-036) lands in
          Phase 11; once the bulk preload is wired the override path will
          plug in here without changing the column shape.
        """
        if project is None:
            return site_resolution, None

        visibility = getattr(project, "visibility", None)
        if visibility == ProjectVisibility.RESTRICTED:
            cfg = getattr(project, "restricted_config", None) or {}
            toggle_res = cfg.get("public_location_precision_h3_res")
            if isinstance(toggle_res, int) and toggle_res < site_resolution:
                return toggle_res, "project_toggle"
            if isinstance(toggle_res, int):
                return toggle_res, None
        return site_resolution, None

    @staticmethod
    def _build_license_history_url(project_id: UUID) -> str:
        """Build the FR-087 ``license_history`` reference URL for the export."""
        return f"/api/v1/projects/{project_id}/license-history"

    def _build_csv_row(
        self,
        ann: Annotation,
        *,
        project: Project | None,
        license_value: str,
        license_history_url: str,
        recording_h3_map: dict[UUID, int],
    ) -> dict[str, str]:
        """Render a single CamtrapDP+FR-086 row dict for ``ann``.

        Extracted so the buffered :meth:`export_csv` and the streaming
        :meth:`export_csv_stream` (Phase 17 A-5 Hybrid Contract) share
        EXACTLY the same row shape.
        """
        recording = ann.recording
        dataset_name = recording.dataset.name if recording and recording.dataset else ""
        recording_uuid = str(recording.id) if recording else ""
        recording_datetime = recording.datetime if recording else None

        event_start = _format_event_datetime(recording_datetime, ann.start_time)
        event_end = _format_event_datetime(recording_datetime, ann.end_time)

        machine_sources = {
            DetectionSource.BIRDNET,
            DetectionSource.PERCH,
            DetectionSource.PERCH_SEARCH,
            DetectionSource.SIMILARITY_SEARCH,
        }
        if ann.source in machine_sources:
            classification_method = "machine"
            if ann.detection_run:
                classified_by = ann.detection_run.model_name
                if ann.detection_run.model_version:
                    classified_by = (
                        f"{ann.detection_run.model_name} {ann.detection_run.model_version}"
                    )
            else:
                classified_by = ann.source.value
        else:
            classification_method = "human"
            if ann.reviewed_by:
                classified_by = ann.reviewed_by.display_name or ann.reviewed_by.email
            else:
                classified_by = ""

        if ann.reviewed_at is not None:
            classification_timestamp = ann.reviewed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif ann.created_at is not None:
            classification_timestamp = ann.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            classification_timestamp = ""

        site_res = (
            recording_h3_map.get(ann.recording_id, _DEFAULT_MEMBER_H3_RESOLUTION)
            if ann.recording_id is not None
            else _DEFAULT_MEMBER_H3_RESOLUTION
        )
        location_generalization, withheld_reason = (
            self._compute_export_location_generalization(
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
            "observationLevel": "media",
            "observationType": "audio",
            "deviceSetupType": "",
            "scientificName": ann.tag.name if ann.tag else "",
            "count": "",
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
            "frequencyLow": f"{ann.freq_low:.1f}" if ann.freq_low is not None else "",
            "frequencyHigh": f"{ann.freq_high:.1f}" if ann.freq_high is not None else "",
            "classificationMethod": classification_method,
            "classifiedBy": classified_by,
            "classificationTimestamp": classification_timestamp,
            "classificationProbability": (
                f"{ann.confidence:.4f}" if ann.confidence is not None else ""
            ),
            "classificationConfirmation": "",
            "observationTags": "",
            "observationComments": "",
            # FR-086 trailing extensions
            "license": license_value,
            "license_history_url": license_history_url,
            "location_generalization": str(location_generalization),
            "withheld_reason": withheld_reason if withheld_reason is not None else "",
        }

    async def export_csv(
        self,
        project_id: UUID,
        status: DetectionStatus | None = None,
        tag_id: UUID | None = None,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        search_session_id: UUID | None = None,
    ) -> str:
        """Export detections as a CamtrapDP observations.csv formatted string.

        Buffered legacy form preserved for back-compat with existing
        callers (notably ``tests/security/search_leak/test_export_csv_no_lat_lng.py``
        which depends on ``export_csv() -> str``). New router code should
        prefer :meth:`export_csv_stream` so the Phase 17 A-5 mid-stream
        permission re-check can fire.
        """
        annotations = await self._fetch_annotations_for_export(
            project_id=project_id,
            status=status,
            tag_id=tag_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
            search_session_id=search_session_id,
        )

        # FR-086 metadata loaded once per export.
        project = await self._load_project(project_id)
        license_value = (
            project.license
            if project is not None and project.license is not None
            else ""
        )
        license_history_url = self._build_license_history_url(project_id)
        recording_h3_map = await self._build_recording_h3_resolution_map(annotations)

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_CAMTRAPDP_COLUMNS)
        writer.writeheader()
        for ann in annotations:
            writer.writerow(
                self._build_csv_row(
                    ann,
                    project=project,
                    license_value=license_value,
                    license_history_url=license_history_url,
                    recording_h3_map=recording_h3_map,
                )
            )
        return output.getvalue()

    async def export_csv_stream(
        self,
        project_id: UUID,
        *,
        action: Action,
        current_user: Any,
        request: Request,
        stream_type: str = "csv_export",
        status: DetectionStatus | None = None,
        tag_id: UUID | None = None,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        search_session_id: UUID | None = None,
    ) -> AsyncIterator[bytes]:
        """Stream the CamtrapDP CSV row-by-row with a mid-stream permission guard.

        Phase 17 backlog A-5 Hybrid Contract:

        * The header row is yielded immediately so the response status and
          ``Content-Disposition`` headers commit before the first re-check.
        * Every :data:`CSV_RECHECK_INTERVAL` rows the generator calls
          :func:`recheck_action_permission` against the request-scoped
          session. PostgreSQL READ COMMITTED guarantees the new SELECT
          observes any sibling-request revoke that has committed.
        * On detection of a mid-stream revoke the generator catches
          :class:`PermissionRevokedMidStream`, writes
          ``stream.permission_revoked_mid_stream`` via a fresh audit
          session (M-2 fix — the streaming session is no longer safe for
          the SERIALIZABLE audit write), yields :data:`SENTINEL_BYTES`
          so audit consumers can detect truncation, and returns.

        The exception is NEVER propagated past the generator — Starlette
        cannot turn a generator-time exception into an HTTP 4xx because
        the response status was already committed when the header row
        was yielded.

        NOTE: pre-start gating remains the caller's responsibility via
        :func:`gate_action`. If the request is denied at gate-time, the
        endpoint returns 403 BEFORE any chunk is yielded.
        """
        annotations = await self._fetch_annotations_for_export(
            project_id=project_id,
            status=status,
            tag_id=tag_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
            search_session_id=search_session_id,
        )
        project = await self._load_project(project_id)
        license_value = (
            project.license
            if project is not None and project.license is not None
            else ""
        )
        license_history_url = self._build_license_history_url(project_id)
        recording_h3_map = await self._build_recording_h3_resolution_map(annotations)

        user_id = getattr(current_user, "id", None)
        request_id = getattr(getattr(request, "state", None), "request_id", "") or ""
        client = getattr(request, "client", None)
        ip = getattr(client, "host", "") or ""
        user_agent = ""
        try:
            user_agent = request.headers.get("user-agent", "") or ""
        except Exception:  # noqa: BLE001 — defensive against test stubs
            user_agent = ""

        # ----- emit header row (commits the response) ---------------------
        header_buf = io.StringIO()
        header_writer = csv.DictWriter(header_buf, fieldnames=_CAMTRAPDP_COLUMNS)
        header_writer.writeheader()
        yield header_buf.getvalue().encode("utf-8")

        # ----- emit rows + periodic re-check ------------------------------
        for index, ann in enumerate(annotations):
            if index > 0 and index % CSV_RECHECK_INTERVAL == 0:
                try:
                    await recheck_action_permission(
                        db=self.db,
                        action=action,
                        project_id=project_id,
                        current_user=current_user,
                        request=request,
                    )
                except PermissionRevokedMidStream as exc:
                    await audit_stream_revoked(
                        project_id=project_id,
                        user_id=user_id,
                        stream_type=stream_type,
                        request_id=request_id,
                        ip=ip,
                        user_agent=user_agent,
                        reason=str(exc),
                    )
                    yield SENTINEL_BYTES
                    return

            row_buf = io.StringIO()
            row_writer = csv.DictWriter(row_buf, fieldnames=_CAMTRAPDP_COLUMNS)
            row_writer.writerow(
                self._build_csv_row(
                    ann,
                    project=project,
                    license_value=license_value,
                    license_history_url=license_history_url,
                    recording_h3_map=recording_h3_map,
                )
            )
            yield row_buf.getvalue().encode("utf-8")

    async def export_ml_dataset(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
    ) -> bytes:
        """Export ML training dataset as ZIP bytes.

        The ZIP archive contains:
        - annotations.csv: Clip-level annotations with audio file references
        - metadata.json: Export metadata including counts and species list
        - README.txt: Human-readable dataset description

        Positive entries come from confirmed annotations; negative entries are
        derived from confirmed regions that have no overlapping confirmed
        annotation (i.e. the reviewer listened but confirmed no species).

        Args:
            project_id: Project UUID to scope the export
            dataset_id: Optional dataset UUID filter
            detection_run_id: Optional detection run UUID filter

        Returns:
            ZIP archive as bytes
        """
        # Fetch confirmed annotations (positive examples)
        confirmed = await self._fetch_annotations_for_export(
            project_id=project_id,
            status=DetectionStatus.CONFIRMED,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
        )

        # Fetch confirmed regions for deriving negative examples
        confirmed_regions = await self._fetch_confirmed_regions(
            project_id=project_id,
            dataset_id=dataset_id,
        )

        # Build annotation entries from confirmed detections
        entries: list[_AnnotationEntry] = []
        for ann in confirmed:
            entries.append({
                "recording_filename": ann.recording.filename if ann.recording else "",
                "recording_path": ann.recording.path if ann.recording else "",
                "start_time": ann.start_time,
                "end_time": ann.end_time,
                "species": ann.tag.name if ann.tag else "",
                "confidence": ann.confidence,
                "label": "positive",
            })

        # Derive negative entries from confirmed regions that do not overlap
        # with any positive annotation in the same recording
        for region in confirmed_regions:
            region_filename = region.recording.filename if region.recording else ""
            has_positive_overlap = False
            for e in entries:
                if (
                    e["recording_filename"] == region_filename
                    and e["start_time"] <= region.end_time
                    and e["end_time"] >= region.start_time
                    and e["label"] == "positive"
                ):
                    has_positive_overlap = True
                    break
            if not has_positive_overlap:
                entries.append({
                    "recording_filename": region_filename,
                    "recording_path": region.recording.path if region.recording else "",
                    "start_time": region.start_time,
                    "end_time": region.end_time,
                    "species": "",
                    "confidence": None,
                    "label": "negative",
                })

        # Assemble ZIP archive in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # --- annotations.csv ---
            csv_output = io.StringIO()
            writer = csv.writer(csv_output)
            writer.writerow([
                "recording_filename",
                "start_time",
                "end_time",
                "species",
                "confidence",
                "label",
            ])
            for entry in entries:
                writer.writerow([
                    entry["recording_filename"],
                    f"{entry['start_time']:.3f}",
                    f"{entry['end_time']:.3f}",
                    entry["species"],
                    f"{entry['confidence']:.4f}" if entry["confidence"] is not None else "",
                    entry["label"],
                ])
            zf.writestr("annotations.csv", csv_output.getvalue())

            # --- metadata.json ---
            exported_at = datetime.now(UTC).isoformat()
            species_set: set[str] = {e["species"] for e in entries if e["species"]}
            species_list = sorted(species_set)
            metadata = {
                "project_id": str(project_id),
                "dataset_id": str(dataset_id) if dataset_id else None,
                "exported_at": exported_at,
                "total_entries": len(entries),
                "positive_count": sum(1 for e in entries if e["label"] == "positive"),
                "negative_count": sum(1 for e in entries if e["label"] == "negative"),
                "species": species_list,
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

            # --- README.txt ---
            readme_lines = [
                "Echoroo ML Training Dataset",
                "===========================",
                "",
                f"Exported: {exported_at}",
                f"Total entries: {metadata['total_entries']}",
                f"Positive (confirmed detections): {metadata['positive_count']}",
                f"Negative (reviewed, no detection): {metadata['negative_count']}",
                f"Species: {', '.join(species_list) if species_list else 'None'}",
                "",
                "Files:",
                "- annotations.csv: Annotation data with recording file references",
                "- metadata.json: Export metadata",
                "- README.txt: This file",
                "",
                "Note: Audio files are referenced by path. Use recording_filename",
                "and start_time/end_time to extract audio clips from the originals.",
                "",
            ]
            zf.writestr("README.txt", "\n".join(readme_lines))

        return zip_buffer.getvalue()

    async def _fetch_annotations_for_export(
        self,
        project_id: UUID,
        status: DetectionStatus | None = None,
        tag_id: UUID | None = None,
        dataset_id: UUID | None = None,
        detection_run_id: UUID | None = None,
        search_session_id: UUID | None = None,
    ) -> list[Annotation]:
        """Fetch annotations with all relationships needed for export.

        Joins through Recording -> Dataset to enforce project-level scoping.

        Args:
            project_id: Project UUID for scoping
            status: Optional status filter
            tag_id: Optional tag UUID filter
            dataset_id: Optional dataset UUID filter
            detection_run_id: Optional detection run UUID filter
            search_session_id: Optional search session UUID filter

        Returns:
            List of Annotation instances with eagerly loaded relationships
        """
        query = (
            select(Annotation)
            .join(Recording, Annotation.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
            .options(
                selectinload(Annotation.recording),
                selectinload(Annotation.tag),
                selectinload(Annotation.detection_run),
                selectinload(Annotation.reviewed_by),
            )
            .order_by(Recording.filename, Annotation.start_time)
        )

        if status is not None:
            query = query.where(Annotation.status == status)
        if tag_id is not None:
            query = query.where(Annotation.tag_id == tag_id)
        if dataset_id is not None:
            query = query.where(Recording.dataset_id == dataset_id)
        if detection_run_id is not None:
            query = query.where(Annotation.detection_run_id == detection_run_id)
        if search_session_id is not None:
            query = query.where(Annotation.search_session_id == search_session_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _fetch_confirmed_regions(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
    ) -> list[ConfirmedRegion]:
        """Fetch confirmed regions with recording relationships for export.

        Joins through Recording -> Dataset to enforce project-level scoping.

        Args:
            project_id: Project UUID for scoping
            dataset_id: Optional dataset UUID filter

        Returns:
            List of ConfirmedRegion instances with eagerly loaded recording
        """
        query = (
            select(ConfirmedRegion)
            .join(Recording, ConfirmedRegion.recording_id == Recording.id)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .where(Dataset.project_id == project_id)
            .options(selectinload(ConfirmedRegion.recording))
            .order_by(Recording.filename, ConfirmedRegion.start_time)
        )

        if dataset_id is not None:
            query = query.where(Recording.dataset_id == dataset_id)

        result = await self.db.execute(query)
        return list(result.scalars().all())
