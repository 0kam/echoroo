"""Admin user management BFF adapters (spec/009 PR 5).

Spec/009 PR 5 migrates the four superuser-admin surfaces consumed by the
Web UI over to the cookie + CSRF ``/web-api/v1/admin/*`` mount. This
module covers the user-management subset (list + update).

Endpoints (2):

* GET    ``/admin/users``            → ``ADMIN_USERS_LIST_ACTION``
* PATCH  ``/admin/users/{user_id}``  → ``ADMIN_USERS_UPDATE_ACTION``

Both actions are ``is_superuser_only=True`` + ``is_platform_scope=True``.
See the matching :mod:`echoroo.api.web_v1._admin_recorders` docstring for
the broader rationale (no ``gate_action``, ``is_allowed`` direct call,
canonical guard helper lint contract).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from echoroo.api.v1 import admin as legacy_admin
from echoroo.api.web_v1._admin_recorders import _gate_admin_platform_action
from echoroo.core.actions import (
    ADMIN_USERS_LIST_ACTION,
    ADMIN_USERS_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentSuperuser
from echoroo.schemas.admin import (
    AdminUserListResponse,
    AdminUserUpdateRequest,
)
from echoroo.schemas.auth import UserResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="List users (admin)",
    description="BFF adapter for the legacy admin user list endpoint.",
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
    """Delegate admin user list to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_USERS_LIST_ACTION,
        current_user=current_user,
        request=request,
    )
    return await legacy_admin.list_users(
        request=request,
        db=db,
        current_user=current_user,
        page=page,
        limit=limit,
        search=search,
        is_active=is_active,
    )


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Update user (admin)",
    description="BFF adapter for the legacy admin user update endpoint.",
)
async def update_user(
    user_id: UUID,
    request: AdminUserUpdateRequest,
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> UserResponse:
    """Delegate admin user update to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_USERS_UPDATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
    return await legacy_admin.update_user(
        user_id=user_id,
        request=request,
        http_request=http_request,
        db=db,
        current_user=current_user,
    )


__all__ = ["router"]
