"""spec/011 US7 — in-app banner + activity endpoints (T600-T602).

Three first-party (cookie + CSRF) endpoints under ``/web-api/v1/me``
that expose the read side of the banner subsystem built in
:mod:`echoroo.services.user_banner`:

* ``GET /me/banners`` (T600, FR-011-301/302) — undismissed,
  banner-eligible audit rows targeting the authenticated user, age-
  capped at 30 days. Each row's raw ``detail`` is reduced to an
  A-13-safe ``summary`` by :func:`echoroo.services.banner_presenter`.
* ``POST /me/banners/dismiss`` (T601, FR-011-302) — record a dismissal.
  Not-found / not-targeting / bad-``audit_table`` all collapse to a
  single identical 404 (anti-enumeration); the service already merges
  those three conditions into :class:`BannerNotFoundError`.
* ``GET /me/activity`` (T602, FR-011-307) — the permanent reverse-
  chronological audit history (no dismissal filter, no age cap), with
  opaque keyset-cursor pagination.

Gating
------
These endpoints operate strictly on the authenticated session user
(resolved by :data:`echoroo.middleware.auth.CurrentUser`); there is no
project context and no cross-user side effect, so they carry NO
``gate_action`` project-permission guard. They are classified
``USER_SCOPED_ONLY`` in :mod:`echoroo.core.endpoint_allowlist` — the
same trust boundary as ``/web-api/v1/auth/change-password`` and the
step-up endpoints. Cookie + CSRF transport is enforced by the
production middleware chain.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.services import banner_presenter, user_banner
from echoroo.services.user_banner import BannerNotFoundError

router = APIRouter(prefix="/me", tags=["me"])


# ---------------------------------------------------------------------------
# Response / request models (mirror contracts/me-banners-activity.yaml)
# ---------------------------------------------------------------------------


class BannerItemOut(BaseModel):
    """One undismissed banner (OpenAPI ``BannerItem``)."""

    audit_table: str
    audit_log_id: UUID
    action: str
    occurred_at: datetime
    summary: str
    link: str | None = None


class BannerListOut(BaseModel):
    """Envelope for ``GET /me/banners``."""

    items: list[BannerItemOut]


class DismissIn(BaseModel):
    """Request body for ``POST /me/banners/dismiss``."""

    audit_table: str
    audit_log_id: UUID


class ActivityItemOut(BaseModel):
    """One audit-history row (OpenAPI ``ActivityItem``)."""

    audit_table: str
    audit_log_id: UUID
    action: str
    occurred_at: datetime
    project_id: UUID | None = None
    actor_user_id: UUID | None = None
    details: dict[str, Any]


class ActivityPageOut(BaseModel):
    """Envelope for ``GET /me/activity`` (keyset pagination)."""

    items: list[ActivityItemOut]
    next_cursor: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/banners",
    response_model=BannerListOut,
    summary="List undismissed banners for the authenticated user (FR-011-301)",
)
async def list_me_banners(
    request: Request,  # noqa: ARG001 — kept for future rate-limit / audit use
    current_user: CurrentUser,
    db: DbSession,
) -> BannerListOut:
    """Return undismissed, banner-eligible audit rows for the caller.

    The raw audit ``detail`` is intentionally NOT surfaced — only an
    A-13-safe ``summary`` (see :func:`banner_presenter.summarize_banner`)
    and the row coordinates the dismiss endpoint needs.
    """
    banners = await user_banner.list_banners(db, user_id=current_user.id)
    return BannerListOut(
        items=[
            BannerItemOut(
                audit_table=banner.audit_table,
                audit_log_id=banner.audit_log_id,
                action=banner.action,
                occurred_at=banner.occurred_at,
                summary=banner_presenter.summarize_banner(
                    action=banner.action,
                    occurred_at=banner.occurred_at,
                ),
                link=None,
            )
            for banner in banners
        ]
    )


@router.post(
    "/banners/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Dismiss a banner (FR-011-302)",
    responses={
        status.HTTP_204_NO_CONTENT: {
            "description": (
                "Dismissal recorded (idempotent — second call returns 204 "
                "too). Banner will not appear again in GET /me/banners."
            )
        },
        status.HTTP_404_NOT_FOUND: {
            "description": (
                "Audit row not found OR not targeting this user OR "
                "audit_table not allowlisted (anti-enumeration → identical "
                "status + body for all three)."
            )
        },
    },
)
async def dismiss_me_banner(
    payload: DismissIn,
    request: Request,  # noqa: ARG001 — kept for future rate-limit / audit use
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    """Record a dismissal for ``(audit_table, audit_log_id)``.

    Anti-enumeration (FR-011-302): "row not found", "row not targeting
    this user", and "``audit_table`` outside the allowlist" all collapse
    to the SAME 404 (status + body). The service raises a single
    :class:`BannerNotFoundError` for all three so the divergence never
    reaches the wire. Repeated dismissals are idempotent (the service's
    ``INSERT ... ON CONFLICT DO NOTHING``) and return 204 each time.
    """
    try:
        await user_banner.dismiss(
            db,
            user_id=current_user.id,
            audit_table=payload.audit_table,
            audit_log_id=payload.audit_log_id,
        )
    except BannerNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        ) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/activity",
    response_model=ActivityPageOut,
    summary="List the authenticated user's audit history (FR-011-307)",
)
async def list_me_activity(
    request: Request,  # noqa: ARG001 — kept for future rate-limit / audit use
    current_user: CurrentUser,
    db: DbSession,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=user_banner.DEFAULT_ACTIVITY_LIMIT, ge=1, le=100),
) -> ActivityPageOut:
    """Return one keyset-paginated page of the caller's audit history.

    Dismissal does NOT filter this list and the 30-day banner age cap
    does NOT apply (FR-011-307). ``actor_user_id`` is always ``null``:
    the service only persists the HASHED actor id and cannot un-hash it
    (OQ4).
    """
    page = await user_banner.list_activity(
        db,
        user_id=current_user.id,
        cursor=cursor,
        limit=limit,
    )
    return ActivityPageOut(
        items=[
            ActivityItemOut(
                audit_table=item.audit_table,
                audit_log_id=item.audit_log_id,
                action=item.action,
                occurred_at=item.occurred_at,
                project_id=item.project_id,
                actor_user_id=None,
                details=item.detail,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


__all__ = ["router"]
