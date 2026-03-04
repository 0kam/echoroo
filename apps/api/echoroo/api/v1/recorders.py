"""Public recorder API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.recorder import RecorderListResponse
from echoroo.services.recorder import RecorderService

router = APIRouter(prefix="/recorders", tags=["recorders"])


def get_recorder_service(db: DbSession) -> RecorderService:
    """Get RecorderService instance.

    Args:
        db: Database session

    Returns:
        RecorderService instance
    """
    return RecorderService(db)


RecorderServiceDep = Annotated[RecorderService, Depends(get_recorder_service)]


@router.get(
    "",
    response_model=RecorderListResponse,
    summary="List all recorders",
    description="Get a paginated list of all audio recording devices. Requires authentication.",
)
async def list_recorders(
    current_user: CurrentUser,  # noqa: ARG001 - used for auth dependency
    service: RecorderServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> RecorderListResponse:
    """List all recorders with pagination.

    Args:
        current_user: Current authenticated user
        service: Recorder service instance
        page: Page number (default: 1)
        limit: Number of items per page (default: 100, max: 100)

    Returns:
        Paginated list of recorders

    Raises:
        401: Not authenticated
    """
    return await service.list_recorders(page=page, limit=limit)
