"""Public recorder API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from echoroo.core.database import DbSession
from echoroo.core.pagination import paginate
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


# W2-3 PR-1: the public ``GET /api/v1/recorders`` route registration was
# unmounted in favour of the ``/web-api/v1/recorders`` BFF surface
# (``echoroo.api.web_v1._recorders``). The handler below is intentionally
# left as a plain importable function (no ``@router`` decorator) because the
# BFF adapter delegates to it via ``legacy_recorders.list_recorders(...)``.
# Keep ``get_recorder_service`` / ``RecorderServiceDep`` importable too.
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
    # Route pagination through the shared helper to apply consistent clamping
    # while preserving the FE-facing Query names (``page`` / ``limit``).
    pagination = paginate(page, limit, default_page_size=100, max_page_size=100)
    return await service.list_recorders(
        page=pagination.page, limit=pagination.page_size
    )
