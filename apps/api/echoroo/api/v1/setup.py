"""Setup API endpoints for initial system configuration."""

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import get_db
from echoroo.schemas.setup import (
    SetupCompleteResponse,
    SetupInitializeRequest,
    SetupStatusResponse,
)
from echoroo.services.setup import SetupService

router = APIRouter(prefix="/setup", tags=["setup"])


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or ""


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent") or ""


@router.get(
    "/status",
    response_model=SetupStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get setup status",
    description="Check if initial setup is required or has been completed",
)
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


@router.post(
    "/initialize",
    response_model=SetupCompleteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize system setup",
    description="Create the first admin user and complete initial setup",
    responses={
        201: {
            "description": "Setup completed successfully, admin user created",
        },
        403: {
            "description": "Setup already completed or users already exist",
        },
        422: {
            "description": "Validation error (invalid email or short password)",
        },
    },
)
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
    return await service.initialize_setup(
        payload,
        request_id=_request_id(request),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
