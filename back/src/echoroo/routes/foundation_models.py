"""Routes for foundation model metadata and runs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from echoroo import exceptions, models, schemas
from echoroo.api import foundation_models
from echoroo.api.common.permissions import can_view_dataset
from echoroo.routes.dependencies import (
    Session,
    EchorooSettings,
    get_current_user_dependency,
    get_optional_current_user_dependency,
)
from echoroo.routes.types import Limit, Offset
from echoroo.routes.species_filters import get_species_filter_applications_router

__all__ = ["get_foundation_model_router"]


def get_foundation_model_router(settings: EchorooSettings) -> APIRouter:
    """Create router for foundation model endpoints."""
    current_user_dep = get_current_user_dependency(settings)
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    # =========================================================================
    # Foundation Model Metadata
    # =========================================================================

    @router.get(
        "/",
        response_model=list[schemas.FoundationModel],
    )
    async def list_models(
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """List available foundation models."""
        return await foundation_models.list_models(session)

    @router.get(
        "/queue-status",
        response_model=schemas.JobQueueStatus,
    )
    async def get_queue_status(
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get current job queue status counts."""
        return await foundation_models.get_queue_status(session)

    @router.get(
        "/datasets/{dataset_uuid}/summary/",
        response_model=list[schemas.DatasetFoundationModelSummary],
    )
    async def get_dataset_summary(
        dataset_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Return summary of latest runs for each model on a dataset."""
        dataset = await foundation_models.get_dataset(
            session,
            dataset_uuid,
            user=user,
        )
        return await foundation_models.get_dataset_summary(session, dataset)

    # =========================================================================
    # Foundation Model Runs
    # =========================================================================

    @router.get(
        "/runs/",
        response_model=schemas.Page[schemas.FoundationModelRun],
    )
    async def list_runs(
        session: Session,
        dataset_uuid: UUID | None = Query(default=None),
        foundation_model_slug: str | None = Query(default=None),
        status: models.FoundationModelRunStatus | None = Query(default=None),
        limit: Limit = 20,
        offset: Offset = 0,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """List past runs, optionally filtered by dataset."""
        dataset_id: int | None = None
        if dataset_uuid:
            dataset = await foundation_models.get_dataset(
                session,
                dataset_uuid,
                user=user,
            )
            dataset_id = dataset.id

        model_id: int | None = None
        if foundation_model_slug:
            model = await foundation_models.get_model_by_slug(
                session,
                foundation_model_slug,
            )
            model_id = model.id

        runs, total = await foundation_models.list_runs(
            session,
            dataset_id=dataset_id,
            foundation_model_id=model_id,
            status=status,
            limit=limit,
            offset=offset,
            user=user,
        )
        return schemas.Page(
            items=runs,
            total=total,
            offset=offset,
            limit=limit,
        )

    @router.post(
        "/runs/",
        response_model=schemas.FoundationModelRun,
        status_code=status.HTTP_201_CREATED,
    )
    async def enqueue_run(
        data: schemas.FoundationModelRunCreate,
        session: Session,
        user: models.User = Depends(current_user_dep),
    ):
        """Trigger a new foundation model run."""
        dataset = await foundation_models.get_dataset(
            session,
            data.dataset_uuid,
            user=user,
        )
        model = await foundation_models.get_model_by_slug(
            session,
            data.foundation_model_slug,
        )
        run = await foundation_models.enqueue_run(
            session,
            dataset,
            model,
            user=user,
            confidence_threshold=data.confidence_threshold,
            scope=data.scope,
            locale=data.locale,
        )
        await session.commit()
        return run

    @router.get(
        "/runs/{run_uuid}",
        response_model=schemas.FoundationModelRun,
    )
    async def get_run(
        run_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get a foundation model run by UUID."""
        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        dataset = run_schema.dataset
        if dataset is None:
            raise exceptions.NotFoundError("Run dataset not found")

        if not await can_view_dataset(session, dataset, user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to view this foundation model run",
            )

        return run_schema

    @router.post(
        "/runs/{run_uuid}/cancel",
        response_model=schemas.FoundationModelRun,
    )
    async def cancel_run(
        run_uuid: UUID,
        session: Session,
        user: models.User = Depends(current_user_dep),
    ):
        """Cancel a running or queued foundation model run."""
        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        result = await foundation_models.cancel_run(
            session,
            run_schema,
            user=user,
        )
        await session.commit()
        return result

    @router.get(
        "/runs/{run_uuid}/species/",
        response_model=schemas.FoundationModelRun,
    )
    async def get_run_species(
        run_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Retrieve species summary for a run."""
        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        dataset = run_schema.dataset
        if dataset is None:
            raise exceptions.NotFoundError("Run dataset not found")

        if not await can_view_dataset(session, dataset, user):
            raise exceptions.PermissionDeniedError(
                "You do not have permission to view this foundation model run",
            )

        run_model = await foundation_models.get_run(session, run_uuid)
        species = await foundation_models.list_species(session, run_model)
        run_schema.species = species
        return run_schema

    # =========================================================================
    # Run Progress (from Species Detection API)
    # =========================================================================

    @router.get(
        "/runs/{run_uuid}/progress",
        response_model=schemas.FoundationModelRunProgress,
    )
    async def get_run_progress(
        run_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get detailed progress information for a foundation model run."""
        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        return await foundation_models.get_run_progress(
            session,
            run_schema,
            user=user,
        )

    # =========================================================================
    # Detection Results (from Species Detection API)
    # =========================================================================

    @router.get(
        "/runs/{run_uuid}/detections",
        response_model=schemas.Page[schemas.DetectionResult],
    )
    async def get_detections(
        run_uuid: UUID,
        session: Session,
        limit: Limit = 50,
        offset: Offset = 0,
        species_tag_id: int | None = Query(default=None, description="Filter by species tag ID"),
        min_confidence: float | None = Query(default=None, ge=0.0, le=1.0, description="Minimum confidence"),
        max_confidence: float | None = Query(default=None, ge=0.0, le=1.0, description="Maximum confidence"),
        review_status: schemas.DetectionReviewStatus | None = Query(default=None, description="Filter by review status"),
        filter_uuid: UUID | None = Query(default=None, description="UUID of species filter application to apply"),
        include_excluded: bool = Query(default=False, description="Include detections excluded by the filter"),
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get paginated detection results for a run.

        When filter_uuid is provided:
        - Only detections that passed the species filter are returned (is_included=True)
        - Set include_excluded=True to also include excluded detections
        - The is_included field will be populated in the response
        """
        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        detections, total = await foundation_models.get_detections(
            session,
            run_schema,
            limit=limit,
            offset=offset,
            species_tag_id=species_tag_id,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            review_status=review_status,
            filter_uuid=filter_uuid,
            include_excluded=include_excluded,
            user=user,
        )
        return schemas.Page(
            items=detections,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/runs/{run_uuid}/detections/summary",
        response_model=schemas.DetectionSummary,
    )
    async def get_detection_summary(
        run_uuid: UUID,
        session: Session,
        user: models.User | None = Depends(optional_user_dep),
    ):
        """Get summary statistics for detection results."""
        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        return await foundation_models.get_detection_summary(
            session,
            run_schema,
            user=user,
        )

    # =========================================================================
    # Review Operations (from Species Detection API)
    # =========================================================================

    @router.post(
        "/runs/{run_uuid}/detections/{clip_prediction_uuid}/review",
        response_model=schemas.DetectionReview,
    )
    async def review_detection(
        run_uuid: UUID,
        clip_prediction_uuid: UUID,
        data: schemas.DetectionReviewUpdate,
        session: Session,
        user: models.User = Depends(current_user_dep),
    ):
        """Review a single detection result."""
        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        review = await foundation_models.review_detection(
            session,
            run_schema,
            clip_prediction_uuid,
            data,
            user=user,
        )
        await session.commit()
        return review

    @router.post(
        "/runs/{run_uuid}/detections/bulk-review",
        response_model=dict,
    )
    async def bulk_review_detections(
        run_uuid: UUID,
        data: schemas.DetectionReviewUpdate,
        session: Session,
        clip_prediction_uuids: list[UUID] = Query(..., description="List of clip prediction UUIDs to review"),
        user: models.User = Depends(current_user_dep),
    ):
        """Bulk review multiple detection results."""
        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        count = await foundation_models.bulk_review_detections(
            session,
            run_schema,
            clip_prediction_uuids,
            data,
            user=user,
        )
        await session.commit()
        return {"reviewed_count": count}

    # =========================================================================
    # Conversion to Annotation Project
    # =========================================================================

    @router.post(
        "/runs/{run_uuid}/convert-to-annotation-project",
        response_model=schemas.ConvertToAnnotationProjectResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def convert_to_annotation_project(
        run_uuid: UUID,
        request: schemas.ConvertToAnnotationProjectRequest,
        session: Session,
        user: models.User = Depends(current_user_dep),
    ):
        """Convert foundation model detections to an annotation project.

        Creates a new annotation project from the detection results of a
        foundation model run. Each detection becomes an annotation task
        with the detected species tags.

        When include_only_filtered is True, only detections that passed
        the specified species filter are included. This requires providing
        the species_filter_application_uuid.
        """
        from echoroo.api.foundation_model_conversion import (
            convert_foundation_model_run_to_annotation_project,
        )

        run_schema = await foundation_models.get_run_with_relations(
            session,
            run_uuid,
        )
        result = await convert_foundation_model_run_to_annotation_project(
            session,
            run_schema,
            name=request.name,
            description=request.description,
            user=user,
            include_only_filtered=request.include_only_filtered,
            species_filter_application_uuid=request.species_filter_application_uuid,
        )
        await session.commit()
        return result

    # =========================================================================
    # Species Filter Applications (nested under runs)
    # =========================================================================

    filter_applications_router = get_species_filter_applications_router(settings)
    router.include_router(
        filter_applications_router,
        prefix="/runs/{run_uuid}/species-filter-applications",
        tags=["Species Filters"],
    )

    return router
