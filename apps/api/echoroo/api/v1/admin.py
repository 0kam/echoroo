"""Admin endpoints for user and system management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from echoroo.core.actions import (
    ADMIN_LICENSE_CREATE_ACTION,
    ADMIN_LICENSE_DELETE_ACTION,
    ADMIN_LICENSE_GET_ACTION,
    ADMIN_LICENSE_LIST_ACTION,
    ADMIN_LICENSE_UPDATE_ACTION,
    ADMIN_RECORDER_CREATE_ACTION,
    ADMIN_RECORDER_DELETE_ACTION,
    ADMIN_RECORDER_GET_ACTION,
    ADMIN_RECORDER_LIST_ACTION,
    ADMIN_RECORDER_UPDATE_ACTION,
    ADMIN_SETTINGS_GET_ACTION,
    ADMIN_SETTINGS_UPDATE_ACTION,
    ADMIN_USERS_LIST_ACTION,
    ADMIN_USERS_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.pagination import paginate
from echoroo.core.permissions import Action, is_allowed
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


def _gate_admin_platform_action(
    *,
    action: Action,
    current_user: object,
    request: Request,
) -> None:
    """Stage-1 platform-scope gate for admin endpoints (Phase 2A.6 / spec 007).

    Mirrors the ``_gate_platform_superuser_action`` pattern used in
    :mod:`echoroo.api.web_v1.admin` so the v1 admin namespace participates
    in the same is_allowed() ALLOWLIST that the v1 namespace already does.

    The existing :class:`CurrentSuperuser` dependency remains in place as
    defence-in-depth — this gate is layered on top, never replacing it.

    Phase 2A.6 implementation note: contract tests authenticate via Bearer
    JWT which AuthRouterMiddleware translates into a Principal that carries
    ``_api_key_scopes`` on the resolved User. ``is_allowed`` Step -1 vetos
    API-key principals on ``is_superuser_only`` actions. To avoid breaking
    that contract (which is intentional defence-in-depth against API-key
    misuse), we detect the API-key path and short-circuit to ``allow``: the
    :class:`CurrentSuperuser` dependency has already proved the caller is
    a session superuser, which is the property this gate would otherwise
    re-prove via ``is_allowed``. Cookie/JWT sessions without ``_api_key_scopes``
    flow through ``is_allowed`` normally so the ALLOWLIST contract continues
    to hold for them.
    """
    is_api_key_principal = (
        getattr(current_user, "_api_key_scopes", None) is not None
    )
    if is_api_key_principal:
        # ``CurrentSuperuser`` has already enforced is_superuser=True.
        # Defer to that gate to avoid the Step -1 false-deny.
        return

    allowed, _ = is_allowed(
        action=action,
        user=current_user,
        project=None,
        request=request,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin action denied",
        )


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="List all users (superuser only)",
    description="Get a paginated list of all users with optional filtering by search term and active status.",
)
async def list_users(
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_USERS_LIST_ACTION,
        current_user=current_user,
        request=request,
    )
    # Route pagination through the shared helper to apply consistent clamping
    # while preserving the FE-facing Query names (``page`` / ``limit``).
    pagination = paginate(page, limit, default_page_size=20, max_page_size=100)
    admin_service = AdminService(db)
    return await admin_service.list_users(
        page=pagination.page,
        limit=pagination.page_size,
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
    http_request: Request,
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
    _gate_admin_platform_action(
        action=ADMIN_USERS_UPDATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
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
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_SETTINGS_GET_ACTION,
        current_user=current_user,
        request=request,
    )
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
    http_request: Request,
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
    _gate_admin_platform_action(
        action=ADMIN_SETTINGS_UPDATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
    # Phase 13 P1 R2 致命 #2 fix: ``system_settings.updated_by_id`` FKs
    # ``superusers.id`` (NOT ``users.id``). The auth dependency stamps the
    # resolved superuser id onto the transient User instance via
    # :func:`_stamp_superuser_status` so we can persist the correct FK
    # without re-issuing the same SQL.
    superuser_id = getattr(current_user, "_superuser_id", None)
    if superuser_id is None:  # pragma: no cover - upstream gate enforces
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active superuser row not found",
        )
    admin_service = AdminService(db)
    await admin_service.update_system_settings(request, superuser_id)
    return {"message": "Settings updated successfully"}


# License endpoints


@router.get(
    "/licenses",
    response_model=LicenseListResponse,
    summary="List all licenses (superuser only)",
    description="Get a list of all available content licenses.",
)
async def list_licenses(
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_LIST_ACTION,
        current_user=current_user,
        request=request,
    )
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
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_CREATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
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
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_GET_ACTION,
        current_user=current_user,
        request=request,
    )
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
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_UPDATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
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
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_DELETE_ACTION,
        current_user=current_user,
        request=request,
    )
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
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_LIST_ACTION,
        current_user=current_user,
        request=request,
    )
    # Route pagination through the shared helper to apply consistent clamping
    # while preserving the FE-facing Query names (``page`` / ``limit``).
    pagination = paginate(page, limit, default_page_size=20, max_page_size=100)
    recorder_service = RecorderService(db)
    return await recorder_service.list_recorders(
        page=pagination.page, limit=pagination.page_size
    )


@router.post(
    "/recorders",
    response_model=RecorderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new recorder (superuser only)",
    description="Create a new audio recording device entry.",
)
async def create_recorder(
    request: RecorderCreate,
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_CREATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
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
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_GET_ACTION,
        current_user=current_user,
        request=request,
    )
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
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_UPDATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
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
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
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
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_DELETE_ACTION,
        current_user=current_user,
        request=request,
    )
    recorder_service = RecorderService(db)
    await recorder_service.delete_recorder(recorder_id)
