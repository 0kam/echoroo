"""DetectionRun service for business logic."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunStatus
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.schemas.detection_run import (
    DetectionRunCreate,
    DetectionRunListResponse,
    DetectionRunResponse,
    DetectionRunUpdate,
)


class DetectionRunService:
    """Service for detection run management business logic."""

    def __init__(
        self,
        detection_run_repo: DetectionRunRepository,
        annotation_repo: AnnotationRepository | None = None,
    ) -> None:
        """Initialize service with repository.

        Args:
            detection_run_repo: DetectionRun repository instance
            annotation_repo: Optional Annotation repository instance (required for retry)
        """
        self.detection_run_repo = detection_run_repo
        self.annotation_repo = annotation_repo

    async def list_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 50,
        dataset_id: UUID | None = None,
    ) -> DetectionRunListResponse:
        """List detection runs for a project.

        Args:
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            dataset_id: Optional filter by dataset UUID

        Returns:
            Paginated detection run list response
        """
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 200:
            page_size = 50

        runs, total = await self.detection_run_repo.list_by_project(
            project_id=project_id,
            page=page,
            page_size=page_size,
            dataset_id=dataset_id,
        )

        pages = math.ceil(total / page_size) if total > 0 else 1

        return DetectionRunListResponse(
            items=[DetectionRunResponse.model_validate(r) for r in runs],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def get(self, run_id: UUID, project_id: UUID | None = None) -> DetectionRunResponse:
        """Get a detection run by ID.

        Args:
            run_id: DetectionRun's UUID
            project_id: Optional project UUID for ownership verification

        Returns:
            Detection run response

        Raises:
            HTTPException: If run not found or project_id mismatch
        """
        run = await self.detection_run_repo.get_by_id(run_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )
        if project_id is not None and run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )
        return DetectionRunResponse.model_validate(run)

    async def create(
        self,
        project_id: UUID,
        request: DetectionRunCreate,
    ) -> DetectionRunResponse:
        """Create a new detection run and queue the Celery detection task.

        Args:
            project_id: Project's UUID
            request: Detection run creation data

        Returns:
            Created detection run response
        """
        import logging

        from echoroo.workers.ml_tasks import run_birdnet_detection

        logger = logging.getLogger(__name__)

        run = DetectionRun(
            project_id=project_id,
            dataset_id=request.dataset_id,
            model_name=request.model_name,
            model_version=request.model_version,
            parameters=request.parameters,
            status=DetectionRunStatus.PENDING,
        )

        created = await self.detection_run_repo.create(run)
        response = DetectionRunResponse.model_validate(created)

        # Queue the Celery task after the record is created.
        # Use try/except so DB record creation succeeds even if Celery is unavailable.
        try:
            run_birdnet_detection.delay(
                str(created.dataset_id),
                str(project_id),
                str(created.id),
            )
            logger.info(
                "Queued BirdNET detection task for detection run %s (dataset %s)",
                created.id,
                created.dataset_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed to queue BirdNET detection task for detection run %s; "
                "record created but worker will not start automatically",
                created.id,
            )

        return response

    async def update(
        self,
        run_id: UUID,
        request: DetectionRunUpdate,
        project_id: UUID | None = None,
    ) -> DetectionRunResponse:
        """Update a detection run's status and metadata.

        Args:
            run_id: DetectionRun's UUID
            request: Update data
            project_id: Optional project UUID for ownership verification

        Returns:
            Updated detection run response

        Raises:
            HTTPException: If run not found or project_id mismatch
        """
        run = await self.detection_run_repo.get_by_id(run_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )
        if project_id is not None and run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )

        if request.status is not None:
            run.status = request.status
            # Auto-set timestamps based on status transitions
            if request.status == DetectionRunStatus.RUNNING and run.started_at is None:
                run.started_at = datetime.now(UTC)
            elif request.status in (DetectionRunStatus.COMPLETED, DetectionRunStatus.FAILED):
                run.completed_at = datetime.now(UTC)

        if request.annotation_count is not None:
            run.annotation_count = request.annotation_count

        if request.error_message is not None:
            run.error_message = request.error_message

        updated = await self.detection_run_repo.update(run)
        return DetectionRunResponse.model_validate(updated)

    async def retry(self, project_id: UUID, run_id: UUID) -> DetectionRunResponse:
        """Retry a completed or failed detection run.

        Deletes all existing annotations for the run, resets the run to PENDING,
        and re-queues the Celery detection task.

        Args:
            project_id: Project's UUID (used to validate ownership and queue task)
            run_id: DetectionRun's UUID

        Returns:
            Updated detection run response

        Raises:
            HTTPException: If run not found or status does not allow retry
        """
        from echoroo.workers.ml_tasks import run_birdnet_detection

        run = await self.detection_run_repo.get_by_id(run_id)
        if not run or run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )

        if run.status not in (DetectionRunStatus.COMPLETED, DetectionRunStatus.FAILED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot retry a detection run with status '{run.status.value}'. "
                       "Only COMPLETED or FAILED runs can be retried.",
            )

        if self.annotation_repo is None:
            raise RuntimeError("AnnotationRepository is required for retry operation")

        # Delete all existing annotations for this run
        await self.annotation_repo.delete_by_detection_run(run_id)

        # Reset run fields
        run.status = DetectionRunStatus.PENDING
        run.annotation_count = 0
        run.error_message = None
        run.started_at = None
        run.completed_at = None

        updated = await self.detection_run_repo.update(run)

        # Queue Celery task with the existing run_id
        run_birdnet_detection.delay(
            str(run.dataset_id),
            str(project_id),
            str(run_id),
        )

        return DetectionRunResponse.model_validate(updated)

    async def cancel(self, project_id: UUID, run_id: UUID) -> DetectionRunResponse:
        """Cancel a pending or running detection run.

        Sets the run status to FAILED with a cancellation message. The Celery
        worker checks for FAILED status before each recording and will stop
        processing when it detects the cancellation.

        Args:
            project_id: Project's UUID for ownership verification
            run_id: DetectionRun's UUID

        Returns:
            Updated detection run response

        Raises:
            HTTPException: If run not found, project_id mismatch, or status does not allow cancellation
        """
        run = await self.detection_run_repo.get_by_id(run_id)
        if not run or run.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection run not found",
            )

        if run.status not in (DetectionRunStatus.PENDING, DetectionRunStatus.RUNNING):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot cancel a detection run with status '{run.status.value}'. "
                       "Only PENDING or RUNNING runs can be cancelled.",
            )

        run.status = DetectionRunStatus.FAILED
        run.error_message = "Cancelled by user"

        updated = await self.detection_run_repo.update(run)
        return DetectionRunResponse.model_validate(updated)
