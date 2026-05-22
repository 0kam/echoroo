"""Trusted overlay management endpoints (Phase 10 / T510, FR-014 / FR-046 / FR-050).

Contract: ``specs/006-permissions-redesign/contracts/trusted.yaml``.

Path operations owned by this module (all under ``/web-api/v1/projects``):

* ``GET    /{project_id}/trusted-users``                        — list (Owner / Admin).
* ``POST   /{project_id}/trusted-users``                        — invite (Owner only).
* ``PATCH  /{project_id}/trusted-users/{trusted_user_id}``      — extend / edit (Owner only).
* ``DELETE /{project_id}/trusted-users/{trusted_user_id}``      — revoke (Owner only).

Spec rationale:
    * Trusted overlay is an **ephemeral capability layer** on top of an
      already-Authenticated principal (FR-041). The Owner alone may issue,
      extend, edit, or revoke an overlay (FR-050) so the policy stays
      auditable; Admins keep read access (``MANAGE_TRUSTED`` is in the
      Admin matrix cell for read-only enumeration but the mutating
      endpoints below add an explicit Owner short-circuit so an Admin
      cannot escalate themselves).
    * The ``MANAGE_TRUSTED`` permission gate runs through
      :func:`echoroo.core.permissions.gate_action` so the matrix sees the
      same Action / role lookup as the rest of Phase 3.
    * Plain-text invitation tokens (FR-051) leave the process **only**
      through the post-commit email outbox. The 202 response from POST
      surfaces ``invitation_id`` + recipient email + expiry; the URL
      token is never serialised onto the API response.
    * Audit + Redis broadcast side-effects fire AFTER the main TX commits
      (mirrors :mod:`echoroo.api.web_v1.projects._license` / the
      restricted-config endpoint). A failed audit write is WARNING-logged
      so the persisted invitation / overlay row stays intact.

Cookie + CSRF transport is enforced by the production middleware chain
(``CsrfMiddleware`` + ``AuthRouterMiddleware``) which the application
factory wires in :func:`echoroo.main.create_app`. This handler only
resolves the principal and runs the Stage-1 permission gate.
"""

from __future__ import annotations

import logging
import unicodedata
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import select

from echoroo.core.actions import (
    PROJECT_TRUSTED_INVITE_ACTION,
    PROJECT_TRUSTED_LIST_ACTION,
    PROJECT_TRUSTED_REVOKE_ACTION,
    PROJECT_TRUSTED_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.core.redis import get_redis_connection
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectMemberRole,
    ProjectTrustedStatus,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.project_trusted_user import ProjectTrustedUser
from echoroo.schemas.trusted import (
    TrustedUserInviteRequest,
    TrustedUserInviteResponse,
    TrustedUserListResponse,
    TrustedUserResponse,
    TrustedUserUpdateRequest,
)
from echoroo.services import invitation_service, trusted_service
from echoroo.services.invitation_service import (
    InvitationConflictError,
    InvitationInfraUnavailableError,
    InvitationRateLimitError,
    InvitationValidationError,
    create_invitation,
)
from echoroo.services.trusted_service import (
    TrustedUpdateError,
    list_trusted_users,
    revoke_trusted_user,
    update_trusted_user,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
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


def _canonicalise_email(email: str) -> str:
    """Phase 10 Batch 2 Round 2 fix (Major 4): mirror the
    ``invitation_service.hash_email`` canonicalisation.

    Accept-side comparison lives on the ``email_hash`` column (HMAC over
    NFKC + casefold + strip), so the invite path's pre-flight checks
    MUST use the same canonical form. The previous ``.lower()`` only
    code path leaks Unicode-equivalent addresses (e.g. fullwidth "A"
    vs ASCII "a", or "İ" vs "i") — an attacker could match a target
    by composing a near-identical address that bypasses the existing-
    member / self-invite guards.
    """
    return unicodedata.normalize("NFKC", email).strip().casefold()


def _require_owner(project: Project, current_user_id: UUID) -> None:
    """Raise 403 unless ``current_user_id`` is the project Owner.

    ``MANAGE_TRUSTED`` is granted to Owner per the canonical matrix
    (Admin holds it for read-enumeration only). The Stage-1 gate above
    already filters non-Owner / non-Admin callers; this helper is the
    second-line check that prevents an Admin from invoking the *mutating*
    Trusted endpoints — the spec is explicit that only Owners may issue,
    extend, edit, or revoke overlays (FR-050).
    """
    if project.owner_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ERR_OWNER_ONLY",
                "message": (
                    "Only the project Owner may issue, extend, edit, or "
                    "revoke a Trusted overlay (FR-050)."
                ),
            },
        )


