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
from fastapi.responses import JSONResponse

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
    response_model=None,
    summary="Delete license (admin)",
    description=(
        "BFF adapter for the admin license delete endpoint. spec/012 "
        "FR-006 / FR-012 / FR-015: refused with 409 + dependency-count "
        "envelope when at least one project or dataset still references "
        "the license. The response shape is identical to "
        "``DELETE /api/v1/admin/licenses/{id}``."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {
            "description": "License id does not exist.",
        },
        status.HTTP_409_CONFLICT: {
            "description": "License is still referenced by projects/datasets.",
            "content": {
                "application/json": {
                    "example": {
                        "error_code": "license_in_use",
                        "message": (
                            "License 'CC-BY' is still in use; reassign or "
                            "remove dependents first"
                        ),
                        "short_name": "CC-BY",
                        "project_count": 3,
                        "dataset_count": 7,
                    }
                }
            },
        }
    },
)
async def delete_license(
    license_id: str,
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> JSONResponse | None:
    """Delegate admin license delete to the legacy handler.

    spec/012: the legacy Bearer handler now returns either ``None`` (204
    path) OR a :class:`JSONResponse` carrying the 409 envelope when the
    license is still in use. We propagate that return value verbatim so
    the BFF and the Bearer surface share the same wire shape at every
    customer touch-point. Continuing to call ``legacy_admin.delete_license``
    (rather than re-implementing the service call here) preserves the
    spec/009 PR 5 delegation pattern so :mod:`tests.integration.api.web_v1
    .admin.test_admin_licenses_smoke` keeps working.
    """
    _gate_admin_platform_action(
        action=ADMIN_LICENSE_DELETE_ACTION,
        current_user=current_user,
        request=request,
    )
    return await legacy_admin.delete_license(
        license_id=license_id,
        request=request,
        db=db,
        current_user=current_user,
    )


__all__ = ["router"]
