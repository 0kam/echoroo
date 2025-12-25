"""REST API routes for Species Detection Jobs.

DEPRECATED: This module is deprecated and no longer used.

All species detection functionality has been unified under the Foundation Models API.
New endpoints are available at:

- GET /api/v1/foundation_models/runs/{run_uuid}/progress
- GET /api/v1/foundation_models/runs/{run_uuid}/detections
- GET /api/v1/foundation_models/runs/{run_uuid}/detections/summary
- POST /api/v1/foundation_models/runs/{run_uuid}/detections/{clip_prediction_uuid}/review
- POST /api/v1/foundation_models/runs/{run_uuid}/detections/bulk-review

This file is kept for reference and can be safely deleted.

Species Detection Jobs allow running BirdNET or Perch models
on audio datasets to automatically detect and classify bird species.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from echoroo import api, models, schemas
from echoroo.routes.dependencies import (
    Session,
    EchorooSettings,
    get_current_user_dependency,
    get_optional_current_user_dependency,
)
from echoroo.routes.types import Limit, Offset

__all__ = ["get_species_detection_router"]


def get_species_detection_router(settings: EchorooSettings) -> APIRouter:
    """Create a router with Species Detection endpoints wired with authentication."""
    current_user_dep = get_current_user_dependency(settings)
    optional_user_dep = get_optional_current_user_dependency(settings)

    router = APIRouter()

    # =========================================================================
    # Species Detection Job CRUD
    # =========================================================================

    @router.get(
        "/",
        response_model=schemas.Page[schemas.SpeciesDetectionJob],
    )
    async def get_species_detection_jobs(
        session: Session,
        limit: Limit = 10,
        offset: Offset = 0,
        dataset_uuid: UUID | None = Query(default=None, description="Filter by dataset"),
        status_filter: schemas.SpeciesDetectionJobStatus | None = Query(
            default=None, alias="status", description="Filter by job status"
        ),
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.SpeciesDetectionJob]:
        """Get a paginated list of species detection jobs."""
        # Build filters
        filters = []
        if dataset_uuid is not None:
            # Get dataset ID from UUID
            from sqlalchemy import select
            dataset = await session.scalar(
                select(models.Dataset).where(models.Dataset.uuid == dataset_uuid)
            )
            if dataset:
                filters.append(models.SpeciesDetectionJob.dataset_id == dataset.id)
        if status_filter is not None:
            filters.append(models.SpeciesDetectionJob.status == status_filter.value)

        jobs, total = await api.species_detection_jobs.get_many(
            session,
            limit=limit,
            offset=offset,
            filters=filters if filters else None,
            user=user,
        )
        return schemas.Page(
            items=jobs,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.post(
        "/",
        response_model=schemas.SpeciesDetectionJob,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_species_detection_job(
        session: Session,
        data: schemas.SpeciesDetectionJobCreate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.SpeciesDetectionJob:
        """Create a new species detection job."""
        job = await api.species_detection_jobs.create(
            session,
            data,
            user=user,
        )
        await session.commit()
        return job

    @router.get(
        "/{job_uuid}",
        response_model=schemas.SpeciesDetectionJob,
    )
    async def get_species_detection_job(
        session: Session,
        job_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.SpeciesDetectionJob:
        """Get a species detection job by UUID."""
        return await api.species_detection_jobs.get(
            session,
            job_uuid,
            user=user,
        )

    @router.patch(
        "/{job_uuid}",
        response_model=schemas.SpeciesDetectionJob,
    )
    async def update_species_detection_job(
        session: Session,
        job_uuid: UUID,
        data: schemas.SpeciesDetectionJobUpdate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.SpeciesDetectionJob:
        """Update a species detection job (e.g., cancel it)."""
        job = await api.species_detection_jobs.get(
            session,
            job_uuid,
            user=user,
        )
        updated = await api.species_detection_jobs.update(
            session,
            job,
            data,
            user=user,
        )
        await session.commit()
        return updated

    @router.delete(
        "/{job_uuid}",
        response_model=schemas.SpeciesDetectionJob,
    )
    async def delete_species_detection_job(
        session: Session,
        job_uuid: UUID,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.SpeciesDetectionJob:
        """Delete a species detection job and all its results."""
        job = await api.species_detection_jobs.get(
            session,
            job_uuid,
            user=user,
        )
        deleted = await api.species_detection_jobs.delete(
            session,
            job,
            user=user,
        )
        await session.commit()
        return deleted

    # =========================================================================
    # Job Progress
    # =========================================================================

    @router.get(
        "/{job_uuid}/progress",
        response_model=schemas.SpeciesDetectionJobProgress,
    )
    async def get_job_progress(
        session: Session,
        job_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.SpeciesDetectionJobProgress:
        """Get progress information for a species detection job."""
        job = await api.species_detection_jobs.get(
            session,
            job_uuid,
            user=user,
        )
        return await api.species_detection_jobs.get_progress(
            session,
            job,
            user=user,
        )

    # =========================================================================
    # Detection Results
    # =========================================================================

    @router.get(
        "/{job_uuid}/detections",
        response_model=schemas.Page[schemas.DetectionResult],
    )
    async def get_detections(
        session: Session,
        job_uuid: UUID,
        limit: Limit = 50,
        offset: Offset = 0,
        species_tag_id: int | None = Query(default=None, description="Filter by species tag ID"),
        min_confidence: float | None = Query(default=None, ge=0.0, le=1.0, description="Minimum confidence"),
        max_confidence: float | None = Query(default=None, ge=0.0, le=1.0, description="Maximum confidence"),
        review_status: schemas.DetectionReviewStatus | None = Query(default=None, description="Filter by review status"),
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.Page[schemas.DetectionResult]:
        """Get paginated detection results for a job."""
        job = await api.species_detection_jobs.get(
            session,
            job_uuid,
            user=user,
        )
        detections, total = await api.species_detection_jobs.get_detections(
            session,
            job,
            limit=limit,
            offset=offset,
            species_tag_id=species_tag_id,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            review_status=review_status,
            user=user,
        )
        return schemas.Page(
            items=detections,
            total=total,
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/{job_uuid}/detections/summary",
        response_model=schemas.DetectionSummary,
    )
    async def get_detection_summary(
        session: Session,
        job_uuid: UUID,
        user: models.User | None = Depends(optional_user_dep),
    ) -> schemas.DetectionSummary:
        """Get summary statistics for detection results."""
        job = await api.species_detection_jobs.get(
            session,
            job_uuid,
            user=user,
        )
        return await api.species_detection_jobs.get_detection_summary(
            session,
            job,
            user=user,
        )

    # =========================================================================
    # Review Operations
    # =========================================================================

    @router.post(
        "/{job_uuid}/detections/{clip_prediction_uuid}/review",
        response_model=schemas.DetectionReview,
    )
    async def review_detection(
        session: Session,
        job_uuid: UUID,
        clip_prediction_uuid: UUID,
        data: schemas.DetectionReviewUpdate,
        user: models.User = Depends(current_user_dep),
    ) -> schemas.DetectionReview:
        """Review a single detection result."""
        job = await api.species_detection_jobs.get(
            session,
            job_uuid,
            user=user,
        )
        review = await api.species_detection_jobs.review_detection(
            session,
            job,
            clip_prediction_uuid,
            data,
            user=user,
        )
        await session.commit()
        return review

    @router.post(
        "/{job_uuid}/detections/bulk-review",
        response_model=dict,
    )
    async def bulk_review_detections(
        session: Session,
        job_uuid: UUID,
        clip_prediction_uuids: list[UUID] = Query(..., description="List of clip prediction UUIDs to review"),
        data: schemas.DetectionReviewUpdate = ...,
        user: models.User = Depends(current_user_dep),
    ) -> dict:
        """Bulk review multiple detection results."""
        job = await api.species_detection_jobs.get(
            session,
            job_uuid,
            user=user,
        )
        count = await api.species_detection_jobs.bulk_review_detections(
            session,
            job,
            clip_prediction_uuids,
            data,
            user=user,
        )
        await session.commit()
        return {"reviewed_count": count}

    return router
