"""DetectionRun service for business logic."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunStatus
from echoroo.repositories.detection_run import DetectionRunRepository
from echoroo.schemas.detection_run import (
    DetectionRunCreate,
    DetectionRunListResponse,
    DetectionRunResponse,
    DetectionRunUpdate,
)


class DetectionRunService:
    """Service for detection run management business logic."""

    def __init__(self, detection_run_repo: DetectionRunRepository) -> None:
        """Initialize service with repository.

        Args:
            detection_run_repo: DetectionRun repository instance
        """
        self.detection_run_repo = detection_run_repo

    async def list_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> DetectionRunListResponse:
        """List detection runs for a project.

        Args:
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page

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
        )

        pages = math.ceil(total / page_size) if total > 0 else 1

        return DetectionRunListResponse(
            items=[DetectionRunResponse.model_validate(r) for r in runs],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def get(self, run_id: UUID) -> DetectionRunResponse:
        """Get a detection run by ID.

        Args:
            run_id: DetectionRun's UUID

        Returns:
            Detection run response

        Raises:
            HTTPException: If run not found
        """
        run = await self.detection_run_repo.get_by_id(run_id)
        if not run:
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
        """Create a new detection run.

        Args:
            project_id: Project's UUID
            request: Detection run creation data

        Returns:
            Created detection run response
        """
        run = DetectionRun(
            project_id=project_id,
            dataset_id=request.dataset_id,
            model_name=request.model_name,
            model_version=request.model_version,
            parameters=request.parameters,
            status=DetectionRunStatus.PENDING,
        )

        created = await self.detection_run_repo.create(run)
        return DetectionRunResponse.model_validate(created)

    async def update(
        self,
        run_id: UUID,
        request: DetectionRunUpdate,
    ) -> DetectionRunResponse:
        """Update a detection run's status and metadata.

        Args:
            run_id: DetectionRun's UUID
            request: Update data

        Returns:
            Updated detection run response

        Raises:
            HTTPException: If run not found
        """
        run = await self.detection_run_repo.get_by_id(run_id)
        if not run:
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
