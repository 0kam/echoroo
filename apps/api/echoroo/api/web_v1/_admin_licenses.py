"""License catalog BFF adapters (spec/009 PR 5).

Spec/009 PR 5 migrates the four superuser-admin surfaces consumed by the
Web UI over to the cookie + CSRF ``/web-api/v1/admin/*`` mount. This
module covers the license catalog CRUD (5 endpoints).

Endpoints (5):

* GET    ``/admin/licenses``              → ``ADMIN_LICENSE_LIST_ACTION``
* POST   ``/admin/licenses``              → ``ADMIN_LICENSE_CREATE_ACTION``
* GET    ``/admin/licenses/{license_id}`` → ``ADMIN_LICENSE_GET_ACTION``
* PATCH  ``/admin/licenses/{license_id}`` → ``ADMIN_LICENSE_UPDATE_ACTION``
* DELETE ``/admin/licenses/{license_id}`` → ``ADMIN_LICENSE_DELETE_ACTION``

All 5 actions are ``is_superuser_only=True`` + ``is_platform_scope=True``.
See the matching :mod:`echoroo.api.web_v1._admin_recorders` docstring for
the broader rationale.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import admin as legacy_admin
from echoroo.api.web_v1._admin_recorders import _gate_admin_platform_action
from echoroo.core.actions import (
    ADMIN_LICENSE_CREATE_ACTION,
    ADMIN_LICENSE_DELETE_ACTION,
    ADMIN_LICENSE_GET_ACTION,
    ADMIN_LICENSE_LIST_ACTION,
    ADMIN_LICENSE_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentSuperuser
from echoroo.schemas.license import (
    LicenseCreate,
    LicenseListResponse,
    LicenseResponse,
    LicenseUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/licenses",
    response_model=LicenseListResponse,
    summary="List licenses (admin)",
    description="BFF adapter for the legacy admin license list endpoint.",
)
async def list_licenses(
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> LicenseListResponse:
    """Delegate admin license list to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_LIST_ACTION,
        current_user=current_user,
        request=request,
    )
    return await legacy_admin.list_licenses(
        request=request,
        db=db,
        current_user=current_user,
    )


@router.post(
    "/licenses",
    response_model=LicenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create license (admin)",
    description="BFF adapter for the legacy admin license create endpoint.",
)
async def create_license(
    request: LicenseCreate,
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> LicenseResponse:
    """Delegate admin license create to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_CREATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
    return await legacy_admin.create_license(
        request=request,
        http_request=http_request,
        db=db,
        current_user=current_user,
    )


@router.get(
    "/licenses/{license_id}",
    response_model=LicenseResponse,
    summary="Get license (admin)",
    description="BFF adapter for the legacy admin license detail endpoint.",
)
async def get_license(
    license_id: str,
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> LicenseResponse:
    """Delegate admin license detail to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_GET_ACTION,
        current_user=current_user,
        request=request,
    )
    return await legacy_admin.get_license(
        license_id=license_id,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.patch(
    "/licenses/{license_id}",
    response_model=LicenseResponse,
    summary="Update license (admin)",
    description="BFF adapter for the legacy admin license update endpoint.",
)
async def update_license(
    license_id: str,
    request: LicenseUpdate,
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> LicenseResponse:
    """Delegate admin license update to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_UPDATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
    return await legacy_admin.update_license(
        license_id=license_id,
        request=request,
        http_request=http_request,
        db=db,
        current_user=current_user,
    )


@router.delete(
    "/licenses/{license_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete license (admin)",
    description="BFF adapter for the legacy admin license delete endpoint.",
)
async def delete_license(
    license_id: str,
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> None:
    """Delegate admin license delete to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_DELETE_ACTION,
        current_user=current_user,
        request=request,
    )
    await legacy_admin.delete_license(
        license_id=license_id,
        request=request,
        db=db,
        current_user=current_user,
    )


__all__ = ["router"]