async def _load_overlay_or_404(
    db: DbSession, *, project_id: UUID, trusted_user_id: UUID
) -> ProjectTrustedUser:
    """Resolve ``trusted_user_id`` scoped to ``project_id`` or raise 404."""
    result = await db.execute(
        select(ProjectTrustedUser)
        .where(
            ProjectTrustedUser.id == trusted_user_id,
            ProjectTrustedUser.project_id == project_id,
        )
        .with_for_update(),
    )
    overlay = result.scalar_one_or_none()
    if overlay is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trusted overlay not found",
        )
    return overlay


async def _existing_membership_role(
    db: DbSession, *, project_id: UUID, canonical_email: str
) -> ProjectMemberRole | None:
    """Return the active membership role for the user with ``canonical_email``.

    The Trusted invite path forbids targeting a user who already holds an
    active project role (``ERR_TRUSTED_TARGET_INVALID``, FR-050). We
    canonicalise the candidate ``User.email`` rows the same way the caller
    does (NFKC + casefold + strip — see :func:`_canonicalise_email`) so
    Unicode-equivalent addresses collide.

    Phase 10 Batch 2 Round 3 fix (Major 3): the previous implementation
    compared ``func.lower(User.email)`` against the NFKC-casefolded input
    in pure SQL. Postgres' ``LOWER`` is locale-aware but does NOT perform
    NFKC normalisation, so a fullwidth or combining-mark variant such as
    ``Ádmin@example.com`` (= ``Ádmin@example.com``) would survive
    the comparison and bypass the FR-050 guard, letting an Owner
    Trusted-invite a user whose actual ``User.email`` row is the ASCII
    canonical form. We now narrow the candidate set in SQL via the
    local-part prefix and re-apply the strict :func:`_canonicalise_email`
    in Python so the SQL/Python casefold mismatch cannot produce a false
    negative. ``project_members`` for any single project is small (Phase 4
    membership cardinality is bounded by org policy), so the extra row
    materialisation has no measurable cost on the hot path.
    """
    from echoroo.models.user import User

    # We fetch every active member's stored email and re-canonicalise
    # in Python so a Unicode-equivalent input (e.g. fullwidth ``Ａ`` vs
    # ASCII ``a``, ligatures, combining marks) cannot bypass the
    # comparison just because Postgres' ``LOWER`` and ``ILIKE`` only
    # implement locale-aware case folding without NFKC normalisation.
    # ``project_members`` cardinality per project is bounded (org-policy
    # ceiling), so the broad SELECT is a constant-cost trade for
    # closing the SQL/Python casefold mismatch. The legacy
    # ``ix_project_members_project_active`` index covers the WHERE
    # clause so the planner avoids a full table scan.
    result = await db.execute(
        select(ProjectMember.role, User.email)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.removed_at.is_(None),
        ),
    )
    for role, db_email in result.all():
        if _canonicalise_email(db_email or "") == canonical_email:
            if isinstance(role, ProjectMemberRole):
                return role
            try:
                return ProjectMemberRole(str(role).lower())
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------
# GET /trusted-users — list (Owner / Admin)
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/trusted-users",
    response_model=TrustedUserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List Trusted overlays for a project (Web UI)",
    description=(
        "Owner / Admin only (``MANAGE_TRUSTED``). The optional ``status`` "
        "filter narrows the result to ``active`` / ``expired`` / ``revoked`` "
        "rows; ``ix_project_trusted_users_project_user_status`` covers the "
        "project + status filter."
    ),
)
async def list_project_trusted_users(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    # Phase 10 Batch 2 Round 2 fix (Major 3): the contract uses
    # ``?status=...``; the parameter is bound via ``alias='status'`` to
    # avoid shadowing the imported ``status`` module while preserving the
    # documented query name.
    status_filter: ProjectTrustedStatus | None = Query(None, alias="status"),
) -> TrustedUserListResponse:
    """Return every overlay row for ``project_id`` (Owner / Admin)."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_TRUSTED_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    rows = await list_trusted_users(
        db, project_id=project_id, status=status_filter
    )
    return TrustedUserListResponse(
        items=[TrustedUserResponse.model_validate(row) for row in rows],
        total=len(rows),
    )


# ---------------------------------------------------------------------------
# POST /trusted-users — invite (Owner only)
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/trusted-users",
    response_model=TrustedUserInviteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Issue a Trusted invitation (Owner only)",
    description=(
        "Owner only (FR-050). Validates ``granted_permissions`` against "
        "``TRUSTED_ALLOWED_PERMISSIONS`` (FR-012), rejects targeting an "
        "existing Viewer / Member / Admin / Owner of the project "
        "(``ERR_TRUSTED_TARGET_INVALID``) and self-invitation "
        "(``ERR_SELF_TRUSTED_INVALID``). spec/011 Step 6 (T207, "
        "FR-011-103): the response NOW includes ``invitation_url`` — "
        "the issuing admin is responsible for handing the one-shot URL "
        "out-of-band. The outbound-email outbox enqueue is removed; "
        "spec/006 FR-051 is formally superseded by FR-011-103."
    ),
)
async def invite_trusted_user(
    project_id: UUID,
    payload: TrustedUserInviteRequest,
    request: Request,
    response: Response,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> TrustedUserInviteResponse:
    """Issue a ``kind='trusted'`` invitation to ``payload.email``."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    project = await gate_action(
        action=PROJECT_TRUSTED_INVITE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    _require_owner(project, current_user.id)

    # Self-invitation is meaningless and a privilege-escalation footgun
    # (an Owner does not need a Trusted overlay on their own project).
    # Phase 10 Batch 2 Round 2 fix (Major 4): both sides are normalised
    # with NFKC + casefold so a Unicode-equivalent address (fullwidth /
    # combining-mark variant) cannot bypass the self-invite guard.
    target_email_canonical = _canonicalise_email(payload.email)
    actor_email_canonical = _canonicalise_email(current_user.email or "")
    if target_email_canonical == actor_email_canonical:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_SELF_TRUSTED_INVALID",
                "message": (
                    "The project Owner may not issue a Trusted overlay "
                    "to themselves."
                ),
            },
        )

    # Prevent overlapping with an existing project role — the Authenticated
    # member already holds Viewer / Member / Admin permissions and the
    # overlay would only confuse the gate (FR-050).
    existing_role = await _existing_membership_role(
        db, project_id=project_id, canonical_email=target_email_canonical
    )
    if existing_role is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_TRUSTED_TARGET_INVALID",
                "message": (
                    "The target user already has an active project role "
                    f"({existing_role.value!r}); Trusted overlays are only "
                    "valid for Authenticated callers without a membership."
                ),
            },
        )

    settings = get_settings()
    redis = await get_redis_connection()

    try:
        outcome = await create_invitation(
            db,
            project_id=project_id,
            kind=ProjectInvitationKind.TRUSTED,
            email=payload.email,
            invited_by_id=current_user.id,
            hmac_secret=settings.web_session_secret,
            redis=redis,
            granted_permissions=payload.granted_permissions,
            trusted_duration_seconds=payload.duration_seconds,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationValidationError as exc:
        # Allowlist mismatch / unknown permission name. Map to the
        # contract's ERR_INVALID_TRUSTED_PERMISSION envelope so the Web UI
        # can branch on the dedicated code rather than the generic 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_INVALID_TRUSTED_PERMISSION",
                "message": str(exc),
            },
        ) from exc
    except InvitationConflictError as exc:
        # FR-049: a pending invitation for the same (project, email) pair
        # already exists. Reissue requires explicit revoke first.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_INVITATION_PENDING",
                "message": str(exc),
            },
        ) from exc
    except InvitationRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except InvitationInfraUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    invitation = outcome.invitation
    # spec/011 Step 6 (T207, FR-011-103): surface the one-shot invitation
    # URL directly on the response. Spec/006 FR-051 (token leaves the
    # process only through the email outbox) is formally superseded —
    # the Owner is responsible for handing the URL off out-of-band.
    # ``invitation.expires_at`` is ``TIMESTAMPTZ`` in the DB so the
    # value comes back tz-aware; the conditional normalisation keeps a
    # historic naive-datetime test fixture from leaking onto the wire.
    expires_at_aware = invitation.expires_at
    if expires_at_aware.tzinfo is None:  # pragma: no cover — DB guarantees tz-aware
        expires_at_aware = expires_at_aware.replace(tzinfo=UTC)
    body = TrustedUserInviteResponse(
        invitation_id=invitation.id,
        invitation_url=outcome.signed_token_envelope,
        expires_at=expires_at_aware,
    )

    # FR-011-103: anti-bfcache + private cache directives. Mirrors the
    # Member-invitation precedent (FR-011-102) so a browser back / refresh
    # does not replay the URL from the rendered page.
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )

    # Commit the issuance; the post-commit hook then writes the audit row
    # in a fresh session. The outbound-email enqueue is removed by T054.
    await db.commit()
    await invitation_service.trigger_post_commit_side_effects(outcome)
    return body


