"""Admin recorder catalog BFF adapter (spec/009 PR 5).

Spec/009 PR 5 migrates the four superuser-admin surfaces consumed by the
Web UI (``/api/v1/admin/{recorders,users,settings,licenses}``) over to
the cookie + CSRF ``/web-api/v1/admin/*`` mount. The legacy ``/api/v1``
handlers stay live to keep the API-key catalog surface functional; each
BFF module here is a thin adapter that re-runs the platform-scope
``is_allowed`` gate before delegating to the legacy handler.

Endpoints (5):

* GET    ``/admin/recorders``               → ``ADMIN_RECORDER_LIST_ACTION``
* POST   ``/admin/recorders``               → ``ADMIN_RECORDER_CREATE_ACTION``
* GET    ``/admin/recorders/{recorder_id}`` → ``ADMIN_RECORDER_GET_ACTION``
* PATCH  ``/admin/recorders/{recorder_id}`` → ``ADMIN_RECORDER_UPDATE_ACTION``
* DELETE ``/admin/recorders/{recorder_id}`` → ``ADMIN_RECORDER_DELETE_ACTION``

The 5 admin recorder Actions are all ``is_superuser_only=True`` +
``is_platform_scope=True``. ``gate_action`` cannot be used (it requires
a ``project_id``); the BFF mirrors the legacy handler's
``_gate_admin_platform_action`` helper which runs ``is_allowed`` directly
with ``project=None``. The lint accepts ``is_allowed`` as a canonical
guard helper (:mod:`scripts.lint_permission_guard`).

The legacy admin module exists at :mod:`echoroo.api.v1.admin`; this
module deliberately does NOT collide with
:mod:`echoroo.api.web_v1._recorders` (PR 4 public recorder list BFF)
because that surface is the tenant-wide unprivileged catalog, while
these 5 admin endpoints are the superuser CRUD surface.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from echoroo.api.v1 import admin as legacy_admin
from echoroo.core.actions import (
    ADMIN_RECORDER_CREATE_ACTION,
    ADMIN_RECORDER_DELETE_ACTION,
    ADMIN_RECORDER_GET_ACTION,
    ADMIN_RECORDER_LIST_ACTION,
    ADMIN_RECORDER_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import Action, is_allowed
from echoroo.middleware.auth import CurrentSuperuser
from echoroo.schemas.recorder import (
    RecorderCreate,
    RecorderListResponse,
    RecorderResponse,
    RecorderUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _gate_admin_platform_action(
    *,
    action: Action,
    current_user: object,
    request: Request,
) -> None:
    """BFF-side mirror of :func:`legacy_admin._gate_admin_platform_action`.

    Run the Stage-1 platform-scope ``is_allowed`` gate. ``CurrentSuperuser``
    has already proved the caller is a session superuser (and rejected
    API-key principals via the BFF's surface-separation contract). This
    helper is the second line of defence and keeps the canonical
    ``is_superuser_only`` action allowlist authoritative.

    The legacy helper short-circuits API-key principals to avoid the
    Step -1 false-deny — that branch is intentionally omitted here
    because the BFF surface is API-key-rejected by AuthRouterMiddleware
    upstream, so any caller reaching this gate is a session principal.
    """
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
    "/recorders",
    response_model=RecorderListResponse,
    summary="List recorders (admin)",
    description="BFF adapter for the legacy admin recorder list endpoint.",
)
async def list_recorders(
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecorderListResponse:
    """Delegate admin recorder list to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_LIST_ACTION,
        current_user=current_user,
        request=request,
    )
    return await legacy_admin.list_recorders(
        request=request,
        db=db,
        current_user=current_user,
        page=page,
        limit=limit,
    )


@router.post(
    "/recorders",
    response_model=RecorderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create recorder (admin)",
    description="BFF adapter for the legacy admin recorder create endpoint.",
)
async def create_recorder(
    request: RecorderCreate,
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> RecorderResponse:
    """Delegate admin recorder create to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_CREATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
    return await legacy_admin.create_recorder(
        request=request,
        http_request=http_request,
        db=db,
        current_user=current_user,
    )


@router.get(
    "/recorders/{recorder_id}",
    response_model=RecorderResponse,
    summary="Get recorder (admin)",
    description="BFF adapter for the legacy admin recorder detail endpoint.",
)
async def get_recorder(
    recorder_id: str,
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> RecorderResponse:
    """Delegate admin recorder detail to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_GET_ACTION,
        current_user=current_user,
        request=request,
    )
    return await legacy_admin.get_recorder(
        recorder_id=recorder_id,
        request=request,
        db=db,
        current_user=current_user,
    )


@router.patch(
    "/recorders/{recorder_id}",
    response_model=RecorderResponse,
    summary="Update recorder (admin)",
    description="BFF adapter for the legacy admin recorder update endpoint.",
)
async def update_recorder(
    recorder_id: str,
    request: RecorderUpdate,
    http_request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> RecorderResponse:
    """Delegate admin recorder update to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_UPDATE_ACTION,
        current_user=current_user,
        request=http_request,
    )
    return await legacy_admin.update_recorder(
        recorder_id=recorder_id,
        request=request,
        http_request=http_request,
        db=db,
        current_user=current_user,
    )


@router.delete(
    "/recorders/{recorder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete recorder (admin)",
    description="BFF adapter for the legacy admin recorder delete endpoint.",
)
async def delete_recorder(
    recorder_id: str,
    request: Request,
    db: DbSession,
    current_user: CurrentSuperuser,
) -> None:
    """Delegate admin recorder delete to the legacy handler."""
    _gate_admin_platform_action(
        action=ADMIN_RECORDER_DELETE_ACTION,
        current_user=current_user,
        request=request,
    )
    await legacy_admin.delete_recorder(
        recorder_id=recorder_id,
        request=request,
        db=db,
        current_user=current_user,
    )


__all__ = ["router"]
