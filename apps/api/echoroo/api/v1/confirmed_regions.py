"""Confirmed region management API endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.confirmed_region import ConfirmedRegionRepository
from echoroo.schemas.confirmed_region import (
    ConfirmedRegionCreate,
    ConfirmedRegionListResponse,
    ConfirmedRegionResponse,
)
from echoroo.services.confirmed_region import ConfirmedRegionService

router = APIRouter(prefix="/projects/{project_id}/confirmed-regions", tags=["confirmed-regions"])


def get_confirmed_region_service(db: DbSession) -> ConfirmedRegionService:
    """Get ConfirmedRegionService instance.

    Args:
        db: Database session

    Returns:
        ConfirmedRegionService instance
    """
    return ConfirmedRegionService(confirmed_region_repo=ConfirmedRegionRepository(db))


ConfirmedRegionServiceDep = Annotated[ConfirmedRegionService, Depends(get_confirmed_region_service)]


@router.get(
    "",
    response_model=ConfirmedRegionListResponse,
    summary="List confirmed regions",
    description="List confirmed regions for a specific recording",
)
async def list_confirmed_regions(
    project_id: UUID,
    current_user: CurrentUser,
    service: ConfirmedRegionServiceDep,
    recording_id: UUID | None = None,
    page: int = 1,
    page_size: int = 50,
) -> ConfirmedRegionListResponse:
    """List confirmed regions for a recording.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Confirmed region service instance
        recording_id: Optional recording ID filter (required for useful results)
        page: Page number (default: 1)
        page_size: Items per page (default: 50)

    Returns:
        Paginated list of confirmed regions

    Raises:
        401: Not authenticated
    """
    if recording_id is None:
        # Return empty response if no recording_id provided
        return ConfirmedRegionListResponse(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            pages=1,
        )

    return await service.list_by_recording(
        recording_id=recording_id,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=ConfirmedRegionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create confirmed region",
    description="Create a new confirmed region for a recording",
)
async def create_confirmed_region(
    project_id: UUID,
    request: ConfirmedRegionCreate,
    current_user: CurrentUser,
    service: ConfirmedRegionServiceDep,
    db: DbSession,
) -> ConfirmedRegionResponse:
    """Create a new confirmed region.

    Args:
        project_id: Project's UUID
        request: Confirmed region creation data
        current_user: Current authenticated user
        service: Confirmed region service instance
        db: Database session

    Returns:
        Created confirmed region

    Raises:
        401: Not authenticated
        422: Validation error
    """
    region = await service.create(request=request, user_id=current_user.id)
    await db.commit()
    return region


@router.delete(
    "/{region_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete confirmed region",
    description="Delete a confirmed region by ID",
)
async def delete_confirmed_region(
    project_id: UUID,
    region_id: UUID,
    current_user: CurrentUser,
    service: ConfirmedRegionServiceDep,
    db: DbSession,
) -> None:
    """Delete confirmed region.

    Args:
        project_id: Project's UUID
        region_id: ConfirmedRegion's UUID
        current_user: Current authenticated user
        service: Confirmed region service instance
        db: Database session

    Raises:
        401: Not authenticated
        404: Confirmed region not found
    """
    await service.delete(region_id=region_id)
    await db.commit()