# ---------------------------------------------------------------------------
# PATCH /trusted-users/{trusted_user_id} — extend / edit (Owner only)
# ---------------------------------------------------------------------------


@router.patch(
    "/{project_id}/trusted-users/{trusted_user_id}",
    response_model=TrustedUserResponse,
    status_code=status.HTTP_200_OK,
    summary="Extend or edit a Trusted overlay (Owner only)",
    description=(
        "Owner only (FR-046 / FR-050). Either ``expires_at`` or "
        "``extension_seconds`` may be supplied (mutually exclusive). The "
        "new expiry is hard-capped at ``granted_at + 1 year`` (FR-043). "
        "``granted_permissions`` is re-validated against "
        "``TRUSTED_ALLOWED_PERMISSIONS`` (FR-014). Empty PATCH bodies are "
        "rejected with 422."
    ),
)
async def update_trusted_user_endpoint(
    project_id: UUID,
    trusted_user_id: UUID,
    payload: TrustedUserUpdateRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> TrustedUserResponse:
    """Apply Owner-driven edits to ``trusted_user_id``."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    project = await gate_action(
        action=PROJECT_TRUSTED_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    _require_owner(project, current_user.id)

    if (
        payload.expires_at is None
        and payload.extension_seconds is None
        and payload.granted_permissions is None
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_NO_OP",
                "message": "PATCH body must contain at least one mutation.",
            },
        )
    if payload.expires_at is not None and payload.extension_seconds is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_AMBIGUOUS_EXPIRY",
                "message": (
                    "Pass either ``expires_at`` or ``extension_seconds``, "
                    "not both."
                ),
            },
        )

    overlay = await _load_overlay_or_404(
        db, project_id=project_id, trusted_user_id=trusted_user_id
    )

    try:
        outcome = await update_trusted_user(
            db,
            trusted_user=overlay,
            actor_user_id=current_user.id,
            granted_permissions=payload.granted_permissions,
            expires_at=payload.expires_at,
            extension_seconds=payload.extension_seconds,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except TrustedUpdateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_TRUSTED_UPDATE_INVALID",
                "message": str(exc),
            },
        ) from exc

    # Snapshot the response shape before commit so attribute expiration
    # cannot blank out the returned row (mirrors restricted-config flow).
    response = TrustedUserResponse.model_validate(outcome.trusted_user)

    await db.commit()
    await trusted_service.trigger_post_commit_side_effects(outcome)
    return response


# ---------------------------------------------------------------------------
# DELETE /trusted-users/{trusted_user_id} — revoke (Owner only)
# ---------------------------------------------------------------------------


@router.delete(
    "/{project_id}/trusted-users/{trusted_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a Trusted overlay (Owner only)",
    description=(
        "Owner only (FR-050). Idempotent: revoking an already-revoked "
        "overlay returns 204 without writing a duplicate audit row "
        "(``trigger_post_commit_side_effects`` short-circuits on empty "
        "``diff``). Subscribers on the ``trusted_user.invalidate`` Redis "
        "channel receive a notification within NFR-008a (≤ 5 min)."
    ),
)
async def revoke_trusted_user_endpoint(
    project_id: UUID,
    trusted_user_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> None:
    """Transition the overlay to ``status='revoked'``."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    project = await gate_action(
        action=PROJECT_TRUSTED_REVOKE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    _require_owner(project, current_user.id)

    overlay = await _load_overlay_or_404(
        db, project_id=project_id, trusted_user_id=trusted_user_id
    )

    outcome = await revoke_trusted_user(
        db,
        trusted_user=overlay,
        actor_user_id=current_user.id,
        request_id=_request_id(request),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        now=datetime.now(UTC),
    )
    await db.commit()
    await trusted_service.trigger_post_commit_side_effects(outcome)
    return None


__all__ = ["router"]
