"""Project membership + invitation endpoints (T511 / T512).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module (Phase 10 Batch 2):

* ``POST   /{project_id}/invitations/{token}/accept``  — accept invite (T511,
  FR-053 / FR-054).
* ``DELETE /{project_id}/invitations/{token}``         — recipient self-decline
  (T512, FR-107 / FR-101c / FR-054 / FR-055).

The router still has **no prefix** here — the parent package
:mod:`echoroo.api.web_v1.projects` mounts every submodule under the
shared ``/projects`` prefix.

Listing / inviting / patching / removing members lives elsewhere in
Phase 3 (T120-T127); this Batch 2 increment adds only the
recipient-side accept + decline so US5 (Trusted accept) and the FR-107
self-decline contract can be exercised end-to-end.

Spec rationale:
    * **Token resolution** — the URL-borne signed token is the single
      authentication factor for the recipient. The HMAC-SHA-256 signature
      is verified first (FR-052); a tampered / expired signature returns
      410 immediately. Only after the signature passes do we look up the
      DB row by ``token_hash`` (the SHA-256 digest of the raw token).
    * **Email match (FR-054)** — the caller's primary email is matched
      against the invitation's ``email_hash`` using NFKC + casefold on
      both sides. Mismatch on the *accept* path returns 403 because the
      contract spec wants the caller to learn the invite is *for someone
      else*; mismatch on the *decline* path returns 404 (enumeration
      mitigation, FR-055 — a recipient who knows the URL token would
      otherwise leak via the 403/404 split).
    * **Idempotency (FR-053)** — the ``X-Idempotency-Key`` header is
      mandatory on accept. The Redis-backed dedupe lives in the
      invitation service; replays return the same row without writing a
      duplicate ProjectMember / ProjectTrustedUser. Faults on the
      idempotency cache surface as HTTP 503 (fail-closed).
    * **Decline state machine** — pending → DECLINED is the only allowed
      transition. Already DECLINED is idempotent (still 204). All
      terminal states (accepted / expired / revoked) return 410. The
      404 statuses for token-unknown / cross-account use the same
      response code as email-mismatch so an attacker cannot enumerate
      (FR-055).
    * **Audit + email** — the post-commit side effects fire AFTER the
      main TX commits (mirrors the license / restricted-config endpoints).
      Failures are WARNING-logged and never undo the persisted state.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Final, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy import select

from echoroo.api.web_v1.projects._audit import write_project_bff_audit_soft
from echoroo.api.web_v1.projects._core import ProjectServiceDep
from echoroo.core.actions import (
    PROJECT_MEMBER_INVITATION_ISSUE_ACTION,
    PROJECT_MEMBER_INVITATION_REVOKE_ACTION,
    PROJECT_MEMBER_INVITE_ACTION,
    PROJECT_MEMBER_LIST_ACTION,
    PROJECT_MEMBER_REMOVE_ACTION,
    PROJECT_MEMBER_UPDATE_ROLE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.core.redis import get_redis_connection
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
)
from echoroo.models.project import ProjectInvitation, ProjectMember
from echoroo.schemas.member_invitations import (
    BulkInvitationRequest,
    BulkInvitationResultItem,
    InvitationRevokeRequest,
    MemberInvitationIssueRequest,
    MemberInvitationIssueResponse,
    ProjectInvitationListItem,
    ProjectInvitationListResponse,
)
from echoroo.schemas.project import (
    ProjectMemberAddRequest,
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
)
from echoroo.services import invitation_service
from echoroo.services.email_verification_service import EmailVerificationService
from echoroo.services.invitation_service import (
    InvitationConflictError,
    InvitationCreateOutcome,
    InvitationEmailMismatchError,
    InvitationInfraUnavailableError,
    InvitationRateLimitError,
    InvitationStateError,
    InvitationTokenInvalidError,
    InvitationValidationError,
    accept_invitation,
    canonicalize_email,
    create_invitation,
    decline_invitation_by_recipient,
    revoke_invitation,
)

# ---------------------------------------------------------------------------
# spec/011 Step 8 / T263 — Per-issuer global invitation rate limit
# ---------------------------------------------------------------------------
#
# FR-011-114: every issuance counts against a per-issuer (user_id) sliding-
# window pair: 200/hour and 1000/day across all projects. Implementation
# reuses the Phase 17 A-6 Redis-backed INCR + EXPIRE pattern (same as the
# spec/011 invitation-public surface in :mod:`echoroo.api.web_v1.auth`).
# Fail-closed: a Redis fault is reported as ``rate_limited`` for the row
# under test so the issuer cannot bypass the cap by tripping the cache.
_BULK_INVITE_HOUR_LIMIT: Final[int] = 200
_BULK_INVITE_HOUR_WINDOW_SECONDS: Final[int] = 60 * 60
_BULK_INVITE_DAY_LIMIT: Final[int] = 1000
_BULK_INVITE_DAY_WINDOW_SECONDS: Final[int] = 24 * 60 * 60


def _per_issuer_hour_key(user_id: UUID) -> str:
    return f"invitation:per-issuer:hour:{user_id}"


def _per_issuer_day_key(user_id: UUID) -> str:
    return f"invitation:per-issuer:day:{user_id}"

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


def _json_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _enum_value(value: object) -> object:
    """Return a JSON-safe enum value while preserving None and plain objects."""
    if isinstance(value, Enum):
        return cast(object, value.value)
    return value


def _member_audit_snapshot(
    member: ProjectMember | ProjectMemberResponse,
    *,
    project_id: UUID,
) -> dict[str, Any]:
    role = getattr(member, "role", None)
    user_id = getattr(member, "user_id", None)
    if user_id is None:
        user_id = member.user.id
    return {
        "id": str(member.id),
        "project_id": str(project_id),
        "user_id": str(user_id),
        "role": _enum_value(role),
        "joined_at": _json_datetime(member.joined_at),
        "expires_at": _json_datetime(member.expires_at),
        "removed_at": _json_datetime(member.removed_at),
    }


async def _load_member_for_audit(
    db: DbSession,
    *,
    project_id: UUID,
    user_id: UUID,
) -> ProjectMember | None:
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# T037 / T043 / T044 — /{project_id}/members
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberResponse],
    summary="List project members (Web UI)",
    description=(
        "Cookie-session Web UI surface mirroring the programmatic member "
        "list route. Owner / Admin only via the canonical MANAGE_MEMBERS gate."
    ),
)
async def list_project_members(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> list[ProjectMemberResponse]:
    """List members through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.list_members(current_user.id, project_id)


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add project member (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic member "
        "add route. Owner / Admin only via the canonical MANAGE_MEMBERS gate."
    ),
    responses={
        202: {"description": "Invitation email queued (FR-055 async path)"},
    },
)
async def add_project_member(
    project_id: UUID,
    payload: ProjectMemberAddRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Add a member through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_INVITE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    member = await service.add_member(current_user.id, project_id, payload)
    await db.commit()
    await write_project_bff_audit_soft(
        actor_user_id=current_user.id,
        project_id=project_id,
        action=PROJECT_MEMBER_INVITE_ACTION.name,
        request=request,
        detail={
            "project_id": str(project_id),
            "user_id": str(member.user.id),
            "role": member.role.value,
        },
        before=None,
        after=_member_audit_snapshot(member, project_id=project_id),
    )
    return member


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
    summary="Update member role (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic member "
        "role update route. Owner / Admin only via MANAGE_MEMBERS."
    ),
)
async def update_project_member_role(
    project_id: UUID,
    user_id: UUID,
    payload: ProjectMemberUpdateRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Update a member role through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_UPDATE_ROLE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    before_member = await _load_member_for_audit(
        db,
        project_id=project_id,
        user_id=user_id,
    )
    before = (
        _member_audit_snapshot(before_member, project_id=project_id)
        if before_member is not None
        else None
    )
    member = await service.update_member_role(
        current_user.id,
        project_id,
        user_id,
        payload,
    )
    await db.commit()
    await write_project_bff_audit_soft(
        actor_user_id=current_user.id,
        project_id=project_id,
        action=PROJECT_MEMBER_UPDATE_ROLE_ACTION.name,
        request=request,
        detail={
            "project_id": str(project_id),
            "user_id": str(user_id),
            "old_role": before["role"] if before is not None else None,
            "new_role": member.role.value,
        },
        before=before,
        after=_member_audit_snapshot(member, project_id=project_id),
    )
    return member


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove project member (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic member "
        "remove route. Owner / Admin only via MANAGE_MEMBERS."
    ),
)
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> None:
    """Remove a member through the first-party BFF surface."""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_REMOVE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    before_member = await _load_member_for_audit(
        db,
        project_id=project_id,
        user_id=user_id,
    )
    before = (
        _member_audit_snapshot(before_member, project_id=project_id)
        if before_member is not None
        else None
    )
    await service.remove_member(current_user.id, project_id, user_id)
    await db.commit()
    await write_project_bff_audit_soft(
        actor_user_id=current_user.id,
        project_id=project_id,
        action=PROJECT_MEMBER_REMOVE_ACTION.name,
        request=request,
        detail={
            "project_id": str(project_id),
            "user_id": str(user_id),
            "old_role": before["role"] if before is not None else None,
        },
        before=before,
        after=None,
    )


