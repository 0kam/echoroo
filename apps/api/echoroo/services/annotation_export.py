"""Annotation export service for multiple format output."""

import csv
import io
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.annotation_project import AnnotationProject
from echoroo.models.annotation_task import AnnotationTask
from echoroo.models.clip_annotation import ClipAnnotation
from echoroo.models.sound_event_annotation import SoundEventAnnotation

VALID_FORMATS = {"json", "csv", "aoef"}


class AnnotationExportService:
    """Service for exporting annotations in multiple formats."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the service with a database session.

        Args:
            db: Async database session
        """
        self.db = db

    async def export_annotations(
        self,
        annotation_project_id: UUID,
        format: str,
    ) -> dict[str, Any] | str:
        """Export annotations for a project.

        Args:
            annotation_project_id: The annotation project to export
            format: Export format (json, csv, aoef)

        Returns:
            Formatted export data as dict (JSON/AOEF) or str (CSV)

        Raises:
            HTTPException: 404 if annotation project not found
            HTTPException: 422 if format is not supported
        """
        if format not in VALID_FORMATS:
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported export format '{format}'. Valid options: {', '.join(sorted(VALID_FORMATS))}",
            )

        data = await self._get_export_data(annotation_project_id)

        if format == "csv":
            return self._format_csv(data)
        if format == "aoef":
            return self._format_aoef(data)
        return self._format_json(data)

    async def _get_export_data(self, annotation_project_id: UUID) -> dict[str, Any]:
        """Gather all annotation data for export.

        Queries the annotation project along with all associated tasks,
        clip annotations, sound event annotations, and tags.

        Args:
            annotation_project_id: AnnotationProject UUID to export

        Returns:
            Structured dictionary containing project metadata and all annotations

        Raises:
            HTTPException: 404 if annotation project not found
        """
        # Fetch the annotation project
        project_result = await self.db.execute(
            select(AnnotationProject).where(AnnotationProject.id == annotation_project_id)
        )
        annotation_project = project_result.scalar_one_or_none()

        if annotation_project is None:
            raise HTTPException(
                status_code=404,
                detail="Annotation project not found",
            )

        # Fetch tasks with clip annotations and sound events loaded eagerly
        tasks_result = await self.db.execute(
            select(AnnotationTask)
            .where(AnnotationTask.annotation_project_id == annotation_project_id)
            .options(
                selectinload(AnnotationTask.clip_annotation).selectinload(
                    ClipAnnotation.sound_events
                ).selectinload(SoundEventAnnotation.tags),
                selectinload(AnnotationTask.clip_annotation).selectinload(ClipAnnotation.tags),
                selectinload(AnnotationTask.clip),
            )
        )
        tasks = list(tasks_result.scalars().all())

        # Build structured export data
        annotations: list[dict[str, Any]] = []
        for task in tasks:
            clip_annotation = task.clip_annotation
            if clip_annotation is None:
                continue

            sound_events: list[dict[str, Any]] = []
            for sea in clip_annotation.sound_events:
                sound_events.append(
                    {
                        "id": str(sea.id),
                        "geometry": sea.geometry,
                        "source": sea.source.value,
                        "confidence": sea.confidence,
                        "tags": [
                            {"name": t.name, "category": t.category.value} for t in sea.tags
                        ],
                        "created_at": sea.created_at.isoformat() if sea.created_at else None,
                    }
                )

            annotations.append(
                {
                    "clip_annotation_id": str(clip_annotation.id),
                    "task_id": str(task.id),
                    "clip": {
                        "id": str(task.clip.id),
                        "start_time": task.clip.start_time,
                        "end_time": task.clip.end_time,
                    },
                    "review_status": clip_annotation.review_status.value,
                    "tags": [
                        {"name": t.name, "category": t.category.value}
                        for t in clip_annotation.tags
                    ],
                    "sound_events": sound_events,
                    "created_at": clip_annotation.created_at.isoformat()
                    if clip_annotation.created_at
                    else None,
                }
            )

        return {
            "annotation_project": {
                "id": str(annotation_project.id),
                "name": annotation_project.name,
                "description": annotation_project.description,
                "instructions": annotation_project.instructions,
                "visibility": annotation_project.visibility.value,
                "created_at": annotation_project.created_at.isoformat()
                if annotation_project.created_at
                else None,
            },
            "annotations": annotations,
        }

    def _format_json(self, data: dict[str, Any]) -> dict[str, Any]:
        """Format export data as structured JSON.

        Returns:
            Dictionary with annotation_project metadata and annotations array
        """
        return data

    def _format_csv(self, data: dict[str, Any]) -> str:
        """Format export data as Raven Selection Table-compatible CSV.

        Each sound event annotation becomes one row. Clips without sound
        events produce no rows.

        Columns:
            Selection, View, Channel, Begin Time (s), End Time (s),
            Low Freq (Hz), High Freq (Hz), Tags, Source, Confidence, File

        Args:
            data: Structured annotation export data from _get_export_data

        Returns:
            CSV string in Raven Selection Table format
        """
        output = io.StringIO()
        writer = csv.writer(output, dialect="excel")

        headers = [
            "Selection",
            "View",
            "Channel",
            "Begin Time (s)",
            "End Time (s)",
            "Low Freq (Hz)",
            "High Freq (Hz)",
            "Tags",
            "Source",
            "Confidence",
            "File",
        ]
        writer.writerow(headers)

        selection_counter = 1
        for annotation in data["annotations"]:
            clip = annotation["clip"]
            clip_start = clip["start_time"]

            for sea in annotation["sound_events"]:
                geometry = sea["geometry"]
                geo_type = geometry.get("type", "")

                # Derive begin/end times and frequency bounds from geometry
                if geo_type == "BoundingBox":
                    coordinates = geometry.get("coordinates", [0, 0, 0, 0])
                    begin_time = clip_start + coordinates[0]
                    end_time = clip_start + coordinates[2]
                    low_freq: float | str = coordinates[1]
                    high_freq: float | str = coordinates[3]
                elif geo_type == "TimeInterval":
                    coordinates = geometry.get("coordinates", [0, 0])
                    begin_time = clip_start + coordinates[0]
                    end_time = clip_start + coordinates[1]
                    low_freq = ""
                    high_freq = ""
                else:
                    begin_time = clip_start
                    end_time = clip["end_time"]
                    low_freq = ""
                    high_freq = ""

                tags_str = ";".join(
                    f"{t['name']}:{t['category']}" for t in sea["tags"]
                )
                confidence: float | str = (
                    sea["confidence"] if sea["confidence"] is not None else ""
                )
                file_ref = clip["id"]

                writer.writerow(
                    [
                        selection_counter,
                        "Spectrogram 1",
                        1,
                        begin_time,
                        end_time,
                        low_freq,
                        high_freq,
                        tags_str,
                        sea["source"],
                        confidence,
                        file_ref,
                    ]
                )
                selection_counter += 1

        return output.getvalue()

    def _format_aoef(self, data: dict[str, Any]) -> dict[str, Any]:
        """Format export data as AOEF (Audio Object Event Format).

        AOEF is a JSON-based format compatible with the soundevent library.
        Structure follows the soundevent AOEF schema.

        Args:
            data: Structured annotation export data from _get_export_data

        Returns:
            AOEF-structured dictionary
        """
        clip_annotations: list[dict[str, Any]] = []
        sound_event_annotations: list[dict[str, Any]] = []

        for annotation in data["annotations"]:
            clip = annotation["clip"]

            clip_annotation_record: dict[str, Any] = {
                "id": annotation["clip_annotation_id"],
                "clip": {
                    "id": clip["id"],
                    "start_time": clip["start_time"],
                    "end_time": clip["end_time"],
                },
                "review_status": annotation["review_status"],
                "tags": annotation["tags"],
                "created_at": annotation["created_at"],
            }
            clip_annotations.append(clip_annotation_record)

            for sea in annotation["sound_events"]:
                sound_event_annotations.append(
                    {
                        "id": sea["id"],
                        "clip_annotation_id": annotation["clip_annotation_id"],
                        "geometry": sea["geometry"],
                        "source": sea["source"],
                        "confidence": sea["confidence"],
                        "tags": sea["tags"],
                        "created_at": sea["created_at"],
                    }
                )

        return {
            "info": {
                "format": "aoef",
                "version": "1.0",
                "annotation_project": data["annotation_project"],
            },
            "clip_annotations": clip_annotations,
            "sound_event_annotations": sound_event_annotations,
        }
