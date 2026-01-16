"""Admin endpoints for user and system management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentSuperuser
from echoroo.schemas.admin import (
    AdminUserListResponse,
    AdminUserUpdateRequest,
    SystemSettingResponse,
    SystemSettingsUpdateRequest,
)
from echoroo.schemas.auth import UserResponse
from echoroo.schemas.license import (
    LicenseCreate,
    LicenseListResponse,
    LicenseResponse,
    LicenseUpdate,
)
from echoroo.schemas.recorder import (
    RecorderCreate,
    RecorderListResponse,
    RecorderResponse,
    RecorderUpdate,
)
from echoroo.services.admin import AdminService
from echoroo.services.license import LicenseService
from echoroo.services.recorder import RecorderService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="List all users (superuser only)",
    description="Get a paginated list of all users with optional filtering by search term and active status.",
)
async def list_users(
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    is_active: bool | None = None,
) -> AdminUserListResponse:
    """List all users with pagination and filtering.

    Args:
        db: Database session
        current_user: Current authenticated superuser
        page: Page number (default: 1)
        limit: Number of items per page (default: 20, max: 100)
        search: Search term for email or display name
        is_active: Filter by active status

    Returns:
        Paginated list of users

    Raises:
        401: Not authenticated
        403: Not a superuser
    """
    admin_service = AdminService(db)
    return await admin_service.list_users(
        page=page,
        limit=limit,
        search=search,
        is_active=is_active,
    )


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Update user status (superuser only)",
    description="Update user's active status, superuser status, or email verification status.",
)
async def update_user(
    user_id: UUID,
    request: AdminUserUpdateRequest,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> UserResponse:
    """Update user status and permissions.

    Args:
        user_id: UUID of user to update
        request: Update request with fields to change
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        Updated user

    Raises:
        400: Cannot disable or demote last superuser
        401: Not authenticated
        403: Not a superuser
        404: User not found
    """
    admin_service = AdminService(db)
    user = await admin_service.update_user(user_id, request, current_user.id)
    return UserResponse.model_validate(user)


@router.get(
    "/settings",
    response_model=dict[str, SystemSettingResponse],
    summary="Get system settings (superuser only)",
    description="Get all system configuration settings.",
)
async def get_system_settings(
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> dict[str, SystemSettingResponse]:
    """Get all system settings.

    Args:
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        Dictionary of all system settings

    Raises:
        401: Not authenticated
        403: Not a superuser
    """
    admin_service = AdminService(db)
    return await admin_service.get_system_settings()


@router.patch(
    "/settings",
    status_code=status.HTTP_200_OK,
    summary="Update system settings (superuser only)",
    description="Update system configuration settings.",
)
async def update_system_settings(
    request: SystemSettingsUpdateRequest,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> dict[str, str]:
    """Update system settings.

    Args:
        request: Settings update request
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        Success message

    Raises:
        401: Not authenticated
        403: Not a superuser
        422: Validation error
    """
    admin_service = AdminService(db)
    await admin_service.update_system_settings(request, current_user.id)
    return {"message": "Settings updated successfully"}


# License endpoints


@router.get(
    "/licenses",
    response_model=LicenseListResponse,
    summary="List all licenses (superuser only)",
    description="Get a list of all available content licenses.",
)
async def list_licenses(
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> LicenseListResponse:
    """List all licenses.

    Args:
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        List of all licenses

    Raises:
        401: Not authenticated
        403: Not a superuser
    """
    license_service = LicenseService(db)
    return await license_service.list_licenses()


@router.post(
    "/licenses",
    response_model=LicenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new license (superuser only)",
    description="Create a new content license type.",
)
async def create_license(
    request: LicenseCreate,
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> LicenseResponse:
    """Create a new license.

    Args:
        request: License creation data
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        Created license

    Raises:
        401: Not authenticated
        403: Not a superuser
        409: License with same ID already exists
        422: Validation error
    """
    license_service = LicenseService(db)
    return await license_service.create_license(request)


@router.get(
    "/licenses/{license_id}",
    response_model=LicenseResponse,
    summary="Get license by ID (superuser only)",
    description="Get detailed information about a specific license.",
)
async def get_license(
    license_id: str,
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> LicenseResponse:
    """Get license by ID.

    Args:
        license_id: License identifier code
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        License details

    Raises:
        401: Not authenticated
        403: Not a superuser
        404: License not found
    """
    license_service = LicenseService(db)
    return await license_service.get_license(license_id)


@router.patch(
    "/licenses/{license_id}",
    response_model=LicenseResponse,
    summary="Update license (superuser only)",
    description="Update an existing content license.",
)
async def update_license(
    license_id: str,
    request: LicenseUpdate,
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> LicenseResponse:
    """Update an existing license.

    Args:
        license_id: License identifier code
        request: License update data
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        Updated license

    Raises:
        401: Not authenticated
        403: Not a superuser
        404: License not found
        422: Validation error
    """
    license_service = LicenseService(db)
    return await license_service.update_license(license_id, request)


@router.delete(
    "/licenses/{license_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete license (superuser only)",
    description="Delete a content license type.",
)
async def delete_license(
    license_id: str,
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> None:
    """Delete a license.

    Args:
        license_id: License identifier code
        db: Database session
        current_user: Current authenticated superuser

    Raises:
        401: Not authenticated
        403: Not a superuser
        404: License not found
        409: License is referenced by other records
    """
    license_service = LicenseService(db)
    await license_service.delete_license(license_id)


# Recorder endpoints


@router.get(
    "/recorders",
    response_model=RecorderListResponse,
    summary="List all recorders (superuser only)",
    description="Get a paginated list of all audio recording devices.",
)
async def list_recorders(
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecorderListResponse:
    """List all recorders with pagination.

    Args:
        db: Database session
        current_user: Current authenticated superuser
        page: Page number (default: 1)
        limit: Number of items per page (default: 20, max: 100)

    Returns:
        Paginated list of recorders

    Raises:
        401: Not authenticated
        403: Not a superuser
    """
    recorder_service = RecorderService(db)
    return await recorder_service.list_recorders(page=page, limit=limit)


@router.post(
    "/recorders",
    response_model=RecorderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new recorder (superuser only)",
    description="Create a new audio recording device entry.",
)
async def create_recorder(
    request: RecorderCreate,
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> RecorderResponse:
    """Create a new recorder.

    Args:
        request: Recorder creation data
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        Created recorder

    Raises:
        401: Not authenticated
        403: Not a superuser
        409: Recorder with same ID already exists
        422: Validation error
    """
    recorder_service = RecorderService(db)
    return await recorder_service.create_recorder(request)


@router.get(
    "/recorders/{recorder_id}",
    response_model=RecorderResponse,
    summary="Get recorder by ID (superuser only)",
    description="Get detailed information about a specific recorder.",
)
async def get_recorder(
    recorder_id: str,
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> RecorderResponse:
    """Get recorder by ID.

    Args:
        recorder_id: Recorder unique identifier
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        Recorder details

    Raises:
        401: Not authenticated
        403: Not a superuser
        404: Recorder not found
    """
    recorder_service = RecorderService(db)
    return await recorder_service.get_recorder(recorder_id)


@router.patch(
    "/recorders/{recorder_id}",
    response_model=RecorderResponse,
    summary="Update recorder (superuser only)",
    description="Update an existing audio recording device.",
)
async def update_recorder(
    recorder_id: str,
    request: RecorderUpdate,
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> RecorderResponse:
    """Update an existing recorder.

    Args:
        recorder_id: Recorder unique identifier
        request: Recorder update data
        db: Database session
        current_user: Current authenticated superuser

    Returns:
        Updated recorder

    Raises:
        401: Not authenticated
        403: Not a superuser
        404: Recorder not found
        422: Validation error
    """
    recorder_service = RecorderService(db)
    return await recorder_service.update_recorder(recorder_id, request)


@router.delete(
    "/recorders/{recorder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete recorder (superuser only)",
    description="Delete an audio recording device.",
)
async def delete_recorder(
    recorder_id: str,
    db: DbSession,
    current_user: CurrentSuperuser,  # noqa: ARG001 - used for auth dependency
) -> None:
    """Delete a recorder.

    Args:
        recorder_id: Recorder unique identifier
        db: Database session
        current_user: Current authenticated superuser

    Raises:
        401: Not authenticated
        403: Not a superuser
        404: Recorder not found
    """
    recorder_service = RecorderService(db)
    await recorder_service.delete_recorder(recorder_id)