# ---------------------------------------------------------------------------
# spec/011 T200 — POST /{project_id}/invitations  (FR-011-101..102)
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/invitations",
    response_model=MemberInvitationIssueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a Member-kind invitation (spec/011 FR-011-101)",
    description=(
        "Project Owner / Admin issues a one-shot Member invitation for an "
        "out-of-band email + role. The response carries the signed URL "
        "envelope under ``invitation_url`` — the value is never recoverable "
        "after this turn (FR-011-102; spec/006 FR-051 formally superseded "
        "by FR-011-103 for the trusted overlay, FR-011-102 for the member "
        "kind). ``Cache-Control: no-store, no-cache, must-revalidate, "
        "private`` is attached so a browser back / refresh does not replay "
        "the URL from bfcache. The audit row records only the invitation "
        "id and recipient ``email_hash`` — never the plain token (FR-011-102)."
    ),
    responses={
        409: {"description": "Pending invitation already exists for this email"},
        429: {"description": "Per-issuer rate limit exceeded (FR-056)"},
        503: {"description": "Rate-limit infrastructure unavailable"},
    },
)
async def issue_project_member_invitation(
    project_id: UUID,
    payload: MemberInvitationIssueRequest,
    request: Request,
    response: Response,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> MemberInvitationIssueResponse:
    """Issue a ``kind='member'`` invitation under ``project_id``.

    spec/011 FR-011-101: gated by
    :data:`echoroo.core.actions.PROJECT_MEMBER_INVITATION_ISSUE_ACTION`
    (project scope, ``MANAGE_MEMBERS`` permission). The service layer
    handles the FR-052 token shape, FR-056 rate-limit accounting, and the
    FR-011-103 plain-token confidentiality contract.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_INVITATION_ISSUE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # Map the contract's lower-case enum to the persisted ProjectMemberRole.
    try:
        role_enum = ProjectMemberRole(payload.role)
    except ValueError as exc:
        # Pydantic Literal validation would already reject this; the guard
        # below is defence in depth so a future schema relaxation cannot
        # silently downgrade the role assignment.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_INVALID_ROLE",
                "message": f"unknown role: {payload.role!r}",
            },
        ) from exc

    settings = get_settings()
    redis = await get_redis_connection()

    try:
        outcome = await create_invitation(
            db,
            project_id=project_id,
            kind=ProjectInvitationKind.MEMBER,
            email=payload.email,
            invited_by_id=current_user.id,
            hmac_secret=settings.web_session_secret,
            redis=redis,
            role=role_enum,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_INVITATION_INVALID",
                "message": str(exc),
            },
        ) from exc
    except InvitationConflictError as exc:
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
    expires_at_aware = invitation.expires_at
    if expires_at_aware.tzinfo is None:  # pragma: no cover — DB guarantees tz-aware
        expires_at_aware = expires_at_aware.replace(tzinfo=UTC)

    body = MemberInvitationIssueResponse(
        invitation_id=invitation.id,
        invitation_url=outcome.signed_token_envelope,
        expires_at=expires_at_aware,
        bound_email_hash=invitation.email_hash,
    )

    # FR-011-102: anti-bfcache + private cache directives. Mirrors the
    # Trusted endpoint precedent (FR-011-103) added by Step 6 / T207.
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )

    await db.commit()
    await invitation_service.trigger_post_commit_side_effects(outcome)
    return body


# ---------------------------------------------------------------------------
# spec/011 Step 8 (T260-T264) — POST /{project_id}/invitations/bulk
# ---------------------------------------------------------------------------


async def _check_and_consume_per_issuer_rate_limit(
    *,
    user_id: UUID,
) -> tuple[bool, str | None]:
    """Increment + verify the per-issuer hour + day Redis counters.

    Returns ``(allowed, error_message)``. ``allowed=False`` means EITHER
    cap was breached OR Redis is unreachable; the caller surfaces the row
    as ``status='rate_limited'`` (per-row failure semantics per
    FR-011-114 — the cap applies row-by-row inside the SAVEPOINT loop so
    a partial batch can still report some ``issued`` rows alongside
    ``rate_limited`` rows after the cap trips).

    Fail-closed on Redis fault: the helper returns ``(False, "...")`` so
    a Redis outage cannot be used to bypass the documented cap.
    """
    try:
        redis = await get_redis_connection()
    except Exception:  # noqa: BLE001 — fail-closed on any Redis fault
        logger.warning(
            "spec/011 per-issuer invitation rate-limit: Redis unavailable; "
            "failing closed (treating row as rate-limited)",
            exc_info=True,
        )
        return False, "rate-limit infrastructure unavailable"

    hour_key = _per_issuer_hour_key(user_id)
    day_key = _per_issuer_day_key(user_id)

    # Hour window first; if exhausted we still increment the day counter
    # consistently (each successful issuance MUST consume one unit of
    # both buckets, so increment them together at the same instant).
    try:
        hour_count = await redis.incr(hour_key)
        if hour_count == 1:
            await redis.expire(hour_key, _BULK_INVITE_HOUR_WINDOW_SECONDS)
    except Exception:  # noqa: BLE001 — fail-closed on any Redis fault
        logger.warning(
            "spec/011 per-issuer rate-limit: hour-key INCR failed",
            exc_info=True,
        )
        return False, "rate-limit infrastructure unavailable"
    if hour_count > _BULK_INVITE_HOUR_LIMIT:
        return False, (
            f"per-issuer hourly cap exceeded ({_BULK_INVITE_HOUR_LIMIT}/h)"
        )

    try:
        day_count = await redis.incr(day_key)
        if day_count == 1:
            await redis.expire(day_key, _BULK_INVITE_DAY_WINDOW_SECONDS)
    except Exception:  # noqa: BLE001 — fail-closed on any Redis fault
        logger.warning(
            "spec/011 per-issuer rate-limit: day-key INCR failed",
            exc_info=True,
        )
        return False, "rate-limit infrastructure unavailable"
    if day_count > _BULK_INVITE_DAY_LIMIT:
        return False, (
            f"per-issuer daily cap exceeded ({_BULK_INVITE_DAY_LIMIT}/day)"
        )

    return True, None


def _bulk_issued_result_item(
    *,
    email: str,
    outcome: InvitationCreateOutcome,
) -> BulkInvitationResultItem:
    """Shape a successful row's response (FR-011-113)."""
    expires_at = outcome.invitation.expires_at
    if expires_at.tzinfo is None:  # pragma: no cover — DB guarantees tz-aware
        expires_at = expires_at.replace(tzinfo=UTC)
    return BulkInvitationResultItem(
        email=email,
        status="issued",
        invitation_id=outcome.invitation.id,
        invitation_url=outcome.signed_token_envelope,
        expires_at=expires_at,
    )


@router.post(
    "/{project_id}/invitations/bulk",
    response_model=list[BulkInvitationResultItem],
    status_code=status.HTTP_207_MULTI_STATUS,
    summary="Bulk-issue Member-kind invitations (spec/011 FR-011-110)",
    description=(
        "Issue up to 50 Member-kind invitations under a single role in one "
        "atomic operator action. Each row's outcome is reported in the "
        "response array (FR-011-113) — `status='issued'` rows carry the "
        "one-shot signed URL under ``invitation_url`` (NOT recoverable "
        "after this turn), `status='duplicate_pending'` rows skip without "
        "rolling back the rest of the batch, `status='rate_limited'` rows "
        "report the FR-011-114 per-issuer cap hit, and `status='internal_"
        "error'` rows wrap any unexpected infra failure. Per-row SAVEPOINT "
        "semantics (NFR-011-008) guarantee a single-row failure never "
        "invalidates previously-issued rows in the same batch. "
        "Pre-validation (FR-011-111) rejects the WHOLE request with HTTP "
        "422 on a malformed email OR an in-list canonicalisation duplicate "
        "before any SAVEPOINT runs. The response carries "
        "``Cache-Control: no-store, no-cache, must-revalidate, private``."
    ),
    responses={
        207: {"description": "Multi-status; per-row outcomes in the response array"},
        422: {"description": "Whole-request validation failure (FR-011-111)"},
        503: {"description": "Rate-limit infrastructure unavailable"},
    },
)
async def bulk_issue_project_member_invitations(
    project_id: UUID,
    payload: BulkInvitationRequest,
    request: Request,
    response: Response,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> list[BulkInvitationResultItem]:
    """Bulk-issue Member invitations (FR-011-110..115).

    Implements the spec/011 Step 8 surface end-to-end:

    1. Auth + permission gate (``PROJECT_MEMBER_INVITATION_ISSUE_ACTION``).
    2. FR-011-111 atomic pre-validation: EmailStr already rejected
       malformed entries at the Pydantic layer; we re-check the in-list
       canonicalisation-duplicate guard before any DB write. A single
       in-list duplicate rejects the WHOLE request with HTTP 422 and
       does NOT consume per-issuer rate-limit quota.
    3. Per-row SAVEPOINT loop (NFR-011-008): each issuance lives inside
       its own ``session.begin_nested()`` so the unique-pending conflict
       on row N rolls back only row N's SAVEPOINT — successful rows
       persist when the outer ``session.commit()`` runs.
    4. Per-issuer rate-limit (FR-011-114) is consumed PER ROW inside the
       loop. The first row that trips the cap surfaces as
       ``status='rate_limited'``; the remaining rows in the batch ALSO
       fail-closed with ``status='rate_limited'`` (the cap trip is
       sticky for the rest of the batch — no further INCRs run).
    5. Audit emission (T264): each successful row writes one
       ``project.invitation.create`` audit entry via the existing
       post-commit emitter — same shape and SERIALIZABLE TX as the
       single-issue endpoint.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_INVITATION_ISSUE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # FR-011-111: in-list canonicalisation duplicate guard. The malformed-
    # email branch is already handled by Pydantic's EmailStr validator (it
    # surfaces as 422 before this handler runs).
    canonicalised: list[str] = [canonicalize_email(e) for e in payload.emails]
    if len(set(canonicalised)) != len(canonicalised):
        # Whole-request reject (FR-011-111). No SAVEPOINT runs, no
        # per-issuer rate-limit quota consumed.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_BULK_DUPLICATE_EMAILS",
                "message": (
                    "submitted email list contains duplicates after NFKC + "
                    "casefold canonicalisation"
                ),
            },
        )

    # Map the contract's lower-case enum to the persisted ProjectMemberRole.
    try:
        role_enum = ProjectMemberRole(payload.role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_INVALID_ROLE",
                "message": f"unknown role: {payload.role!r}",
            },
        ) from exc

    settings = get_settings()
    redis = await get_redis_connection()

    results: list[BulkInvitationResultItem] = []
    issued_outcomes: list[InvitationCreateOutcome] = []
    rate_limit_tripped = False

    for original_email in payload.emails:
        # Once the cap has tripped for this batch, every remaining row
        # short-circuits to ``rate_limited`` without consuming an extra
        # INCR. The first trip already incremented the counter; further
        # increments would over-charge the issuer's quota.
        if rate_limit_tripped:
            results.append(
                BulkInvitationResultItem(
                    email=original_email,
                    status="rate_limited",
                    error_message=(
                        "per-issuer rate-limit cap reached earlier in "
                        "this batch"
                    ),
                )
            )
            continue

        # FR-011-114 per-issuer cap check. Done BEFORE the SAVEPOINT so a
        # rate-limited row never even opens a nested TX. We still
        # consume one unit of both hour + day counters per attempt so
        # the cap meaning matches the spec (every attempted issuance
        # counts).
        allowed, rl_error = await _check_and_consume_per_issuer_rate_limit(
            user_id=current_user.id,
        )
        if not allowed:
            rate_limit_tripped = True
            results.append(
                BulkInvitationResultItem(
                    email=original_email,
                    status="rate_limited",
                    error_message=rl_error,
                )
            )
            continue

        try:
            async with db.begin_nested():
                outcome = await create_invitation(
                    db,
                    project_id=project_id,
                    kind=ProjectInvitationKind.MEMBER,
                    email=original_email,
                    invited_by_id=current_user.id,
                    hmac_secret=settings.web_session_secret,
                    redis=redis,
                    role=role_enum,
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                )
        except InvitationConflictError:
            # SAVEPOINT exit already rolled back this row's INSERT; the
            # outer TX retains the previously-issued rows intact.
            results.append(
                BulkInvitationResultItem(
                    email=original_email,
                    status="duplicate_pending",
                )
            )
            continue
        except InvitationRateLimitError as exc:
            # Per-project / per-actor FR-056 cap (NOT the same as the
            # per-issuer FR-011-114 cap above): surface as a per-row
            # ``rate_limited`` and keep going. NOTE: when the FR-056
            # check inside ``create_invitation`` trips it has ALREADY
            # incremented Redis counters that won't be undone; SAVEPOINT
            # rollback only affects the DB row.
            rate_limit_tripped = True
            results.append(
                BulkInvitationResultItem(
                    email=original_email,
                    status="rate_limited",
                    error_message=str(exc),
                )
            )
            continue
        except InvitationInfraUnavailableError as exc:
            # Redis fault inside ``create_invitation``: fail the row
            # closed (so the issuer cannot bypass FR-056) but keep the
            # batch flowing — the remaining rows will see the same
            # fault and report it consistently.
            results.append(
                BulkInvitationResultItem(
                    email=original_email,
                    status="rate_limited",
                    error_message=str(exc),
                )
            )
            continue
        except InvitationValidationError as exc:
            # Per-row validation fault (e.g. role / payload contract
            # mismatch). Surface as ``internal_error`` so the operator
            # can fix the request shape — the whole-batch validation
            # already passed by virtue of Pydantic + in-list dedupe.
            results.append(
                BulkInvitationResultItem(
                    email=original_email,
                    status="internal_error",
                    error_message=str(exc),
                )
            )
            continue
        except InvitationStateError as exc:
            results.append(
                BulkInvitationResultItem(
                    email=original_email,
                    status="internal_error",
                    error_message=str(exc),
                )
            )
            continue
        except Exception as exc:  # noqa: BLE001 — last-ditch row guard
            # The SAVEPOINT already rolled back this row's writes. Log
            # the unexpected exception for operator triage; surface as
            # ``internal_error`` so the rest of the batch can complete.
            logger.exception(
                "spec/011 bulk invitation: unexpected per-row failure",
                extra={"project_id": str(project_id), "email": original_email},
            )
            results.append(
                BulkInvitationResultItem(
                    email=original_email,
                    status="internal_error",
                    error_message=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        results.append(
            _bulk_issued_result_item(email=original_email, outcome=outcome),
        )
        issued_outcomes.append(outcome)

    # Commit the outer TX. Successful SAVEPOINT rows persist; failed rows
    # are already rolled back inside their nested context exit.
    await db.commit()

    # T264 — emit ``project.invitation.create`` per issued row.
    for issued_outcome in issued_outcomes:
        await invitation_service.trigger_post_commit_side_effects(
            issued_outcome,
        )

    # FR-011-110 / FR-011-113: anti-bfcache + private cache directives.
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )
    return results


# ---------------------------------------------------------------------------
# spec/011 Step 8 — POST /{project_id}/invitations/{invitation_id}/revoke
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/invitations/{invitation_id}/revoke",
    status_code=status.HTTP_200_OK,
    summary="Revoke a pending invitation (spec/011 Step 8)",
    description=(
        "Owner / Admin revoke of a pending Member-kind or Trusted-overlay "
        "invitation. Atomic UPDATE re-checks ``project_id`` AND "
        "``status='pending'``; any deviation (cross-project lookup, "
        "already-accepted, already-revoked, missing row) collapses to "
        "HTTP 404 with the same response shape so an attacker cannot "
        "enumerate invitation ids. The optional ``reason`` body field is "
        "free-form and runs through the Phase 17 A-13 PII detector — a "
        "submitted email / phone / national identifier yields HTTP 422 "
        "BEFORE the revoke commits. The post-commit emitter writes a "
        "``project.invitation.revoke`` audit row capturing the reason "
        "(but never the plain-text envelope)."
    ),
    responses={
        404: {
            "description": (
                "Invitation not found / wrong project / non-pending "
                "(uniform anti-enumeration shape)"
            )
        },
        422: {"description": "PII detected in reason field (Phase 17 A-13)"},
    },
)
async def revoke_project_invitation(
    project_id: UUID,
    invitation_id: UUID,
    request: Request,
    response: Response,
    current_user: OptionalCurrentUser,
    db: DbSession,
    payload: InvitationRevokeRequest | None = Body(default=None),
) -> dict[str, str]:
    """Owner / Admin revoke a pending invitation (spec/011 Step 8).

    Args:
        project_id: URL-bound project; the row's stored ``project_id``
            MUST match or the response collapses to 404.
        invitation_id: Target invitation row.
        payload: Optional body carrying a free-form ``reason``. The
            PII detector at the schema layer rejects PII patterns with
            HTTP 422 before this handler runs.

    Returns:
        ``{"invitation_id": ..., "status": "revoked", "revoked_at": ISO}``
        so the BFF can refresh the listing without an extra SELECT.

    Raises:
        404: Generic anti-enumeration response for missing / wrong-
            project / non-pending invitations.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_INVITATION_REVOKE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    reason: str | None = payload.reason if payload is not None else None

    try:
        outcome = await revoke_invitation(
            db,
            project_id=project_id,
            invitation_id=invitation_id,
            actor_user_id=current_user.id,
            reason=reason,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationStateError as exc:
        # FR-011-115 anti-enumeration: collapse every cause (missing row,
        # wrong project, already terminal) to the SAME 404 response.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invitation not found",
        ) from exc

    await db.commit()
    await invitation_service.trigger_post_commit_side_effects(outcome)

    # FR-011-115: revoke response carries no-store like the issue and
    # listing surfaces so a back / refresh does not replay the revoke
    # body (the body itself carries no secret, but the policy stays
    # uniform across the invitation surface).
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )

    revoked_at = outcome.invitation.revoked_at
    revoked_at_str = (
        revoked_at.isoformat() if revoked_at is not None else ""
    )
    return {
        "invitation_id": str(outcome.invitation.id),
        "status": outcome.invitation.status.value,
        "revoked_at": revoked_at_str,
    }


# ---------------------------------------------------------------------------
# spec/011 T201 — GET /{project_id}/invitations  (FR-011-108)
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/invitations",
    response_model=ProjectInvitationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List invitations for a project (spec/011 FR-011-108)",
    description=(
        "Unified listing of Member-kind and Trusted-overlay invitations "
        "for the project. Owner / Admin only (MANAGE_MEMBERS). The "
        "optional ``kind`` query filter narrows the result to a single "
        "kind; omit it to enumerate both. ``status`` likewise narrows by "
        "lifecycle state. The original token is **not** recoverable — "
        "admins must revoke + reissue to send a fresh URL."
    ),
)
async def list_project_invitations(
    project_id: UUID,
    request: Request,
    response: Response,
    current_user: OptionalCurrentUser,
    db: DbSession,
    kind: ProjectInvitationKind | None = Query(default=None),
    status_filter: ProjectInvitationStatus | None = Query(
        default=None, alias="status",
    ),
) -> ProjectInvitationListResponse:
    """Return the project's invitation rows (Owner / Admin).

    spec/011 T201 / FR-011-108: the listing returns BOTH member and
    trusted-overlay invitations so a single collaborator UI can render
    one mixed table. The endpoint is gated by
    :data:`PROJECT_MEMBER_LIST_ACTION` (``MANAGE_MEMBERS`` per the
    canonical matrix) so an enumeration audit row matches the rest of
    the membership surface.

    spec/011 step 7 R1 P1-2: the response carries
    ``Cache-Control: no-store, no-cache, must-revalidate, private`` to
    mirror the issue endpoint (``POST /{project_id}/invitations``). The
    listing exposes the ``bound_email_hash`` field and per-invitation
    status — both are admin-only data that MUST NOT be cached by an
    upstream proxy, replayed by browser bfcache, or stored in shared
    intermediate caches.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_MEMBER_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # P1-2: anti-cache directives — set BEFORE the SELECT so the header
    # is present regardless of whether the query short-circuits via an
    # empty result set.
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )

    stmt = (
        select(ProjectInvitation)
        .where(ProjectInvitation.project_id == project_id)
        .order_by(ProjectInvitation.created_at.desc())
    )
    if kind is not None:
        stmt = stmt.where(ProjectInvitation.kind == kind)
    if status_filter is not None:
        stmt = stmt.where(ProjectInvitation.status == status_filter)

    rows = (await db.execute(stmt)).scalars().all()

    items: list[ProjectInvitationListItem] = []
    for row in rows:
        items.append(
            ProjectInvitationListItem(
                id=row.id,
                kind=row.kind,
                role=row.role,
                granted_permissions=row.granted_permissions,
                status=row.status,
                bound_email=row.email,
                issued_by=row.invited_by_id,
                issued_at=row.created_at,
                expires_at=row.expires_at,
                accepted_at=row.accepted_at,
                revoked_at=row.revoked_at,
                declined_at=row.declined_at,
                ownership_transfer_on_accept=row.ownership_transfer_on_accept,
            )
        )
    return ProjectInvitationListResponse(items=items)


# ---------------------------------------------------------------------------
# T511 — POST /{project_id}/invitations/{token}/accept
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/invitations/{token}/accept",
    status_code=status.HTTP_200_OK,
    summary="Accept an invitation (FR-053 / FR-054)",
    description=(
        "Recipient-driven accept. The signed URL token authenticates the "
        "URL itself; the caller's email must match the invitation's stored "
        "hash (FR-054). The ``X-Idempotency-Key`` header is required: "
        "replays under the same key return the same outcome (200), "
        "different tokens under the same key return 409, and any cache "
        "fault surfaces as 503."
    ),
    responses={
        403: {"description": "Caller email does not match invitation hash (FR-054)"},
        410: {"description": "Invitation expired or revoked"},
    },
)
async def accept_project_invitation(
    project_id: UUID,
    token: str,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
) -> dict[str, str]:
    """Consume a pending invitation under ``project_id``.

    Args:
        project_id: Path-bound parent project — used by the audit row;
            the row's authority is the token, not the project_id, but
            we keep the project_id in the URL for clarity and so future
            tightening can verify it matches the invitation row.
        token: Signed ``{raw}.{exp}.{mac}`` envelope from the email URL.
        idempotency_key: ``X-Idempotency-Key`` header — see FR-053.

    Returns:
        ``{"kind": "member" | "trusted", "project_id": ...}`` so the
        Web UI can route the freshly-accepted member to either the
        project landing page (Member) or the Trusted-overlay aware
        surface.

    Raises:
        401: Caller is unauthenticated (no Bearer / cookie principal).
        403: ``ERR_EMAIL_MISMATCH`` per FR-054 (accept surface).
        404: Token unknown / different project_id mismatch — FR-055
            keeps the response uniform so an attacker cannot enumerate
            valid tokens.
        409: ``X-Idempotency-Key`` reused with a different token, OR
            an active membership already exists for this user without
            a matching idempotency record (see invitation_service docs).
        410: Token expired / invitation in terminal state.
        503: Idempotency cache (Redis) unreachable; fail-closed.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ERR_IDEMPOTENCY_KEY_REQUIRED",
                "message": "X-Idempotency-Key header is required (FR-053).",
            },
        )

    settings = get_settings()
    redis = await get_redis_connection()

    try:
        outcome = await accept_invitation(
            db,
            signed_token=token,
            current_user_id=current_user.id,
            current_user_email=current_user.email,
            hmac_secret=settings.web_session_secret,
            redis=redis,
            idempotency_key=idempotency_key,
            project_id_scope=project_id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationTokenInvalidError as exc:
        # Tampered / expired signature OR token_hash unknown. Use 404 for
        # token-not-found (FR-055 enumeration mitigation) and 410 for
        # expired / structurally-invalid signatures.
        msg = str(exc).lower()
        if "not found" in msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "ERR_INVITATION_TOKEN_INVALID",
                "message": str(exc),
            },
        ) from exc
    except InvitationEmailMismatchError as exc:
        # FR-054: 403 on the accept path so the recipient learns the
        # invite is for someone else and can ask for re-issue. The
        # decline path uses 404 instead to keep the FR-055 contract.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ERR_EMAIL_MISMATCH",
                "message": str(exc),
            },
        ) from exc
    except InvitationStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "ERR_INVITATION_TERMINAL_STATE",
                "message": str(exc),
            },
        ) from exc
    except InvitationConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_INVITATION_CONFLICT",
                "message": str(exc),
            },
        ) from exc
    except InvitationInfraUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    invitation = outcome.invitation
    response_payload: dict[str, str] = {
        "kind": invitation.kind.value,
        "project_id": str(invitation.project_id),
    }
    if invitation.kind is ProjectInvitationKind.MEMBER and outcome.member is not None:
        response_payload["member_id"] = str(outcome.member.id)
    elif (
        invitation.kind is ProjectInvitationKind.TRUSTED
        and outcome.trusted_user is not None
    ):
        response_payload["trusted_user_id"] = str(outcome.trusted_user.id)

    await EmailVerificationService(db).mark_verified_from_same_email_invitation(
        user=current_user,
        invitation_email=invitation.email,
        accepted_at=invitation.accepted_at or datetime.now(UTC),
    )
    await db.commit()
    await invitation_service.trigger_post_commit_side_effects(outcome)
    return response_payload


