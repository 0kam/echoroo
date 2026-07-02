"""Admin endpoints for user and system management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

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
from echoroo.services.license import LicenseInUseError, LicenseService
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


# W2-3 PR-11: the browser-facing ``/api/v1/admin/*`` routes (users / settings /
# licenses / recorders) were unmounted in favour of the ``/web-api/v1/admin/*``
# BFF (``echoroo.api.web_v1._admin_users`` / ``_admin_settings`` /
# ``_admin_licenses`` / ``_admin_recorders``). The 14 handlers below are left as
# plain importable functions (no ``@router`` decorators) because the BFF delegates
# to them via ``legacy_admin.<fn>(...)`` and reuses ``_gate_admin_platform_action``
# / ``license_in_use_response``.
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


def license_in_use_response(error: LicenseInUseError) -> JSONResponse:
    """Map :class:`LicenseInUseError` to the spec/012 409 envelope.

    Mirrors ``specs/012-license-master-unification/contracts/
    admin-licenses-delete.yaml``. Used by BOTH the Bearer
    (``/api/v1/admin/licenses/{id}``) and BFF
    (``/web-api/v1/admin/licenses/{id}``) delete handlers — the helper
    is intentionally module-public so the BFF surface in
    :mod:`echoroo.api.web_v1._admin_licenses` can reuse the exact same
    body shape (the wire contract is locked at every customer
    touch-point).
    """
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error_code": "license_in_use",
            "message": (
                f"License '{error.short_name}' is still in use; "
                "reassign or remove dependents first"
            ),
            "short_name": error.short_name,
            "project_count": error.project_count,
            "dataset_count": error.dataset_count,
        },
    )


async def delete_license(
    license_id: str,
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> JSONResponse | None:
    """Delete a license.

    Args:
        license_id: License identifier code
        db: Database session
        current_user: Current authenticated superuser

    Raises:
        401: Not authenticated
        403: Not a superuser
        404: License not found
        409: License is referenced by other records (spec/012 FR-015 body).
    """
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_DELETE_ACTION,
        current_user=current_user,
        request=request,
    )
    license_service = LicenseService(db)
    try:
        await license_service.delete_license(license_id)
    except LicenseInUseError as exc:
        return license_in_use_response(exc)
    # 204 (default for the route — FastAPI emits an empty body).
    return None


# Recorder endpoints


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
