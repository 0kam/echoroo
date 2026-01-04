"""API for converting Foundation Model detection results to Annotation Projects."""

from __future__ import annotations

import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo import exceptions, models, schemas
from echoroo.api import annotation_projects
from echoroo.api.common.permissions import can_manage_project
from echoroo.api.common.utils import batched
from echoroo.api.foundation_models import foundation_models
from echoroo.schemas.foundation_model_conversion import (
    ConvertToAnnotationProjectResponse,
)

__all__ = [
    "convert_foundation_model_run_to_annotation_project",
]


async def convert_foundation_model_run_to_annotation_project(
    session: AsyncSession,
    foundation_model_run: schemas.FoundationModelRun,
    name: str,
    description: str | None,
    user: models.User,
    include_only_filtered: bool = False,
    species_filter_application_uuid: UUID | None = None,
) -> ConvertToAnnotationProjectResponse:
    """Convert all detections from a Foundation Model Run to an Annotation Project.

    This function creates a new annotation project linked to the same dataset as
    the foundation model run, then converts all (or filtered) detections into
    annotation tasks with their corresponding tags.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession.
    foundation_model_run
        The foundation model run to convert detections from.
    name
        Name for the new annotation project.
    description
        Optional description for the annotation project.
    user
        The user creating the annotation project.
    include_only_filtered
        If True, only include detections that passed the species filter.
    species_filter_application_uuid
        UUID of the species filter application to use for filtering.
        Required if include_only_filtered is True.

    Returns
    -------
    ConvertToAnnotationProjectResponse
        Response containing details about the created annotation project.

    Raises
    ------
    exceptions.ValidationError
        If include_only_filtered is True but no filter application is provided.
    exceptions.NotFoundError
        If the species filter application is not found.
    exceptions.PermissionDeniedError
        If the user lacks permission to create the annotation project.
    """
    # Validate parameters
    if include_only_filtered and species_filter_application_uuid is None:
        raise exceptions.ValidationError(
            "species_filter_application_uuid is required when include_only_filtered is True"
        )

    # Get the database model for the run
    db_run = await foundation_models.get_run(session, foundation_model_run.uuid)

    # Get the dataset
    dataset = await session.get(models.Dataset, db_run.dataset_id)
    if dataset is None:
        raise exceptions.NotFoundError(
            f"Dataset with id {db_run.dataset_id} not found"
        )

    # Check permissions - user must be able to manage the project
    if not await can_manage_project(session, dataset.project_id, user):
        raise exceptions.PermissionDeniedError(
            "You do not have permission to create annotation projects for this dataset"
        )

    # Get the model_run_id for querying predictions
    model_run_id = db_run.model_run_id
    if model_run_id is None:
        if db_run.species_detection_job_id is None:
            raise exceptions.ValidationError(
                "Foundation model run has no associated predictions"
            )
        job = await session.get(
            models.SpeciesDetectionJob,
            db_run.species_detection_job_id,
        )
        if job is None or job.model_run_id is None:
            raise exceptions.ValidationError(
                "Foundation model run has no associated predictions"
            )
        model_run_id = job.model_run_id

    # Get species filter application if filtering is requested
    filter_application: models.SpeciesFilterApplication | None = None
    if species_filter_application_uuid is not None:
        filter_application = await session.scalar(
            select(models.SpeciesFilterApplication).where(
                models.SpeciesFilterApplication.uuid == species_filter_application_uuid,
                models.SpeciesFilterApplication.foundation_model_run_id == db_run.id,
            )
        )
        if filter_application is None:
            raise exceptions.NotFoundError(
                f"Species filter application with uuid {species_filter_application_uuid} "
                f"not found for this run"
            )

    # Fetch all clip predictions linked to this model run
    predictions_query = (
        select(models.ClipPrediction)
        .join(
            models.ModelRunPrediction,
            models.ClipPrediction.id == models.ModelRunPrediction.clip_prediction_id,
        )
        .options(
            selectinload(models.ClipPrediction.clip).selectinload(
                models.Clip.recording
            ),
            selectinload(models.ClipPrediction.tags).selectinload(
                models.ClipPredictionTag.tag
            ),
        )
        .where(models.ModelRunPrediction.model_run_id == model_run_id)
    )

    # Apply species filter if requested
    if filter_application is not None and include_only_filtered:
        predictions_query = predictions_query.join(
            models.SpeciesFilterMask,
            (models.ClipPrediction.id == models.SpeciesFilterMask.clip_prediction_id)
            & (
                models.SpeciesFilterMask.species_filter_application_id
                == filter_application.id
            ),
        ).where(models.SpeciesFilterMask.is_included.is_(True))

    result = await session.execute(predictions_query)
    clip_predictions = result.scalars().unique().all()

    if not clip_predictions:
        raise exceptions.ValidationError(
            "No detections found to convert to annotation project"
        )

    # Collect all unique species tags from predictions
    # If a filter application is specified, only include tags that passed the filter
    unique_tags: dict[int, schemas.Tag] = {}
    if filter_application is not None:
        # Get the set of tag IDs that passed the filter (is_included=True)
        passed_tags_query = (
            select(models.SpeciesFilterMask.tag_id)
            .where(
                models.SpeciesFilterMask.species_filter_application_id
                == filter_application.id,
                models.SpeciesFilterMask.is_included.is_(True),
            )
            .distinct()
        )
        passed_tags_result = await session.execute(passed_tags_query)
        passed_tag_ids = set(passed_tags_result.scalars().all())

        for cp in clip_predictions:
            for cpt in cp.tags:
                if cpt.tag_id in passed_tag_ids and cpt.tag_id not in unique_tags:
                    unique_tags[cpt.tag_id] = schemas.Tag.model_validate(cpt.tag)
    else:
        for cp in clip_predictions:
            for cpt in cp.tags:
                if cpt.tag_id not in unique_tags:
                    unique_tags[cpt.tag_id] = schemas.Tag.model_validate(cpt.tag)

    # Create the annotation project with source tracking
    try:
        annotation_project = await annotation_projects.create(
            session,
            name=name,
            description=description or "",
            user=user,
            dataset_id=dataset.id,
            source_foundation_model_run_id=db_run.id,
            source_species_filter_application_id=(
                filter_application.id if filter_application else None
            ),
        )
    except exceptions.DuplicateObjectError:
        raise exceptions.DuplicateObjectError(
            f"An annotation project with the name '{name}' already exists. "
            "Please choose a different name."
        )

    # Batch insert annotation project tags using ON CONFLICT DO NOTHING
    if unique_tags:
        now = datetime.datetime.now(datetime.timezone.utc)
        project_tag_values = [
            {
                "annotation_project_id": annotation_project.id,
                "tag_id": tag_id,
                "created_on": now,
            }
            for tag_id in unique_tags.keys()
        ]
        for batch in batched(project_tag_values, 500):
            stmt = pg_insert(models.AnnotationProjectTag).values(list(batch))
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["annotation_project_id", "tag_id"]
            )
            await session.execute(stmt)
        await session.flush()

    # Update annotation_project schema with added tags
    annotation_project = annotation_project.model_copy(
        update={"tags": list(unique_tags.values())}
    )

    # Group predictions by clip to avoid creating duplicate tasks
    clip_to_predictions: dict[int, list[models.ClipPrediction]] = {}
    for cp in clip_predictions:
        if cp.clip_id not in clip_to_predictions:
            clip_to_predictions[cp.clip_id] = []
        clip_to_predictions[cp.clip_id].append(cp)

    # Batch create clip annotations
    clip_annotation_data = [
        {"clip_id": clip_id} for clip_id in clip_to_predictions.keys()
    ]
    clip_annotation_objs: list[models.ClipAnnotation] = []
    for batch in batched(clip_annotation_data, 500):
        for datum in batch:
            ann = models.ClipAnnotation(**datum)
            session.add(ann)
            clip_annotation_objs.append(ann)
    await session.flush()

    # Build mapping from clip_id to clip_annotation
    clip_id_to_annotation: dict[int, models.ClipAnnotation] = {
        ann.clip_id: ann for ann in clip_annotation_objs
    }

    annotations_created = len(clip_annotation_objs)

    # Batch create annotation tasks
    annotation_task_data = [
        {
            "annotation_project_id": annotation_project.id,
            "clip_id": clip_id,
            "clip_annotation_id": clip_id_to_annotation[clip_id].id,
        }
        for clip_id in clip_to_predictions.keys()
    ]
    for batch in batched(annotation_task_data, 500):
        for datum in batch:
            task = models.AnnotationTask(**datum)
            session.add(task)
    await session.flush()

    tasks_created = len(annotation_task_data)

    # Collect all clip annotation tags for batch insert
    # Using a set to deduplicate (clip_annotation_id, tag_id, created_by_id)
    clip_annotation_tags_set: set[tuple[int, int, UUID | None]] = set()
    user_id = user.id

    for clip_id, preds in clip_to_predictions.items():
        clip_annotation = clip_id_to_annotation[clip_id]
        for pred in preds:
            for cpt in pred.tags:
                # Only include tags that passed the filter (if filtering is applied)
                if cpt.tag_id in unique_tags:
                    clip_annotation_tags_set.add(
                        (clip_annotation.id, cpt.tag_id, user_id)
                    )

    # Batch insert clip annotation tags using ON CONFLICT DO NOTHING
    if clip_annotation_tags_set:
        now = datetime.datetime.now(datetime.timezone.utc)
        clip_annotation_tag_values = [
            {
                "clip_annotation_id": clip_ann_id,
                "tag_id": tag_id,
                "created_by_id": created_by_id,
                "created_on": now,
            }
            for clip_ann_id, tag_id, created_by_id in clip_annotation_tags_set
        ]
        for batch in batched(clip_annotation_tag_values, 500):
            stmt = pg_insert(models.ClipAnnotationTag).values(list(batch))
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["clip_annotation_id", "tag_id", "created_by_id"]
            )
            await session.execute(stmt)
        await session.flush()

    return ConvertToAnnotationProjectResponse(
        annotation_project_uuid=annotation_project.uuid,
        annotation_project_name=annotation_project.name,
        total_tasks_created=tasks_created,
        total_annotations_created=annotations_created,
        total_tags_added=len(unique_tags),
    )