# ---------------------------------------------------------------------------
# T512 — DELETE /{project_id}/invitations/{token}
# ---------------------------------------------------------------------------


@router.delete(
    "/{project_id}/invitations/{token}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Recipient-driven self-decline (FR-107)",
    description=(
        "Pending → DECLINED state transition initiated by the recipient. "
        "Idempotent (already-DECLINED → 204). Terminal states "
        "(accepted / expired / revoked) → 410. Token unknown / cross-account / "
        "email mismatch all collapse to 404 per FR-055 enumeration "
        "mitigation. Owner / Admin revocation lives on a separate "
        "endpoint (future FR)."
    ),
    responses={
        404: {"description": "Invitation not found / cross-account (FR-055 enumeration mitigation)"},
        410: {"description": "Invitation already accepted / expired / revoked"},
    },
)
async def decline_project_invitation(
    project_id: UUID,
    token: str,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> None:
    """Recipient-driven self-decline.

    Args:
        project_id: Path-bound parent project — used by the audit row.
        token: Signed ``{raw}.{exp}.{mac}`` envelope.

    Raises:
        401: Caller is unauthenticated.
        404: Token unknown / cross-account mismatch / email mismatch
            (uniform per FR-055).
        410: accept / expired / revoked terminal state.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    settings = get_settings()

    # Phase 10 Batch 2 Round 2 fix (致命 3): the URL path's ``project_id``
    # is now passed into the service so a token whose invitation row
    # belongs to a *different* project surfaces uniformly as 404 (FR-055
    # enumeration mitigation). Previously the variable was discarded
    # which let an attacker who guessed a project_id confirm or deny
    # the existence of an arbitrary token under that project's URL.
    try:
        outcome = await decline_invitation_by_recipient(
            db,
            signed_token=token,
            current_user_id=current_user.id,
            current_user_email=current_user.email,
            hmac_secret=settings.web_session_secret,
            project_id_scope=project_id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except InvitationTokenInvalidError as exc:
        # FR-055: token unknown or signature failure both surface as 404
        # so the response shape is identical to the email-mismatch path.
        # An expired token is also 404 here (vs. 410 on the accept path)
        # because the spec sets the decline route to a uniform 404 for
        # *all* "cannot resolve / cannot match" outcomes, while terminal
        # states (accepted / expired / revoked) on a *valid, matched*
        # invitation surface as 410. The state-machine 410 path is taken
        # in the `InvitationStateError` branch below.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invitation not found",
        ) from exc
    except InvitationEmailMismatchError as exc:
        # FR-055: collapse to 404 on the decline surface so the caller
        # cannot infer that a *matching* token exists for someone else.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="invitation not found",
        ) from exc
    except InvitationStateError as exc:
        # accepted / expired / revoked → 410 (terminal state, decline
        # is no longer possible).
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "error": "ERR_INVITATION_TERMINAL_STATE",
                "message": str(exc),
            },
        ) from exc

    await db.commit()
    await invitation_service.trigger_post_commit_side_effects(outcome)
    return None


__all__ = ["router"]
