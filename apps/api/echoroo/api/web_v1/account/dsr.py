"""DSR (Data Subject Request) endpoints (Phase 14 / T900, FR-105 / FR-109).

Contract: ``specs/006-permissions-redesign/contracts/account.yaml``.

Path operations owned by this module (all under
``/web-api/v1/account/dsr``):

* ``POST /export`` — synchronous JSON export of every first-party row
  the caller can claim under FR-109.
* ``POST /delete`` — soft-delete the caller's ``users`` row (FR-105).

Spec rationale
--------------
* ``audit_log``-family rows are deliberately excluded from the export
  payload: they only persist hashed actor identifiers (FR-091a / b)
  so they cannot be re-personalised.
* The export queries ``project_invitations`` and
  ``project_trusted_users`` by HMAC ``email_hash`` (FR-055) so an
  invitation that was issued before the user accepted it (and that
  therefore has no FK back to ``users.id``) is still surfaced.
* The delete endpoint mutates the row inside the request session and
  fires the ``platform_audit_log`` write from a fresh session AFTER
  the main TX commits — mirrors the pattern in
  :mod:`echoroo.services.superuser_approval_service` so the
  SERIALIZABLE upgrade succeeds.

Cookie + CSRF transport is enforced by the production middleware
chain (``CsrfMiddleware`` + ``AuthRouterMiddleware``) which
:func:`echoroo.main.create_app` wires in. This handler only resolves
the principal and runs the application-layer guards.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Request, Response, status

from echoroo.core.database import DbSession
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.annotation_vote import AnnotationVote
from echoroo.models.project import (
    ProjectInvitation,
    ProjectMember,
)
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.models.user import User
from echoroo.services.invitation_service import hash_email
from echoroo.services.user_deletion_service import (
    UserAlreadyDeletedError,
    UserNotFoundError,
    soft_delete_user,
    trigger_post_commit_audit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dsr")


# ---------------------------------------------------------------------------
# Request envelope helpers — mirrors the conventions used by
# ``api/web_v1/admin.py`` and ``api/web_v1/trusted.py`` so the audit
# rows produced by this module carry the same actor / request
# envelope shape.
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent") or ""


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or ""


def _require_authenticated(current_user: User | None) -> User:
    """401 unless the caller is authenticated and not soft-deleted.

    The auth middleware already rejects sessions whose ``users`` row
    carries ``deleted_at IS NOT NULL`` (see
    :mod:`echoroo.services.session_verification`), but we re-check
    here defensively in case a custom auth path bypasses the middleware.
    """
    if current_user is None or getattr(current_user, "deleted_at", None) is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return current_user


def _isoformat(value: datetime | None) -> str | None:
    """Serialise a tz-aware datetime to ISO-8601 or pass NULL through."""
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# POST /account/dsr/export — FR-109
# ---------------------------------------------------------------------------


async def _export_user_payload(user: User) -> dict[str, Any]:
    """Render the ``user`` block of the DSR export response."""
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "two_factor_enabled": user.two_factor_enabled,
        "last_login_at": _isoformat(user.last_login_at),
        "last_first_party_activity_at": _isoformat(
            user.last_first_party_activity_at
        ),
        "registered_timezone": user.registered_timezone,
        "created_at": _isoformat(user.created_at),
        "deleted_at": _isoformat(user.deleted_at),
    }


async def _export_memberships(
    db: DbSession,
    user_id: UUID,
) -> list[dict[str, Any]]:
    """Return every ``project_members`` row keyed on ``user_id``.

    Removed memberships (``removed_at IS NOT NULL``) are deliberately
    included — the row is part of the user's personal history even
    after revocation, which the spec wants surfaced under FR-109.
    """
    stmt = sa.select(ProjectMember).where(ProjectMember.user_id == user_id)
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "project_id": str(row.project_id),
            "role": row.role.value,
            "joined_at": _isoformat(row.joined_at),
            "expires_at": _isoformat(row.expires_at),
            "removed_at": _isoformat(row.removed_at),
        }
        for row in rows
    ]


async def _export_invitations(
    db: DbSession,
    *,
    email_hash_value: str,
) -> list[dict[str, Any]]:
    """Return every ``project_invitations`` row whose ``email_hash`` matches.

    We match on the HMAC hash (FR-055) rather than ``email`` so older
    rows whose plaintext was already nulled by
    :mod:`echoroo.workers.invitation_email_null` (FR-106) still appear.
    """
    stmt = sa.select(ProjectInvitation).where(
        ProjectInvitation.email_hash == email_hash_value
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "kind": row.kind.value,
            "role": row.role.value if row.role is not None else None,
            "status": row.status.value,
            "email": row.email,
            "expires_at": _isoformat(row.expires_at),
            "accepted_at": _isoformat(row.accepted_at),
            "declined_at": _isoformat(row.declined_at),
            "revoked_at": _isoformat(row.revoked_at),
            "created_at": _isoformat(row.created_at),
        }
        for row in rows
    ]


async def _export_trusted_overlays(
    db: DbSession,
    *,
    user_id: UUID,
    email_hash_value: str,
) -> list[dict[str, Any]]:
    """Return every ``project_trusted_users`` row owned by the caller.

    The capability overlay carries ``user_id`` (post-accept) AND
    ``email_at_invitation_hash`` (capture-time HMAC). We OR the two
    predicates so a stale historical overlay whose ``user_id`` was
    later transferred (a hypothetical future migration) still surfaces.
    """
    stmt = sa.select(ProjectTrustedUser).where(
        sa.or_(
            ProjectTrustedUser.user_id == user_id,
            ProjectTrustedUser.email_at_invitation_hash == email_hash_value,
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "status": row.status.value,
            "granted_permissions": list(row.granted_permissions or []),
            "granted_at": _isoformat(row.granted_at),
            "expires_at": _isoformat(row.expires_at),
            "revoked_at": _isoformat(row.revoked_at),
            "email_at_invitation": row.email_at_invitation,
        }
        for row in rows
    ]


async def _export_votes(
    db: DbSession,
    user_id: UUID,
) -> list[dict[str, Any]]:
    """Return every ``annotation_votes`` row keyed on ``voter_user_id``."""
    stmt = sa.select(AnnotationVote).where(
        AnnotationVote.voter_user_id == user_id
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(row.id),
            "annotation_id": str(row.annotation_id),
            "project_id": str(row.project_id),
            "vote": int(row.vote),
            "source": row.source.value,
            "project_role_at_vote": (
                row.project_role_at_vote.value
                if row.project_role_at_vote is not None
                else None
            ),
            "created_at": _isoformat(row.created_at),
            "updated_at": _isoformat(row.updated_at),
        }
        for row in rows
    ]


@router.post(
    "/export",
    status_code=status.HTTP_200_OK,
    summary="Export the caller's first-party data (GDPR DSR, FR-109)",
)
async def dsr_export(
    request: Request,  # noqa: ARG001 — kept for future rate-limit / audit use
    db: DbSession,
    current_user: OptionalCurrentUser,
) -> dict[str, Any]:
    """Return the caller's full DSR payload.

    The body shape is documented in
    ``specs/006-permissions-redesign/contracts/account.yaml``
    (``DsrExportResponse``). Audit-log family rows are excluded by
    design (FR-091a/b — those tables persist only hashed actor
    identifiers and cannot be re-personalised).

    Rate limit: TODO post-launch — the spec mandates 1 successful
    export per user per 24 hours but the production rate-limiter
    surface is not yet wired into this module. We log the call so
    the ops dashboard can monitor the volume; the daily cap will
    land alongside the broader Redis rate-limit work.
    """
    user = _require_authenticated(current_user)

    settings = get_settings()
    email_hash_value = hash_email(
        user.email,
        hmac_secret=settings.web_session_secret,
    )

    # ``platform_audit_log`` / ``project_audit_log`` are intentionally
    # NOT exported — see FR-091a/b. Every row in those tables stores
    # only HMAC-hashed actor identifiers, so the user has no readable
    # rows to reclaim there.
    payload: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "user": await _export_user_payload(user),
        "project_memberships": await _export_memberships(db, user.id),
        "project_invitations": await _export_invitations(
            db, email_hash_value=email_hash_value
        ),
        "trusted_user_overlays": await _export_trusted_overlays(
            db,
            user_id=user.id,
            email_hash_value=email_hash_value,
        ),
        "annotation_votes": await _export_votes(db, user.id),
    }
    logger.info(
        "dsr_export: user_id=%s memberships=%d invitations=%d "
        "trusted=%d votes=%d",
        user.id,
        len(payload["project_memberships"]),
        len(payload["project_invitations"]),
        len(payload["trusted_user_overlays"]),
        len(payload["annotation_votes"]),
    )
    return payload


# ---------------------------------------------------------------------------
# POST /account/dsr/delete — FR-105
# ---------------------------------------------------------------------------


@router.post(
    "/delete",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete the caller's account (GDPR right to erasure, FR-105)",
)
async def dsr_delete(
    request: Request,
    response: Response,
    db: DbSession,
    current_user: OptionalCurrentUser,
) -> dict[str, Any]:
    """Anonymise the caller's ``users`` row in place (FR-105).

    Mutation happens inside the dependency-managed
    :class:`AsyncSession`; the ``platform_audit_log`` row is written
    from a fresh session AFTER the main TX commits (the SERIALIZABLE
    upgrade required by :class:`AuditLogService` cannot share a
    connection with prior SELECTs / UPDATEs).

    The endpoint also clears the session cookie so the browser does
    not keep replaying a now-invalid ``session_id`` value. The cookie
    name (``session_id``) and attributes (``Path=/web-api/v1/``,
    ``HttpOnly``, ``Secure``, ``SameSite=Strict``) match the issuer
    in :mod:`echoroo.api.web_v1.auth`.
    """
    user = _require_authenticated(current_user)

    request_id = _request_id(request)
    ip = _client_ip(request)
    ua = _user_agent(request)

    try:
        outcome = await soft_delete_user(
            db,
            user_id=user.id,
            request_id=request_id,
            ip=ip,
            user_agent=ua,
        )
    except UserAlreadyDeletedError:
        # The auth middleware would normally reject the session
        # before this handler runs, but a race or a custom auth
        # path could land us here — surface a 401 to keep the
        # endpoint idempotent (the spec requires that a second
        # delete by the same caller is a no-op, not a 500).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from None
    except UserNotFoundError:
        # Should be impossible while the session resolves to a row;
        # treat as 401 for the same reason as above.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from None

    # Force the session/connection to flush the mutation; the
    # ``get_db`` dependency commits when the handler returns
    # successfully. We rely on its commit hook to make the row
    # change durable before the post-commit audit fires.
    await db.flush()

    # Clear the session cookie so the browser stops replaying it.
    # Mirror the issuer's attribute set so production caches do not
    # keep a residual cookie around.
    response.delete_cookie(
        key="session_id",
        path="/web-api/v1/",
        httponly=True,
        secure=True,
        samesite="strict",
    )

    # The audit row is written by the post-commit hook. We schedule
    # it AFTER the dependency-managed commit by using FastAPI's
    # ``BackgroundTasks``-equivalent pattern: the simplest version
    # is an explicit ``await`` here followed by an explicit commit
    # — but the dependency commit happens *after* this handler
    # returns. We therefore commit the main session ourselves first
    # so the audit writer sees a durable row, then call the audit
    # hook. The dependency's commit-on-return becomes a no-op
    # because the session is already flushed and committed.
    await db.commit()
    await trigger_post_commit_audit(outcome)

    logger.info(
        "dsr_delete: user_id=%s deleted_at=%s",
        outcome.user_id,
        outcome.deleted_at.isoformat(),
    )
    return {
        "user_id": str(outcome.user_id),
        "deleted_at": outcome.deleted_at.isoformat(),
    }


__all__ = ["router"]
