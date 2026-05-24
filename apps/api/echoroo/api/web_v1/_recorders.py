"""Recorder list BFF adapter (spec/009 PR 4).

Spec/009 PR 4 moves the public recorder listing surface from
``/api/v1/recorders`` to ``/web-api/v1/recorders``. The legacy
``/api/v1/recorders.py`` handler stays in place to serve the API-key
surface; the BFF layer is a thin adapter that lands the request on the
cookie + CSRF session boundary and re-uses the legacy service.

This module is mounted directly under ``/web-api/v1`` (not under
``/web-api/v1/projects``) because the legacy router is *not* project
scoped — recorders are a tenant-wide catalog used by the dataset
creation UI.

Endpoint (1):

* GET    ``/recorders``                              → no Action

The legacy ``list_recorders`` handler relies on the ``CurrentUser``
dependency alone (no ``gate_action``); the BFF mirrors that decision so
behaviour parity holds. ``permission_guard_allowlist`` therefore needs
a thin-adapter entry — see the allowlist comment block. The response
model is :class:`RecorderListResponse`, which does not name ``Recording``
/ ``Detection`` / ``Site``, so no response-filter allowlist entry is
required.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from echoroo.api.v1 import recorders as legacy_recorders
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.recorder import RecorderListResponse

router = APIRouter(prefix="/recorders", tags=["recorders"])


@router.get(
    "",
    response_model=RecorderListResponse,
    summary="List recorders",
    description="BFF adapter for the legacy public recorder list endpoint.",
)
async def list_recorders(
    current_user: CurrentUser,
    service: legacy_recorders.RecorderServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> RecorderListResponse:
    """Delegate recorder list to the legacy handler."""
    return await legacy_recorders.list_recorders(
        current_user=current_user,
        service=service,
        page=page,
        limit=limit,
    )


__all__ = ["router"]
