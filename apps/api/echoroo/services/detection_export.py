"""Detection export service for CSV and ML dataset generation."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.annotation import Annotation
from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.models.dataset import Dataset
from echoroo.models.enums import DetectionSource, DetectionStatus
from echoroo.models.recording import Recording


class _AnnotationEntry(TypedDict):
    """Internal annotation entry for ML dataset export."""

    recording_filename: str
    recording_path: str
    start_time: float
    end_time: float
    species: str
    confidence: float | None
    label: str


# CamtrapDP observations.csv columns in standard order
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
]


def _format_event_datetime(
    recording_datetime: datetime | None,
    offset_seconds: float,
) -> str:
    """Format an absolute ISO 8601 datetime from recording start + offset.

    Args:
        recording_datetime: Base datetime of the recording (timezone-aware or naive).
        offset_seconds: Offset in seconds from the recording start.

    Returns:
        ISO 8601 string with Z suffix, or empty string if datetime is None.
    """
    if recording_datetime is None:
        return ""
    result = recording_datetime + timedelta(seconds=offset_seconds)
    return result.strftime("%Y-%m-%dT%H:%M:%SZ")


class DetectionExportService:
    """Service for exporting detection data as CSV or ML training datasets."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize service with database session.

        Args:
            db: Async database session
        """
        self.db = db

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

        Produces a 31-column CSV conforming to the CamtrapDP standard for
        bioacoustic observations. Each annotation becomes one row.

        Column mapping:
        - observationID: annotation UUID
        - deploymentID: dataset name
        - mediaID: recording UUID
        - eventID: annotation UUID (same as observationID for audio detections)
        - eventStart/eventEnd: absolute ISO 8601 datetime (recording start + offset)
        - classificationMethod: "machine" for ML detections, "human" for manual
        - classifiedBy: model name for machine, user email for human
        - classificationTimestamp: annotation creation timestamp
        - scientificName: tag name
        - observationComments: empty (no free-text notes in this model)

        Args:
            project_id: Project UUID to filter annotations by
            status: Optional detection status filter
            tag_id: Optional tag UUID filter
            dataset_id: Optional dataset UUID filter
            detection_run_id: Optional detection run UUID filter
            search_session_id: Optional search session UUID filter

        Returns:
            CSV content as a string in CamtrapDP format
        """
        annotations = await self._fetch_annotations_for_export(
            project_id=project_id,
            status=status,
            tag_id=tag_id,
            dataset_id=dataset_id,
            detection_run_id=detection_run_id,
            search_session_id=search_session_id,
        )

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_CAMTRAPDP_COLUMNS)
        writer.writeheader()

        for ann in annotations:
            recording = ann.recording
            dataset_name = recording.dataset.name if recording and recording.dataset else ""
            recording_uuid = str(recording.id) if recording else ""
            recording_datetime = recording.datetime if recording else None

            event_start = _format_event_datetime(recording_datetime, ann.start_time)
            event_end = _format_event_datetime(recording_datetime, ann.end_time)

            # Determine classification method and classified_by
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
                        classified_by = f"{ann.detection_run.model_name} {ann.detection_run.model_version}"
                else:
                    classified_by = ann.source.value
            else:
                classification_method = "human"
                if ann.reviewed_by:
                    classified_by = ann.reviewed_by.display_name or ann.reviewed_by.email
                else:
                    classified_by = ""

            # Use reviewed_at for human annotations, created_at for machine
            if ann.reviewed_at is not None:
                classification_timestamp = ann.reviewed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif ann.created_at is not None:
                classification_timestamp = ann.created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                classification_timestamp = ""

            writer.writerow({
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
            })

        return output.getvalue()

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
