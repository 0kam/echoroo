"""Detection annotation service for detection review business logic."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.annotation import Annotation
from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.models.enums import DetectionStatus
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.schemas.detection import (
    ChangeSpeciesRequest,
    ConfirmRequest,
    DetectionCreate,
    DetectionListResponse,
    DetectionResponse,
    SpeciesSummaryItem,
    SpeciesSummaryResponse,
)
from echoroo.schemas.tag import TagResponse


class DetectionService:
    """Service for detection annotation management business logic."""

    def __init__(
        self,
        annotation_repo: AnnotationRepository,
        confirmed_region_repo: ConfirmedRegionRepository,
    ) -> None:
        """Initialize service with repositories.

        Args:
            annotation_repo: Annotation repository instance
            confirmed_region_repo: ConfirmedRegion repository instance
        """
        self.annotation_repo = annotation_repo
        self.confirmed_region_repo = confirmed_region_repo

    async def list_detections(
        self,
        project_id: UUID,
        tag_id: UUID | None = None,
        status: DetectionStatus | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        dataset_id: UUID | None = None,
        recording_id: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> DetectionListResponse:
        """List detections for a project with optional filtering and pagination.

        Args:
            project_id: Project's UUID
            tag_id: Optional tag filter
            status: Optional review status filter
            confidence_min: Optional minimum confidence filter
            confidence_max: Optional maximum confidence filter
            dataset_id: Optional dataset filter
            recording_id: Optional recording filter
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Paginated detection list response
        """
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 200:
            page_size = 50

        annotations, total = await self.annotation_repo.list(
            project_id=project_id,
            tag_id=tag_id,
            status=status,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            dataset_id=dataset_id,
            recording_id=recording_id,
            page=page,
            page_size=page_size,
        )

        pages = math.ceil(total / page_size) if total > 0 else 1

        items = [self._to_response(a) for a in annotations]

        return DetectionListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def get_species_summary(
        self,
        project_id: UUID,
        dataset_id: UUID | None = None,
    ) -> SpeciesSummaryResponse:
        """Get species detection summary grouped by tag.

        Args:
            project_id: Project's UUID
            dataset_id: Optional dataset filter

        Returns:
            Species summary response with per-species statistics
        """
        rows = await self.annotation_repo.species_summary(
            project_id=project_id,
            dataset_id=dataset_id,
        )

        items = [
            SpeciesSummaryItem(
                tag_id=row["tag_id"],
                tag_name=row["tag_name"],
                scientific_name=row["scientific_name"],
                common_name=row["common_name"],
                total_count=row["total_count"],
                unreviewed_count=row["unreviewed_count"],
                confirmed_count=row["confirmed_count"],
                rejected_count=row["rejected_count"],
                avg_confidence=row["avg_confidence"],
            )
            for row in rows
        ]

        return SpeciesSummaryResponse(
            items=items,
            total_species=len(items),
        )

    async def get(self, detection_id: UUID) -> DetectionResponse:
        """Get a detection annotation by ID.

        Args:
            detection_id: Annotation's UUID

        Returns:
            Detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )
        return self._to_response(annotation)

    async def create(
        self,
        project_id: UUID,  # noqa: ARG002 - used for future authorization
        request: DetectionCreate,
    ) -> DetectionResponse:
        """Create a new detection annotation.

        Args:
            project_id: Project's UUID (for authorization context)
            request: Detection creation data

        Returns:
            Created detection response
        """
        annotation = Annotation(
            recording_id=request.recording_id,
            tag_id=request.tag_id,
            detection_run_id=request.detection_run_id,
            source=request.source,
            confidence=request.confidence,
            start_time=request.start_time,
            end_time=request.end_time,
            freq_low=request.freq_low,
            freq_high=request.freq_high,
        )

        created = await self.annotation_repo.create(annotation)
        return self._to_response(created)

    async def confirm(
        self,
        detection_id: UUID,
        request: ConfirmRequest,
        user_id: UUID,
    ) -> DetectionResponse:
        """Confirm a detection annotation and create a confirmed region.

        Sets status to confirmed, records the reviewer, and creates a
        ConfirmedRegion for the confirmed time range.

        Args:
            detection_id: Annotation's UUID
            request: Confirm request with time range
            user_id: ID of the user confirming the detection

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        annotation.status = DetectionStatus.CONFIRMED
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)
        annotation.start_time = request.start_time
        annotation.end_time = request.end_time

        updated = await self.annotation_repo.update(annotation)

        # Create a confirmed region for the confirmed time range
        confirmed_region = ConfirmedRegion(
            recording_id=annotation.recording_id,
            start_time=request.start_time,
            end_time=request.end_time,
            reviewed_by_id=user_id,
        )
        await self.confirmed_region_repo.create(confirmed_region)

        return self._to_response(updated)

    async def reject(
        self,
        detection_id: UUID,
        user_id: UUID,
    ) -> DetectionResponse:
        """Reject a detection annotation.

        Args:
            detection_id: Annotation's UUID
            user_id: ID of the user rejecting the detection

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        annotation.status = DetectionStatus.REJECTED
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)

        updated = await self.annotation_repo.update(annotation)
        return self._to_response(updated)

    async def change_species(
        self,
        detection_id: UUID,
        request: ChangeSpeciesRequest,
        user_id: UUID,
    ) -> DetectionResponse:
        """Change the species tag of a detection annotation.

        Also updates time range if provided, and records the reviewer.

        Args:
            detection_id: Annotation's UUID
            request: Change species request with new tag and optional time range
            user_id: ID of the user making the change

        Returns:
            Updated detection response

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        annotation.tag_id = request.new_tag_id
        annotation.reviewed_by_id = user_id
        annotation.reviewed_at = datetime.now(UTC)

        if request.start_time is not None:
            annotation.start_time = request.start_time
        if request.end_time is not None:
            annotation.end_time = request.end_time

        updated = await self.annotation_repo.update(annotation)
        return self._to_response(updated)

    async def delete(self, detection_id: UUID) -> None:
        """Delete a detection annotation.

        Args:
            detection_id: Annotation's UUID

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(detection_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        await self.annotation_repo.delete(detection_id)

    @staticmethod
    def _to_response(annotation: Annotation) -> DetectionResponse:
        """Convert an Annotation model to a DetectionResponse schema.

        Args:
            annotation: Annotation model instance

        Returns:
            DetectionResponse instance
        """
        tag_response = None
        if annotation.tag is not None:
            tag_response = TagResponse.model_validate(annotation.tag)

        return DetectionResponse(
            id=annotation.id,
            recording_id=annotation.recording_id,
            tag_id=annotation.tag_id,
            detection_run_id=annotation.detection_run_id,
            source=annotation.source,
            status=annotation.status,
            confidence=annotation.confidence,
            start_time=annotation.start_time,
            end_time=annotation.end_time,
            freq_low=annotation.freq_low,
            freq_high=annotation.freq_high,
            reviewed_by_id=annotation.reviewed_by_id,
            reviewed_at=annotation.reviewed_at,
            created_at=annotation.created_at,
            updated_at=annotation.updated_at,
            tag=tag_response,
        )
