"""ToriTore (とりトレ) self-service BFF endpoints (preview).

Two first-party (cookie + CSRF) endpoints under ``/web-api/v1/me`` that let
the authenticated user upload their ToriTore JSON export and read back their
proficiency summary:

* ``POST /me/toritore-results`` — body is the raw ToriTore JSON object.
  Ingested for the authenticated user and the refreshed summary is returned.
* ``GET  /me/toritore-results`` — current proficiency summary.

Gating
------
Both endpoints operate strictly on the authenticated session user
(resolved by :data:`echoroo.middleware.auth.CurrentUser`); there is no
project context and no cross-user side effect, so they carry NO
``gate_action`` project-permission guard. They are classified
``USER_SCOPED_ONLY`` in :mod:`echoroo.core.endpoint_allowlist` — the same
trust boundary as ``/web-api/v1/me/banners`` and the step-up endpoints.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.toritore import ToriToreSummary
from echoroo.services import toritore as toritore_service

router = APIRouter(prefix="/me", tags=["me"])


@router.post(
    "/toritore-results",
    response_model=ToriToreSummary,
    summary="Upload a ToriTore JSON export (preview)",
)
async def upload_toritore_results(
    current_user: CurrentUser,
    db: DbSession,
    request: Request,  # noqa: ARG001 — kept for parity / future audit use
    payload: dict[str, Any] = Body(...),
) -> ToriToreSummary:
    """Ingest the uploading user's ToriTore export and return the summary."""
    return await toritore_service.ingest_upload(db, current_user.id, payload)


@router.get(
    "/toritore-results",
    response_model=ToriToreSummary,
    summary="Get the authenticated user's ToriTore proficiency summary (preview)",
)
async def get_toritore_results(
    current_user: CurrentUser,
    db: DbSession,
    request: Request,  # noqa: ARG001 — kept for parity / future audit use
) -> ToriToreSummary:
    """Return the proficiency summary for the authenticated user."""
    return await toritore_service.get_summary(db, current_user.id)


__all__ = ["router"]
