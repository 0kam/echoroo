"""CamtrapDP export functions for annotation projects.

This module provides functions to export annotation projects to the CamtrapDP
observations.csv format, which is a standard format for camera trap and
bioacoustic observation data.

See: https://github.com/camera-traps/bioacoustics
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import TYPE_CHECKING, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo import models, schemas
from echoroo.api.annotation_tasks import annotation_tasks
from echoroo.filters.annotation_tasks import (
    AnnotationProjectFilter as AnnotationTaskAnnotationProjectFilter,
)

if TYPE_CHECKING:
    pass

__all__ = [
    "to_camtrapdp_csv",
]


# CamtrapDP CSV columns in order
CAMTRAPDP_COLUMNS = [
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


def _format_datetime(
    recording_datetime: dt.datetime | None,
    offset_seconds: float,
) -> str:
    """Format a datetime with offset in ISO format.

    Parameters
    ----------
    recording_datetime
        The base datetime of the recording.
    offset_seconds
        The offset in seconds from the recording start.

    Returns
    -------
    str
        ISO formatted datetime string, or empty if datetime is None.
    """
    if recording_datetime is None:
        return ""

    # Add offset to the recording datetime
    result = recording_datetime + dt.timedelta(seconds=offset_seconds)
    return result.strftime("%Y-%m-%dT%H:%M:%SZ")


async def to_camtrapdp_csv(
    session: AsyncSession,
    annotation_project: schemas.AnnotationProject,
) -> str:
    """Export an annotation project to CamtrapDP observations.csv format.

    This function converts all annotations in the project to the CamtrapDP
    format, which is a standardized format for bioacoustic observations.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession.
    annotation_project
        The annotation project to export.

    Returns
    -------
    str
        CSV content as a string.

    Notes
    -----
    Each species tag on an annotation becomes a separate row in the CSV.
    The observationID is a combination of the clip annotation UUID and the tag ID.
    """
    # Get all annotation tasks
    tasks, _ = await annotation_tasks.get_many(
        session,
        limit=-1,
        filters=[AnnotationTaskAnnotationProjectFilter(eq=annotation_project.uuid)],
    )

    if not tasks:
        # Return empty CSV with headers only
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=CAMTRAPDP_COLUMNS)
        writer.writeheader()
        return output.getvalue()

    # Get clip annotations with their clips and tags
    task_ids = [t.id for t in tasks]
    stmt = (
        select(models.AnnotationTask)
        .where(models.AnnotationTask.id.in_(task_ids))
        .options(
            selectinload(models.AnnotationTask.clip_annotation)
            .selectinload(models.ClipAnnotation.clip)
            .selectinload(models.Clip.recording),
            selectinload(models.AnnotationTask.clip_annotation)
            .selectinload(models.ClipAnnotation.clip_annotation_tags)
            .selectinload(models.ClipAnnotationTag.tag),
            selectinload(models.AnnotationTask.clip_annotation)
            .selectinload(models.ClipAnnotation.clip_annotation_tags)
            .selectinload(models.ClipAnnotationTag.created_by),
            selectinload(models.AnnotationTask.clip_annotation)
            .selectinload(models.ClipAnnotation.notes)
            .selectinload(models.Note.created_by),
        )
    )
    result = await session.execute(stmt)
    db_tasks = result.scalars().unique().all()

    # Get dataset information
    dataset = await session.get(models.Dataset, annotation_project.dataset_id)
    deployment_id = dataset.name if dataset else ""

    # Get source model information if available
    db_project = await session.get(models.AnnotationProject, annotation_project.id)
    classification_method = "human"
    classified_by = ""

    if db_project and db_project.source_foundation_model_run_id:
        # Load the foundation model run with its model
        fm_run = await session.get(
            models.FoundationModelRun,
            db_project.source_foundation_model_run_id,
            options=[selectinload(models.FoundationModelRun.foundation_model)],
        )
        if fm_run and fm_run.foundation_model:
            classification_method = "machine"
            classified_by = fm_run.foundation_model.display_name

    # Build CSV rows
    rows: list[dict[str, str]] = []

    for db_task in db_tasks:
        clip_annotation = db_task.clip_annotation
        if not clip_annotation:
            continue

        clip = clip_annotation.clip
        if not clip:
            continue

        recording = clip.recording
        if not recording:
            continue

        # Get recording datetime
        recording_datetime = recording.datetime

        # Calculate event times
        event_start = _format_datetime(recording_datetime, clip.start_time)
        event_end = _format_datetime(recording_datetime, clip.end_time)

        # Get notes as comments
        comments = "; ".join(
            note.message for note in clip_annotation.notes if note.message
        )

        # Get tags and create a row for each species tag
        clip_tags = clip_annotation.clip_annotation_tags
        species_tags = [
            ct for ct in clip_tags if ct.tag and ct.tag.key == "species"
        ]

        if not species_tags:
            # No species tags, create a row with empty scientificName
            row = _create_row(
                clip_annotation=clip_annotation,
                clip=clip,
                recording=recording,
                deployment_id=deployment_id,
                event_start=event_start,
                event_end=event_end,
                scientific_name="",
                classification_method=classification_method,
                classified_by=classified_by,
                tag_created_by=None,
                classification_timestamp="",
                comments=comments,
            )
            rows.append(row)
        else:
            for clip_tag in species_tags:
                # Use the tag creator as classified_by if human-classified
                tag_classified_by = classified_by
                tag_classification_timestamp = ""

                if classification_method == "human" and clip_tag.created_by:
                    tag_classified_by = clip_tag.created_by.name or clip_tag.created_by.username

                # Get classification timestamp from tag creation
                if hasattr(clip_tag, "created_on") and clip_tag.created_on:
                    tag_classification_timestamp = clip_tag.created_on.strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )

                row = _create_row(
                    clip_annotation=clip_annotation,
                    clip=clip,
                    recording=recording,
                    deployment_id=deployment_id,
                    event_start=event_start,
                    event_end=event_end,
                    scientific_name=clip_tag.tag.value if clip_tag.tag else "",
                    classification_method=classification_method,
                    classified_by=tag_classified_by,
                    tag_created_by=clip_tag.created_by,
                    classification_timestamp=tag_classification_timestamp,
                    comments=comments,
                )
                rows.append(row)

    # Write CSV
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CAMTRAPDP_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)

    return output.getvalue()


def _create_row(
    *,
    clip_annotation: models.ClipAnnotation,
    clip: models.Clip,
    recording: models.Recording,
    deployment_id: str,
    event_start: str,
    event_end: str,
    scientific_name: str,
    classification_method: str,
    classified_by: str,
    tag_created_by: models.User | None,
    classification_timestamp: str,
    comments: str,
) -> dict[str, str]:
    """Create a single CamtrapDP observation row.

    Parameters
    ----------
    clip_annotation
        The clip annotation model.
    clip
        The clip model.
    recording
        The recording model.
    deployment_id
        The deployment ID (typically dataset name).
    event_start
        ISO formatted event start time.
    event_end
        ISO formatted event end time.
    scientific_name
        The species scientific name (tag value).
    classification_method
        "machine" or "human".
    classified_by
        Name of the classifier (model or user).
    tag_created_by
        User who created the tag (for human classification).
    classification_timestamp
        ISO formatted classification timestamp.
    comments
        Observation comments from notes.

    Returns
    -------
    dict[str, str]
        A dictionary representing one row in the CSV.
    """
    # Create unique observation ID by combining clip annotation UUID and tag
    observation_id = str(clip_annotation.uuid)
    if scientific_name:
        # Append a hash of the scientific name to make unique per-species
        observation_id = f"{clip_annotation.uuid}_{hash(scientific_name) & 0xFFFFFFFF:08x}"

    return {
        "observationID": observation_id,
        "deploymentID": deployment_id,
        "mediaID": str(recording.uuid),
        "eventID": str(clip.uuid),
        "eventStart": event_start,
        "eventEnd": event_end,
        "observationLevel": "media",
        "observationType": "audio",
        "deviceSetupType": "",
        "scientificName": scientific_name,
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
        "frequencyLow": "",
        "frequencyHigh": "",
        "classificationMethod": classification_method,
        "classifiedBy": classified_by,
        "classificationTimestamp": classification_timestamp,
        "classificationProbability": "",
        "classificationConfirmation": "",
        "observationTags": "",
        "observationComments": comments,
    }
