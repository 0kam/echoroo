"""Setup API endpoints for initial system configuration."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import get_db
from echoroo.schemas.setup import (
    SetupCompleteResponse,
    SetupInitializeRequest,
    SetupStatusResponse,
)
from echoroo.services.setup import SetupService

router = APIRouter(prefix="/setup", tags=["setup"])
_SETUP_NOT_AVAILABLE_DETAIL = "Setup not available"


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or ""


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent") or ""


# W2-3 PR-2: the public ``GET /api/v1/setup/status`` route registration was
# unmounted in favour of the ``/web-api/v1/setup/status`` BFF surface
# (``echoroo.api.web_v1.setup``). The handler below is intentionally left as a
# plain importable function (no ``@router`` decorator) because the BFF mirror
# delegates to it via ``legacy_setup.get_setup_status(...)``.
async def get_setup_status(
    db: AsyncSession = Depends(get_db),
) -> SetupStatusResponse:
    """Get current setup status.

    Returns information about whether initial setup is required or completed.

    Returns:
        SetupStatusResponse: Current setup status
    """
    service = SetupService(db)
    return await service.get_setup_status()


# W2-3 PR-2: the public ``POST /api/v1/setup/initialize`` route registration was
# unmounted in favour of the ``/web-api/v1/setup/initialize`` BFF surface. The
# handler below stays importable (no ``@router`` decorator); the BFF mirror
# delegates to it via ``legacy_setup.initialize_setup(...)``.
async def initialize_setup(
    request: Request,
    response: Response,
    payload: SetupInitializeRequest,
    db: AsyncSession = Depends(get_db),
) -> SetupCompleteResponse:
    """Initialize system setup by creating the first admin user.

    Creates a superuser account with full system access and marks
    the initial setup as completed. Can only be performed once.

    Args:
        payload: Setup initialization request
        db: Database session

    Returns:
        SetupCompleteResponse: Created admin user plus one-time bootstrap secrets

    Raises:
        HTTPException: 403 if setup already completed
    """
    service = SetupService(db)
    response.headers["Cache-Control"] = "no-store, no-cache, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    try:
        return await service.initialize_setup(
            payload,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_403_FORBIDDEN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=_SETUP_NOT_AVAILABLE_DETAIL,
                headers=dict(exc.headers) if exc.headers is not None else None,
            ) from exc
        raise
