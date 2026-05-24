"""System settings BFF adapters (spec/009 PR 5).

Spec/009 PR 5 migrates the four superuser-admin surfaces consumed by the
Web UI over to the cookie + CSRF ``/web-api/v1/admin/*`` mount. This
module covers the system-settings subset (get + update).

Endpoints (2):

* GET    ``/admin/settings``  → ``ADMIN_SETTINGS_GET_ACTION``
* PATCH  ``/admin/settings``  → ``ADMIN_SETTINGS_UPDATE_ACTION``

Both actions are ``is_superuser_only=True`` + ``is_platform_scope=True``.
See the matching :mod:`echoroo.api.web_v1._admin_recorders` docstring for
the broader rationale.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import admin as legacy_admin
from echoroo.api.web_v1._admin_recorders import _gate_admin_platform_action
from echoroo.core.actions import (
    ADMIN_SETTINGS_GET_ACTION,
    ADMIN_SETTINGS_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentSuperuser
from echoroo.schemas.admin import (
    SystemSettingResponse,
    SystemSettingsUpdateRequest,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/settings",
    response_model=dict[str, SystemSettingResponse],
    summary="Get system settings (admin)",
    description="BFF adapter for the legacy admin system settings get endpoint.",
)
async def get_system_settings(
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> dict[str, SystemSettingResponse]:
    """Delegate system-settings read to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_SETTINGS_GET_ACTION,
        current_user=current_user,
        request=request,
    )
    return await legacy_admin.get_system_settings(
        request=request,
        db=db,
        current_user=current_user,
    )


@router.patch(
    "/settings",
    status_code=status.HTTP_200_OK,
    summary="Update system settings (admin)",
    description="BFF adapter for the legacy admin system settings update endpoint.",
)
async def update_system_settings(
    request: SystemSettingsUpdateRequest,
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> dict[str, str]:
    """Delegate system-settings update to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_SETTINGS_UPDATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
    return await legacy_admin.update_system_settings(
        request=request,
        http_request=http_request,
        db=db,
        current_user=current_user,
    )


__all__ = ["router"]
