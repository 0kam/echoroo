"""Setup API endpoints for initial system configuration."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.database import get_db
from echoroo.schemas.setup import (
    SetupInitializeRequest,
    SetupStatusResponse,
    UserResponse,
)
from echoroo.services.setup import SetupService

router = APIRouter(prefix="/setup", tags=["setup"])


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
    response_model=UserResponse,
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
    request: SetupInitializeRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Initialize system setup by creating the first admin user.

    Creates a superuser account with full system access and marks
    the initial setup as completed. Can only be performed once.

    Args:
        request: Setup initialization request
        db: Database session

    Returns:
        UserResponse: Created admin user

    Raises:
        HTTPException: 403 if setup already completed
    """
    service = SetupService(db)
    user = await service.initialize_setup(request)
    return UserResponse.model_validate(user)
