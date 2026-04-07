"""ConfirmedRegion service for business logic."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from echoroo.core.pagination import paginate
from echoroo.models.confirmed_region import ConfirmedRegion
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.schemas.confirmed_region import (
    ConfirmedRegionCreate,
    ConfirmedRegionListResponse,
    ConfirmedRegionResponse,
)


class ConfirmedRegionService:
    """Service for confirmed region management business logic."""

    def __init__(self, confirmed_region_repo: ConfirmedRegionRepository) -> None:
        """Initialize service with repository.

        Args:
            confirmed_region_repo: ConfirmedRegion repository instance
        """
        self.confirmed_region_repo = confirmed_region_repo

    async def list_by_recording(
        self,
        recording_id: UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> ConfirmedRegionListResponse:
        """List confirmed regions for a specific recording.

        Args:
            recording_id: Recording's UUID
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Paginated confirmed region list response
        """
        pagination = paginate(page, page_size)

        regions, total = await self.confirmed_region_repo.list_by_recording(
            recording_id=recording_id,
            page=pagination.page,
            page_size=pagination.page_size,
        )

        return ConfirmedRegionListResponse(
            items=[ConfirmedRegionResponse.model_validate(r) for r in regions],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pagination.total_pages(total),
        )

    async def create(
        self,
        request: ConfirmedRegionCreate,
        user_id: UUID,
    ) -> ConfirmedRegionResponse:
        """Create a new confirmed region.

        Args:
            request: Confirmed region creation data
            user_id: ID of the user creating the region

        Returns:
            Created confirmed region response
        """
        region = ConfirmedRegion(
            recording_id=request.recording_id,
            start_time=request.start_time,
            end_time=request.end_time,
            reviewed_by_id=user_id,
        )

        created = await self.confirmed_region_repo.create(region)
        return ConfirmedRegionResponse.model_validate(created)

    async def delete(self, region_id: UUID) -> None:
        """Delete a confirmed region.

        Args:
            region_id: ConfirmedRegion's UUID

        Raises:
            HTTPException: If region not found
        """
        region = await self.confirmed_region_repo.get_by_id(region_id)
        if not region:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Confirmed region not found",
            )

        await self.confirmed_region_repo.delete(region_id)
