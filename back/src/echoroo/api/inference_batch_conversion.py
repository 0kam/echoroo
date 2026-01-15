"""API for converting Inference Batch predictions to Annotation Projects."""

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

__all__ = [
    "convert_inference_batch_to_annotation_project",
]


async def convert_inference_batch_to_annotation_project(
    session: AsyncSession,
    inference_batch: schemas.InferenceBatch,
    name: str,
    description: str | None,
    user: models.User,
    confidence_threshold_override: float | None = None,
    include_only_positive: bool = True,
) -> schemas.AnnotationProject:
    """Convert inference batch predictions to annotation project.

    This function creates a new annotation project linked to the same dataset as
    the inference batch, then converts all (or filtered) predictions into
    annotation tasks with their corresponding tags.

    Parameters
    ----------
    session
        SQLAlchemy AsyncSession.
    inference_batch
        The inference batch to convert predictions from.
    name
        Name for the new annotation project.
    description
        Optional description for the annotation project.
    user
        The user creating the annotation project.
    confidence_threshold_override
        Override the batch's confidence threshold. If None, uses batch threshold.
    include_only_positive
        If True, only include predictions where predicted_positive is True.

    Returns
    -------
    schemas.AnnotationProject
        The created annotation project.

    Raises
    ------
    exceptions.InvalidDataError
        If no predictions are found matching the criteria.
    exceptions.NotFoundError
        If required entities are not found.
    exceptions.PermissionDeniedError
        If the user lacks permission to create the annotation project.
    """
    # Get the database model for the inference batch
    db_batch = await session.scalar(
        select(models.InferenceBatch)
        .where(models.InferenceBatch.uuid == inference_batch.uuid)
        .options(
            selectinload(models.InferenceBatch.custom_model).selectinload(
                models.CustomModel.target_tag
            ),
            selectinload(models.InferenceBatch.dataset_scopes).selectinload(
                models.InferenceBatchDatasetScope.dataset
            ),
        )
    )
    if db_batch is None:
        raise exceptions.NotFoundError(
            f"Inference batch with uuid {inference_batch.uuid} not found"
        )

    # Get custom model and target tag
    custom_model = db_batch.custom_model
    if custom_model is None:
        raise exceptions.InvalidDataError(
            "Inference batch has no associated custom model"
        )

    target_tag = custom_model.target_tag
    if target_tag is None:
        raise exceptions.InvalidDataError(
            "Custom model has no target tag defined"
        )

    # Find a dataset to associate with the annotation project
    # Use the first dataset scope's dataset
    dataset: models.Dataset | None = None
    if db_batch.dataset_scopes:
        dataset = db_batch.dataset_scopes[0].dataset
    else:
        # Fallback: try to get dataset from ML project
        if db_batch.ml_project_id is not None:
            ml_project_scope = await session.scalar(
                select(models.MLProjectDatasetScope)
                .where(models.MLProjectDatasetScope.ml_project_id == db_batch.ml_project_id)
                .options(selectinload(models.MLProjectDatasetScope.dataset))
            )
            if ml_project_scope is not None:
                dataset = ml_project_scope.dataset

    if dataset is None:
        raise exceptions.InvalidDataError(
            "Could not determine dataset for annotation project"
        )

    # Check permissions - user must be able to manage the project
    if not await can_manage_project(session, dataset.project_id, user):
        raise exceptions.PermissionDeniedError(
            "You do not have permission to create annotation projects for this dataset"
        )

    # Determine confidence threshold
    threshold = confidence_threshold_override or db_batch.confidence_threshold

    # Build query for predictions
    predictions_query = (
        select(models.InferencePrediction)
        .options(selectinload(models.InferencePrediction.clip))
        .where(
            models.InferencePrediction.inference_batch_id == db_batch.id,
            models.InferencePrediction.confidence >= threshold,
        )
    )

    # Filter to only positive predictions if requested
    if include_only_positive:
        predictions_query = predictions_query.where(
            models.InferencePrediction.predicted_positive.is_(True)
        )

    result = await session.execute(predictions_query)
    predictions = result.scalars().unique().all()

    if not predictions:
        raise exceptions.InvalidDataError(
            "No predictions found matching the specified criteria"
        )

    # Create the annotation project
    try:
        annotation_project = await annotation_projects.create(
            session,
            name=name,
            description=description or "",
            user=user,
            dataset_id=dataset.id,
        )
    except exceptions.DuplicateObjectError:
        raise exceptions.DuplicateObjectError(
            f"An annotation project with the name '{name}' already exists. "
            "Please choose a different name."
        )

    # Add target tag to the project using batch insert
    now = datetime.datetime.now(datetime.timezone.utc)
    project_tag_values = [
        {
            "annotation_project_id": annotation_project.id,
            "tag_id": target_tag.id,
            "created_on": now,
        }
    ]
    stmt = pg_insert(models.AnnotationProjectTag).values(project_tag_values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["annotation_project_id", "tag_id"]
    )
    await session.execute(stmt)
    await session.flush()

    # Collect unique clips from predictions
    clip_ids = list({pred.clip_id for pred in predictions})

    # Batch create clip annotations
    clip_annotation_data = [{"clip_id": clip_id} for clip_id in clip_ids]
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

    # Batch create annotation tasks
    annotation_task_data = [
        {
            "annotation_project_id": annotation_project.id,
            "clip_id": clip_id,
            "clip_annotation_id": clip_id_to_annotation[clip_id].id,
        }
        for clip_id in clip_ids
    ]
    for batch in batched(annotation_task_data, 500):
        for datum in batch:
            task = models.AnnotationTask(**datum)
            session.add(task)
    await session.flush()

    # Create clip annotation tags for each prediction
    # Use set to deduplicate (in case of multiple predictions for same clip)
    clip_annotation_tags_set: set[tuple[int, int, UUID]] = set()
    user_id = user.id

    for pred in predictions:
        clip_annotation = clip_id_to_annotation.get(pred.clip_id)
        if clip_annotation is not None:
            clip_annotation_tags_set.add(
                (clip_annotation.id, target_tag.id, user_id)
            )

    # Batch insert clip annotation tags
    if clip_annotation_tags_set:
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

    # Reload annotation_project with tags to return complete schema
    reloaded_project = await session.scalar(
        select(models.AnnotationProject)
        .where(models.AnnotationProject.id == annotation_project.id)
        .options(selectinload(models.AnnotationProject.tags))
    )

    return schemas.AnnotationProject.model_validate(reloaded_project)
