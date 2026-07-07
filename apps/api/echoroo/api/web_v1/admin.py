"""Superuser admin endpoints (Phase 11 / T630, FR-034 / FR-036 / FR-111).

Contract: ``specs/006-permissions-redesign/contracts/admin.yaml``.

Path operations owned by this module (mounted under ``/web-api/v1/admin``):

* ``POST /projects/{project_id}/taxon-overrides/{override_id}/approve``
  — Flip a pending looser override to ``approval_status='applied'`` (FR-034).
* ``POST /projects/{project_id}/taxon-overrides/{override_id}/reject``
  — Mark a pending looser override as rejected with a free-form reason.
* ``POST /iucn/force-resync``
  — Enqueue the weekly :func:`sync_iucn_red_list` Celery task on demand
    (FR-036). Used when the scheduled batch is broken or an emergency
    sensitivity update needs to land before the next Sunday tick.

Authentication and transport
----------------------------
The production middleware chain (CSRF + AuthRouter + IP allowlist for
superusers) gates the cookie session before any handler in this module
sees the request. The handler-level ``is_allowed`` / ``gate_action``
calls are the second line of defence: they ensure the caller really is
flagged ``is_superuser=True`` AND, for the project-scope mutations, that
the action name appears in :data:`SUPERUSER_PROJECT_SCOPE_ALLOWLIST`
(FR-008b) so non-superuser regressions fail closed.

Audit
-----
Service-level helpers
(:mod:`echoroo.services.superuser_approval_service`) write the
project-scope rows for approve / reject. The endpoints additionally
write a ``platform_audit_log`` entry through :class:`AuditLogService` so
the superuser dashboard can list "every admin action this superuser took
this week" without joining across the two tables. ``force_resync`` is
platform-only and writes a single platform row.

Phase 11 / T630 scope
---------------------
This module only delivers the looser-override + IUCN force-resync trio
called out by T630. Archive / restore (T702) and superuser CRUD (T610+
follow-ups) extend the same router in later batches.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError

from echoroo.core.actions import (
    ADMIN_USER_RESET_PASSWORD_ACTION,
    PLATFORM_IUCN_FORCE_RESYNC_ACTION,
    PLATFORM_TAXON_SEED_BIRDNET_ACTION,
    PLATFORM_TAXON_SYNC_VERNACULAR_ACTION,
    PLATFORM_UPLOAD_RECOVER_ACTION,
    PROJECT_ARCHIVE_ACTION,
    PROJECT_RESTORE_ACTION,
    PROJECT_TAXON_OVERRIDE_APPROVE_ACTION,
    PROJECT_TAXON_OVERRIDE_REJECT_ACTION,
    SUPERUSER_ADD_ACTION,
    SUPERUSER_APPROVAL_REQUEST_LIST_ACTION,
    SUPERUSER_APPROVE_REQUEST_ACTION,
    SUPERUSER_BREAK_GLASS_ENTER_ACTION,
    SUPERUSER_BREAK_GLASS_STATUS_ACTION,
    SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION,
    SUPERUSER_LIST_ACTION,
    SUPERUSER_REJECT_REQUEST_ACTION,
    SUPERUSER_REVOKE_ACTION,
)
from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.permissions import Action, gate_action, is_allowed, load_project_or_404
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.middleware.step_up import require_step_up_token
from echoroo.models.enums import ProjectStatus, UploadSessionStatus
from echoroo.models.project import ProjectMember
from echoroo.models.superuser import Superuser
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.models.upload import UploadSession
from echoroo.models.user import User
from echoroo.repositories.upload import UploadSessionRepository
from echoroo.schemas.admin import (
    AdminPasswordResetBody,
    AdminPasswordResetResponse,
    ArchiveRequest,
    ArchiveResponse,
    IucnForceResyncResponse,
    ResetTwoFactorRequest,
    RestoreRequest,
    RestoreResponse,
    StuckUploadSessionListResponse,
    StuckUploadSessionSummary,
    SuperuserActionResponse,
    SuperuserAddRequest,
    SuperuserApprovalRequestListResponse,
    SuperuserApprovalRequestSummary,
    SuperuserBreakGlassEnterRequest,
    SuperuserBreakGlassStatusResponse,
    SuperuserIpAllowlistResponse,
    SuperuserIpAllowlistUpdateRequest,
    SuperuserListResponse,
    SuperuserRejectRequest,
    SuperuserSummary,
    TaskDispatchResponse,
    TaxonOverrideRejectRequest,
    TaxonOverrideResponse,
    TaxonSyncVernacularRequest,
)
from echoroo.services import admin_password_reset, superuser_service
from echoroo.services.audit_service import AuditLogService
from echoroo.services.outbox_service import enqueue as outbox_enqueue
from echoroo.services.step_up_token_service import (
    SCOPE_ADMIN_DESTRUCTIVE,
    SCOPE_ADMIN_RECOVERY,
)
from echoroo.services.superuser_approval_service import (
    TaxonOverrideDecisionOutcome,
    approve_taxon_override,
    reject_taxon_override,
    trigger_decision_post_commit_audit,
)
from echoroo.services.superuser_service import (
    AlreadySuperuserError,
    ApprovalRequestNotFoundError,
    ApprovalRequestStateError,
    DuplicateApprovalError,
    LastSuperuserProtectionError,
    NotSuperuserError,
    SuperuserServiceError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Approval-request payload redaction (Phase 15 Batch 5a R2 — Codex Major 1)
# ---------------------------------------------------------------------------
#
# ``superuser_approval_requests.detail`` and ``.approvals`` are JSONB
# columns owned by :mod:`superuser_service`. The ``superuser.add`` ticket
# embeds the operator-supplied ``webauthn_credentials`` raw payload into
# the detail so the apply step can hand it to ``add_superuser_apply``
# without an extra round trip. That payload includes WebAuthn public key
# bytes, attestation objects, and other fields that the operator
# dashboard does not need and that absolutely must not leak through the
# admin list endpoint to ANY caller — even another superuser. The two
# helpers below apply a fail-closed allowlist: any field not in the
# explicit set is dropped silently. New service-side fields will not
# leak through this surface unless the allowlist is updated.
_DETAIL_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        # superuser.add tickets
        "target_user_id",
        "target_email_hash",
        "target_role",
        "allowed_ip_cidrs",
        # superuser.revoke tickets
        "target_superuser_id",
        "revoke_reason",
        # backup_code_reset / generic
        "support_ticket_id",
        "confirmed_factors",
        "reason",
        # looser override tickets (cross-cutting)
        "override_id",
        "project_id",
        "taxon_id",
        "direction",
        "sensitivity_h3_res",
    }
)
_APPROVAL_ENTRY_ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "superuser_id",
        "approved_at",
        "decided_at",
        "decision",
        "rejected_reason",
        "reason",
    }
)


def _redact_approval_detail(
    detail: dict[str, object] | None,
) -> dict[str, object] | None:
    """Return ``detail`` with only allowlisted keys (FR-111 leak guard)."""
    if detail is None:
        return None
    return {k: v for k, v in detail.items() if k in _DETAIL_ALLOWED_KEYS}


def _redact_approvals_list(
    approvals: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Strip non-allowlisted fields from each approval-history entry."""
    return [
        {k: v for k, v in entry.items() if k in _APPROVAL_ENTRY_ALLOWED_KEYS}
        for entry in approvals
    ]


# ---------------------------------------------------------------------------
# Helpers (mirrors ``web_v1/trusted.py`` / ``web_v1/audit.py`` so audit
# rows produced by this module carry the same actor / request envelope).
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


def _require_superuser_id(current_user: User | None) -> UUID:
    """Return ``current_user._superuser_id`` or 403 if absent.

    Phase 13 P1 R3 (Codex P1 R2 follow-up): the ``approve_taxon_override``
    / ``reject_taxon_override`` endpoints used to write
    ``current_user.id`` (the user's id) into ``approved_by_id`` —
    a ``superusers.id`` FK — which would always raise an integrity
    error in production. The auth dependency stamper now decorates
    every authenticated user with ``_superuser_id`` (active
    ``superusers.id``) when they hold a current superuser row. This
    helper short-circuits to 403 if the stamp is missing so callers
    never confuse the two ID spaces.
    """
    superuser_id: UUID | None = getattr(current_user, "_superuser_id", None)
    if superuser_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ERR_NOT_SUPERUSER",
                "message": (
                    "caller is not stamped as an active superuser; "
                    "_require_authenticated_superuser must run first"
                ),
            },
        )
    return superuser_id


async def _require_authenticated_superuser(
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> None:
    """Verify the caller is an authenticated **superuser** (Phase 12 R1 C1 fix).

    The previous implementation (Phase 11 / Phase 12 Batch 1) only
    checked authentication and relied on the downstream
    :func:`is_allowed` / :func:`gate_action` allowlist branch to gate
    superuser-only actions. The ``project.archive`` /
    ``project.restore`` actions, however, declared
    ``required_permission=Permission.EDIT_PROJECT`` (Owner-only matrix
    cell), so an Owner who happened to land on this endpoint passed
    through gate_action() without ever proving superuser status — a
    privilege escalation against FR-061.

    The fix (Phase 12 R2 致命 C1): consult the persisted ``superusers``
    table directly — that table is the SINGLE SOURCE OF TRUTH for
    superuser status (FR-112a). The User ORM model deliberately has NO
    persisted ``is_superuser`` column; the ``OptionalCurrentUser``
    dependency stamps a transient ``is_superuser`` attribute via the
    same ``superusers`` probe so downstream gates can read it without
    re-issuing SQL. We re-probe here defensively in case a custom
    auth path bypassed the stamper.

    Production transport (CSRF + AuthRouter + IP allowlist + WebAuthn)
    is already enforced upstream by the middleware chain; this helper
    is the application-layer second line of defence.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # The ``superusers`` table is the canonical source of truth: a row
    # with ``revoked_at IS NULL`` means the user is currently a
    # superuser. Any other signal (transient stamps, session claims) is
    # advisory only. Mirrors the raw-SQL probe used by
    # ``api/web_v1/auth.py::_is_superuser`` so the two surfaces stay in
    # lockstep.
    probe = await db.execute(
        sa.text(
            "SELECT 1 FROM superusers "
            "WHERE user_id = :uid AND revoked_at IS NULL LIMIT 1"
        ),
        {"uid": current_user.id},
    )
    if probe.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ERR_NOT_SUPERUSER",
                "message": (
                    "user is not registered as an active superuser; the "
                    "session claim is stale or revoked"
                ),
            },
        )

    # Sync the transient stamp so a downstream ``_is_superuser`` check
    # (e.g. inside ``is_allowed`` Step 0c) sees the verified status even
    # if the auth dependency stamper missed this user.
    current_user.is_superuser = True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# POST /admin/projects/{project_id}/taxon-overrides/{override_id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/taxon-overrides/{override_id}/approve",
    response_model=TaxonOverrideResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a pending looser taxon override (Superuser)",
    description=(
        "Flip a ``pending_superuser_approval`` override to ``applied`` "
        "(FR-034). The matching ``superuser_approval_requests`` row is "
        "transitioned to ``status='approved'`` in the same transaction. "
        "Idempotency: a 409 is returned if the override is already in a "
        "terminal state (``applied`` / ``rejected``)."
    ),
)
async def approve_looser_override(
    project_id: UUID,
    override_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> TaxonOverrideResponse:
    """Approve a pending looser override on behalf of a superuser."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None  # narrowed by the helper above

    # Project-scope gate. Non-superusers fail the ``EDIT_PROJECT`` check;
    # superusers short-circuit through SUPERUSER_PROJECT_SCOPE_ALLOWLIST
    # (FR-008b) — the action name MUST stay in sync with the allowlist
    # entry registered in ``core/permissions.py``.
    await gate_action(
        action=PROJECT_TAXON_OVERRIDE_APPROVE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    decision_outcome: TaxonOverrideDecisionOutcome
    try:
        decision_outcome = await approve_taxon_override(
            db,
            override_id=override_id,
            approver_superuser_id=_require_superuser_id(current_user),
            actor_user_id=current_user.id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except ValueError as exc:
        # Service raises ValueError for: missing override, wrong direction,
        # or non-pending status. The first is a 404, the others a 409.
        message = str(exc)
        if "not found" in message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "ERR_OVERRIDE_NOT_FOUND",
                    "message": message,
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_OVERRIDE_STATE_INVALID",
                "message": message,
            },
        ) from exc
    except IntegrityError as exc:
        # The partial unique index ``ux_taxon_overrides_applied_unique``
        # prevents two ``applied`` rows for the same (project, taxon)
        # pair. A racing approve will trip this — surface a 409 so the
        # operator UI can refresh and re-evaluate.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_OVERRIDE_CONFLICT",
                "message": (
                    "Another applied override exists for this (project, "
                    "taxon) pair; refresh the queue and retry."
                ),
            },
        ) from exc

    override = decision_outcome.override

    # Cross-check the URL-level project_id against the row we just
    # mutated — the override id is globally unique so the path's
    # project_id is informational, but a mismatch is a sign the operator
    # deep-linked from a stale UI; reject loudly rather than silently
    # mutate a row outside the URL's project scope.
    if override.project_id != project_id:
        # The service has already mutated the row; rollback to undo it.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ERR_OVERRIDE_NOT_FOUND",
                "message": (
                    "Override does not belong to the supplied project."
                ),
            },
        )

    # Snapshot the response shape BEFORE commit — attribute expiration
    # post-commit can blank the row out of the ORM identity map.
    response = TaxonOverrideResponse.model_validate(override)

    # Phase 13 P1 R3 follow-up (2026-04-28): audit rows are deferred to
    # the post-commit hook below. Writing them in the request-scoped
    # ``db`` session would violate the audit_service contract because
    # PostgreSQL rejects ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE``
    # on a connection that has already issued SQL (and ``approve_taxon_override``
    # has done plenty: SELECT, UPDATE, _close_approval_request).
    await db.commit()

    await trigger_decision_post_commit_audit(decision_outcome)

    return response


# ---------------------------------------------------------------------------
# POST /admin/projects/{project_id}/taxon-overrides/{override_id}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/taxon-overrides/{override_id}/reject",
    response_model=TaxonOverrideResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject a pending looser taxon override (Superuser)",
    description=(
        "Move a ``pending_superuser_approval`` override to ``rejected`` "
        "with a mandatory free-form reason (FR-034). The override row "
        "stays in the table so historical inspection works; the masking "
        "pipeline ignores ``rejected`` rows via the partial unique index."
    ),
)
async def reject_looser_override(
    project_id: UUID,
    override_id: UUID,
    payload: TaxonOverrideRejectRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> TaxonOverrideResponse:
    """Reject a pending looser override and persist the operator's reason."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None

    await gate_action(
        action=PROJECT_TAXON_OVERRIDE_REJECT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    decision_outcome: TaxonOverrideDecisionOutcome
    try:
        decision_outcome = await reject_taxon_override(
            db,
            override_id=override_id,
            approver_superuser_id=_require_superuser_id(current_user),
            actor_user_id=current_user.id,
            rejected_reason=payload.reason,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "ERR_OVERRIDE_NOT_FOUND",
                    "message": message,
                },
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_OVERRIDE_STATE_INVALID",
                "message": message,
            },
        ) from exc

    override = decision_outcome.override

    if override.project_id != project_id:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ERR_OVERRIDE_NOT_FOUND",
                "message": "Override does not belong to the supplied project.",
            },
        )

    response = TaxonOverrideResponse.model_validate(override)

    # Phase 13 P1 R3 follow-up (2026-04-28): defer audit rows to the
    # post-commit hook. See the matching note in
    # ``approve_looser_override`` above for the rationale.
    await db.commit()

    await trigger_decision_post_commit_audit(decision_outcome)

    return response


# ---------------------------------------------------------------------------
# POST /admin/iucn/force-resync
# ---------------------------------------------------------------------------


@router.post(
    "/iucn/force-resync",
    response_model=IucnForceResyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Force IUCN Red List resync (Superuser)",
    description=(
        "Fire-and-forget Celery dispatch of the weekly "
        "``sync_iucn_red_list`` task (FR-036). The task records its own "
        "``IucnSyncAttempt`` row + sanity-check rejection, so the "
        "endpoint only surfaces the queued task id. The action is "
        "platform-scope (no project_id) and writes a ``platform_audit_log`` "
        "entry."
    ),
)
async def force_iucn_resync(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> IucnForceResyncResponse:
    """Enqueue the IUCN sync task and return the Celery task id."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None

    # Platform-scope gate (Step 0a in :func:`is_allowed`): only superusers
    # pass; we never load a project row.
    allowed, _ = is_allowed(
        action=PLATFORM_IUCN_FORCE_RESYNC_ACTION,
        user=current_user,
        project=None,
        request=request,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="IUCN force resync is restricted to superusers",
        )

    # Local import: pulling in the Celery worker module at import time
    # would force the FastAPI process to load the worker dependency tree
    # (audio + ML libs) which violates the API container's slim image
    # contract. The lazy import keeps the cold start fast.
    from echoroo.workers.iucn_sync import sync_iucn_red_list

    async_result = sync_iucn_red_list.delay()
    enqueued_at = datetime.now(UTC)

    # Phase 13 P1 R3 follow-up (2026-04-28): the request-scoped ``db``
    # session has already issued ``_require_authenticated_superuser``'s
    # ``SELECT 1 FROM superusers`` probe, so PostgreSQL would reject the
    # ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` upgrade that
    # :class:`AuditLogService` issues as its first statement. Mirror the
    # archive / restore endpoints below by writing the platform audit row
    # in a fresh :class:`AsyncSessionLocal` after the main TX commits.
    await db.commit()

    try:
        async with AsyncSessionLocal() as platform_audit_session:
            try:
                await AuditLogService(
                    platform_audit_session
                ).write_platform_event(
                    actor_user_id=current_user.id,
                    action="platform.iucn.force_resync",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail={
                        "task_id": async_result.id,
                        "enqueued_at": enqueued_at.isoformat(),
                    },
                )
                await platform_audit_session.commit()
            except Exception:
                await platform_audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — soft alert; never blocks the dispatch
        logger.warning(
            "platform.iucn.force_resync audit write failed (FR-089 soft alert): "
            "actor=%s task_id=%s error=%r",
            current_user.id,
            async_result.id,
            exc,
        )

    return IucnForceResyncResponse(
        task_id=async_result.id,
        enqueued_at=enqueued_at,
    )


# ---------------------------------------------------------------------------
# Upload-session recovery (platform-scope, superuser-only)
# ---------------------------------------------------------------------------
#
# Operators occasionally hit an upload session that wedges mid-pipeline
# (worker crash, lost message, stuck import). These two endpoints let a
# superuser inspect the wedged sessions and force-fail a specific one so
# the affected user can safely re-upload. There is deliberately NO
# re-dispatch / retry endpoint: re-running a partially-applied import is
# unsafe, so force-fail + user re-upload is the sanctioned recovery path.

# Terminal states a session can never leave; a force-fail on one of these
# is a no-op that would only hide a real state bug, so we reject it (409).
_TERMINAL_UPLOAD_STATUSES = (
    UploadSessionStatus.IMPORTED,
    UploadSessionStatus.FAILED,
)

_UPLOAD_FORCE_FAIL_ERROR = "Force-failed by admin (recovery)"


def _stuck_session_summary(session: UploadSession) -> StuckUploadSessionSummary:
    """Project an :class:`UploadSession` (with ``dataset`` eager-loaded).

    ``project_id`` is resolved via the parent dataset — the session row has
    no direct project FK.
    """
    return StuckUploadSessionSummary(
        id=session.id,
        dataset_id=session.dataset_id,
        project_id=session.dataset.project_id,
        status=session.status.value,
        error=session.error,
        total_files=session.total_files,
        validated_files=session.validated_files,
        imported_files=session.imported_files,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.get(
    "/uploads/stuck",
    response_model=StuckUploadSessionListResponse,
    status_code=status.HTTP_200_OK,
    summary="List stuck upload sessions (Superuser)",
    description=(
        "Return upload sessions stuck in a non-terminal, mid-processing "
        "state (UPLOADED / VALIDATING / VALIDATED / IMPORTING), oldest "
        "first, so an operator can spot and recover wedged imports. Pass "
        "``older_than_seconds`` to restrict the result to sessions idle for "
        "at least that long. Platform-scope (no project_id); writes no "
        "audit row (read-only)."
    ),
)
async def list_stuck_uploads(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    older_than_seconds: int | None = Query(
        None,
        ge=0,
        description=(
            "Only return sessions whose last update is older than this many "
            "seconds. Omit to return every non-terminal session."
        ),
    ),
    limit: int = Query(100, ge=1, le=500, description="Page size"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
) -> StuckUploadSessionListResponse:
    """List non-terminal stuck upload sessions for admin recovery."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None

    allowed, _ = is_allowed(
        action=PLATFORM_UPLOAD_RECOVER_ACTION,
        user=current_user,
        project=None,
        request=request,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload recovery is restricted to superusers",
        )

    repo = UploadSessionRepository(db)
    sessions = await repo.list_stuck_sessions(
        older_than_seconds=older_than_seconds,
        limit=limit,
        offset=offset,
    )
    return StuckUploadSessionListResponse(
        items=[_stuck_session_summary(s) for s in sessions],
    )


@router.post(
    "/uploads/{session_id}/fail",
    response_model=StuckUploadSessionSummary,
    status_code=status.HTTP_200_OK,
    summary="Force-fail a stuck upload session (Superuser)",
    description=(
        "Force-mark a wedged upload session as FAILED so the user can "
        "safely re-upload. Rejects sessions that are already terminal "
        "(IMPORTED / FAILED) with 409, and unknown ids with 404. "
        "Platform-scope; writes a ``platform_audit_log`` entry."
    ),
)
async def force_fail_upload(
    session_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> StuckUploadSessionSummary:
    """Force a stuck upload session into the FAILED terminal state."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None

    allowed, _ = is_allowed(
        action=PLATFORM_UPLOAD_RECOVER_ACTION,
        user=current_user,
        project=None,
        request=request,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload recovery is restricted to superusers",
        )

    repo = UploadSessionRepository(db)
    session = await repo.get_by_id(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found",
        )
    if session.status in _TERMINAL_UPLOAD_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Upload session is already terminal (status={session.status.value}) "
                "and cannot be force-failed"
            ),
        )

    # Capture the status BEFORE the UPDATE: SQLAlchemy's ORM-enabled UPDATE
    # mutates the identity-mapped ``session`` instance in place, so reading
    # ``session.status`` after ``update_status`` would already return FAILED.
    previous_status = session.status.value

    # Compare-and-set on the status we read: if the background import task
    # transitioned the session (e.g. IMPORTING -> IMPORTED) between our read
    # and this write, the guard matches 0 rows and we must NOT force-fail a
    # legitimately completed import.
    updated_ok = await repo.update_status(
        session_id,
        UploadSessionStatus.FAILED,
        error=_UPLOAD_FORCE_FAIL_ERROR,
        expected_status=session.status,
    )
    if not updated_ok:
        # Re-fetch to report the status the session raced into.
        current = await repo.get_by_id(session_id)
        current_status = current.status.value if current is not None else "unknown"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Upload session transitioned concurrently and was not "
                f"force-failed; now {current_status}"
            ),
        )

    # Re-read so the response reflects the persisted FAILED state + error,
    # with the dataset relationship loaded for project_id resolution.
    updated = await repo.get_by_id(session_id)
    assert updated is not None
    response = _stuck_session_summary(updated)

    # Mirror force_iucn_resync (Phase 13 P1 R3): the request-scoped session
    # already ran the superuser probe, so the SERIALIZABLE audit write must
    # ride a fresh AsyncSessionLocal after the main TX commits.
    await db.commit()

    try:
        async with AsyncSessionLocal() as platform_audit_session:
            try:
                await AuditLogService(platform_audit_session).write_platform_event(
                    actor_user_id=current_user.id,
                    action="platform.upload.recover",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail={
                        "session_id": str(session_id),
                        "dataset_id": str(response.dataset_id),
                        "project_id": str(response.project_id),
                        "previous_status": previous_status,
                    },
                )
                await platform_audit_session.commit()
            except Exception:
                await platform_audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — soft alert; never blocks recovery
        logger.warning(
            "platform.upload.recover audit write failed (FR-089 soft alert): "
            "actor=%s session_id=%s error=%r",
            current_user.id,
            session_id,
            exc,
        )

    return response


# ---------------------------------------------------------------------------
# POST /admin/taxon/seed-birdnet
# ---------------------------------------------------------------------------


@router.post(
    "/taxon/seed-birdnet",
    response_model=TaskDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Seed BirdNET taxa (Superuser)",
    description=(
        "Fire-and-forget Celery dispatch of the idempotent "
        "``seed_birdnet_taxa`` task. The task inserts any BirdNET species "
        "rows missing from the ``taxa`` table; the endpoint only surfaces "
        "the queued task id. The action is platform-scope (no project_id) "
        "and writes a ``platform_audit_log`` entry."
    ),
)
async def seed_birdnet_taxa(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> TaskDispatchResponse:
    """Enqueue the BirdNET taxa seeding task and return the Celery task id."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None

    # Platform-scope gate (Step 0a in :func:`is_allowed`): only session
    # superusers pass; we never load a project row.
    allowed, _ = is_allowed(
        action=PLATFORM_TAXON_SEED_BIRDNET_ACTION,
        user=current_user,
        project=None,
        request=request,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="BirdNET taxa seeding is restricted to superusers",
        )

    # Lazy import: see the rationale in :func:`force_iucn_resync` — pulling in
    # the worker module at import time would force the slim API image to load
    # the audio + ML worker dependency tree.
    from echoroo.workers.taxon_tasks import seed_birdnet_taxa as seed_task

    async_result = seed_task.delay()
    enqueued_at = datetime.now(UTC)

    # The request-scoped ``db`` session already issued the superuser probe, so
    # reuse the IUCN endpoint's fresh-session audit pattern (see its note).
    await db.commit()

    try:
        async with AsyncSessionLocal() as platform_audit_session:
            try:
                await AuditLogService(
                    platform_audit_session
                ).write_platform_event(
                    actor_user_id=current_user.id,
                    action="platform.taxon.seed_birdnet",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail={
                        "task_id": async_result.id,
                        "enqueued_at": enqueued_at.isoformat(),
                    },
                )
                await platform_audit_session.commit()
            except Exception:
                await platform_audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — soft alert; never blocks the dispatch
        logger.warning(
            "platform.taxon.seed_birdnet audit write failed (FR-089 soft alert): "
            "actor=%s task_id=%s error=%r",
            current_user.id,
            async_result.id,
            exc,
        )

    return TaskDispatchResponse(
        task_id=async_result.id,
        enqueued_at=enqueued_at,
    )


# ---------------------------------------------------------------------------
# POST /admin/taxon/sync-vernacular
# ---------------------------------------------------------------------------


@router.post(
    "/taxon/sync-vernacular",
    response_model=TaskDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync taxon vernacular names from GBIF (Superuser)",
    description=(
        "Fire-and-forget Celery dispatch of the two-stage GBIF maintenance "
        "chain: ``resolve_gbif_batch`` (fill GBIF classification metadata) "
        "followed by ``fetch_vernacular_names_batch`` (persist locale-specific "
        "vernacular names). The stages run sequentially via a Celery ``chain`` "
        "of immutable signatures so the second stage only runs after the first "
        "completes. The endpoint surfaces the chain's task id. The action is "
        "platform-scope (no project_id) and writes a ``platform_audit_log`` "
        "entry."
    ),
)
async def sync_taxon_vernacular(
    request: Request,
    payload: TaxonSyncVernacularRequest,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> TaskDispatchResponse:
    """Enqueue the GBIF resolve→vernacular chain and return its task id."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None

    # Platform-scope gate (Step 0a in :func:`is_allowed`).
    allowed, _ = is_allowed(
        action=PLATFORM_TAXON_SYNC_VERNACULAR_ACTION,
        user=current_user,
        project=None,
        request=request,
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vernacular-name sync is restricted to superusers",
        )

    # Lazy import: keep the worker dependency tree out of the slim API image.
    from celery import chain

    from echoroo.workers.taxon_tasks import (
        fetch_vernacular_names_batch,
        resolve_gbif_batch,
    )

    # Sequence the two stages with a Celery ``chain`` of *immutable*
    # signatures (``.si``): ``fetch_vernacular_names_batch`` takes its own
    # kwargs and must NOT receive ``resolve_gbif_batch``'s return dict as a
    # positional argument, so each link declares its arguments explicitly.
    workflow = chain(
        resolve_gbif_batch.si(batch_size=payload.batch_size),
        fetch_vernacular_names_batch.si(
            batch_size=payload.batch_size,
            locales=payload.locales,
            skip_existing=payload.skip_existing,
        ),
    )
    async_result = workflow.apply_async()
    enqueued_at = datetime.now(UTC)

    # Reuse the IUCN endpoint's fresh-session audit pattern (see its note).
    await db.commit()

    try:
        async with AsyncSessionLocal() as platform_audit_session:
            try:
                await AuditLogService(
                    platform_audit_session
                ).write_platform_event(
                    actor_user_id=current_user.id,
                    action="platform.taxon.sync_vernacular",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail={
                        "task_id": async_result.id,
                        "enqueued_at": enqueued_at.isoformat(),
                        "batch_size": payload.batch_size,
                        "locales": payload.locales,
                        "skip_existing": payload.skip_existing,
                    },
                )
                await platform_audit_session.commit()
            except Exception:
                await platform_audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — soft alert; never blocks the dispatch
        logger.warning(
            "platform.taxon.sync_vernacular audit write failed (FR-089 soft "
            "alert): actor=%s task_id=%s error=%r",
            current_user.id,
            async_result.id,
            exc,
        )

    return TaskDispatchResponse(
        task_id=async_result.id,
        enqueued_at=enqueued_at,
    )


# ---------------------------------------------------------------------------
# Phase 12 / T702 — POST /admin/projects/{project_id}/archive (FR-061)
# ---------------------------------------------------------------------------


def _project_advisory_lock_key(project_id: UUID) -> int:
    """Fold a project UUID into a 63-bit advisory-lock key.

    Mirrors the convention used by :mod:`echoroo.services.audit_service`
    and :mod:`echoroo.services.ownership_service` so two unrelated
    workflows cannot accidentally share a lock key.
    """
    digest = hashlib.sha256(b"project_admin_lifecycle:" + project_id.bytes).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


@router.post(
    "/projects/{project_id}/archive",
    response_model=ArchiveResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive a project (Superuser, FR-061)",
    description=(
        "Manually flip ``Project.status`` to ``ARCHIVED`` and stamp "
        "``archived_since``. Operator-supplied ``reason`` is recorded in "
        "both the project and platform audit logs (FR-088 / FR-089). "
        "Subsequent state-changing actions are blocked by Step 1 of "
        ":func:`echoroo.core.permissions.is_allowed`."
    ),
)
async def archive_project(
    project_id: UUID,
    payload: ArchiveRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> ArchiveResponse:
    """Move a project to ``ProjectStatus.ARCHIVED`` (FR-061)."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None

    # Project-scope gate. ``project.archive`` is on the FR-008b
    # superuser allowlist so non-superusers fail closed at this step;
    # superusers short-circuit through the allowlist branch.
    await gate_action(
        action=PROJECT_ARCHIVE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    now = datetime.now(UTC)

    # Serialise concurrent admin lifecycle calls on the same project.
    await db.execute(
        sa.text("SELECT pg_advisory_xact_lock(:k)"),
        {"k": _project_advisory_lock_key(project_id)},
    )

    # Resolve the project row up-front so the status precondition can
    # surface a 4xx envelope before we issue ``SELECT ... FOR UPDATE``.
    project = await load_project_or_404(db, project_id)

    if project.status == ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_PROJECT_ALREADY_ARCHIVED",
                "message": "project is already archived",
            },
        )
    # Phase 12 R1 Major M1: ACTIVE *and* DORMANT projects are valid
    # archive targets. The dormancy worker (FR-060) flips inactive
    # projects to ``DORMANT`` after 366d and the superuser then archives
    # the row in the next administrative review window. Refusing
    # ``DORMANT`` would leave that operational path closed.
    if project.status not in (ProjectStatus.ACTIVE, ProjectStatus.DORMANT):
        raise HTTPException(  # pragma: no cover — defensive (no other state exists)
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_PROJECT_NOT_ARCHIVABLE",
                "message": (
                    f"project status is {project.status.value!r}; only "
                    "ACTIVE or DORMANT projects may be archived via this endpoint"
                ),
            },
        )
    previous_status_value = project.status.value

    # Re-issue the SELECT with FOR UPDATE so the row stays locked.
    refresh_stmt = (
        sa.select(type(project))
        .where(type(project).id == project_id)
        .with_for_update()
    )
    refreshed = (await db.execute(refresh_stmt)).scalar_one()
    refreshed.status = ProjectStatus.ARCHIVED
    refreshed.archived_since = now
    refreshed.updated_at = now

    await db.flush()

    # NOTE: the AuditLogService issues SET TRANSACTION ISOLATION
    # SERIALIZABLE which fails when prior statements ran on the
    # connection. The contract says audit writes must be in a fresh
    # session; we mirror the trusted/license services and defer the
    # audit row to a sibling helper after commit. Here we therefore
    # capture the snapshot for the post-commit writer.
    project_audit_detail: dict[str, str] = {
        "reason": payload.reason,
        "previous_status": previous_status_value,
        "archived_since": now.isoformat(),
    }
    project_audit_before = {"status": previous_status_value}
    project_audit_after = {
        "status": ProjectStatus.ARCHIVED.value,
        "archived_since": now.isoformat(),
    }

    # Outbox notification to the (former) Owner. The dispatcher side
    # ships in Phase 13+; here we only enqueue the row so the FR-076a
    # transactional guarantees apply.
    await outbox_enqueue(
        db,
        event_type="project.archive_notification",
        payload={
            "project_id": str(project_id),
            "owner_user_id": str(project.owner_id),
            "reason": payload.reason,
            "archived_since": now.isoformat(),
        },
        idempotency_key=f"archive_notify:{project_id}:{now.strftime('%Y-%m-%d')}",
    )

    response = ArchiveResponse(
        id=project_id,
        status=ProjectStatus.ARCHIVED.value,
        archived_since=now,
    )
    await db.commit()

    # Post-commit audit writes — fresh sessions per the audit_service
    # contract. Failures are WARNING-logged so the persistence guard
    # holds even when the audit chain hiccups.
    try:
        async with AsyncSessionLocal() as project_audit_session:
            try:
                await AuditLogService(project_audit_session).write_project_event(
                    actor_user_id=current_user.id,
                    project_id=project_id,
                    action="project.archive",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail=project_audit_detail,
                    before=project_audit_before,
                    after=project_audit_after,
                )
                await project_audit_session.commit()
            except Exception:
                await project_audit_session.rollback()
                raise

        async with AsyncSessionLocal() as platform_audit_session:
            try:
                await AuditLogService(
                    platform_audit_session
                ).write_platform_event(
                    actor_user_id=current_user.id,
                    action="platform.project.archive",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail={
                        "project_id": str(project_id),
                        "reason": payload.reason,
                    },
                )
                await platform_audit_session.commit()
            except Exception:
                await platform_audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — audit must never block persisted change
        logger.warning(
            "project.archive audit write failed (FR-088/89 soft alert): "
            "project_id=%s actor=%s error=%r",
            project_id,
            current_user.id,
            exc,
        )

    return response


# ---------------------------------------------------------------------------
# Phase 12 / T702 — POST /admin/projects/{project_id}/restore (FR-062)
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/restore",
    response_model=RestoreResponse,
    status_code=status.HTTP_200_OK,
    summary="Restore an archived project (Superuser, FR-062)",
    description=(
        "Flip ``ProjectStatus`` from ``ARCHIVED`` to ``ACTIVE`` and "
        "nominate a new Owner. Optionally upserts old members back into "
        "``project_members``. Both project and platform audit logs are "
        "recorded; restored members + Owner receive an outbox "
        "notification (dispatcher in Phase 13+)."
    ),
)
async def restore_project(
    project_id: UUID,
    payload: RestoreRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> RestoreResponse:
    """Move an archived project back to ACTIVE (FR-062)."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None

    # ``project.restore`` is on the FR-008b superuser allowlist; the
    # gate short-circuits non-superusers via the EDIT_PROJECT sentinel.
    await gate_action(
        action=PROJECT_RESTORE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    now = datetime.now(UTC)

    await db.execute(
        sa.text("SELECT pg_advisory_xact_lock(:k)"),
        {"k": _project_advisory_lock_key(project_id)},
    )

    project = await load_project_or_404(db, project_id)
    if project.status != ProjectStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_PROJECT_NOT_ARCHIVED",
                "message": (
                    f"project status is {project.status.value!r}; only "
                    "ARCHIVED projects may be restored"
                ),
            },
        )

    # Validate the new Owner exists and is not soft-deleted.
    new_owner_stmt = sa.select(User).where(
        User.id == payload.new_owner_user_id,
        User.deleted_at.is_(None),
    )
    new_owner = (await db.execute(new_owner_stmt)).scalar_one_or_none()
    if new_owner is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ERR_NEW_OWNER_NOT_FOUND",
                "message": (
                    f"user {payload.new_owner_user_id} not found or "
                    "soft-deleted; refusing to restore"
                ),
            },
        )

    refresh_stmt = (
        sa.select(type(project))
        .where(type(project).id == project_id)
        .with_for_update()
    )
    refreshed = (await db.execute(refresh_stmt)).scalar_one()
    previous_status = refreshed.status.value
    refreshed.status = ProjectStatus.ACTIVE
    refreshed.archived_since = None
    # Phase 12 R1 Minor m2: clear ``dormant_since`` on restore. With M1
    # in place, the project at archive time may have been DORMANT; the
    # stale timestamp would otherwise survive a round-trip
    # (DORMANT → ARCHIVED → ACTIVE) and confuse downstream reports
    # showing "dormant since 2024-…" against an actively-used project.
    refreshed.dormant_since = None
    refreshed.owner_id = payload.new_owner_user_id
    refreshed.updated_at = now

    await db.flush()

    # Restore members. We use a per-row UPSERT pattern: existing rows
    # (matched on (project_id, user_id) regardless of removed_at) get
    # their role updated and ``removed_at`` cleared; missing rows get a
    # fresh INSERT. Phase 12 keeps the cardinality small (operator
    # selects from the UI) so we avoid a bulk INSERT statement.
    restored_count = 0
    for member_entry in payload.restored_members:
        existing_stmt = (
            sa.select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == member_entry.user_id,
            )
            .with_for_update()
        )
        existing = (await db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            existing.role = member_entry.role
            existing.removed_at = None
            existing.updated_at = now
        else:
            db.add(
                ProjectMember(
                    project_id=project_id,
                    user_id=member_entry.user_id,
                    role=member_entry.role,
                    joined_at=now,
                    invited_by_id=current_user.id,
                )
            )
        restored_count += 1

    await db.flush()

    # Outbox notifications — Owner + each restored member. Each row uses
    # a deterministic idempotency key so a retry collapses cleanly.
    notify_recipients: list[tuple[UUID, str]] = [
        (payload.new_owner_user_id, "owner"),
    ]
    notify_recipients.extend(
        (m.user_id, "restored_member") for m in payload.restored_members
    )
    for recipient_id, role_label in notify_recipients:
        await outbox_enqueue(
            db,
            event_type="project.restore_notification",
            payload={
                "project_id": str(project_id),
                "recipient_user_id": str(recipient_id),
                "role": role_label,
                "restored_at": now.isoformat(),
            },
            idempotency_key=(
                f"restore_notify:{project_id}:{recipient_id}:"
                f"{now.strftime('%Y-%m-%d')}"
            ),
        )

    response = RestoreResponse(
        id=project_id,
        status=ProjectStatus.ACTIVE.value,
        owner_id=payload.new_owner_user_id,
        restored_member_count=restored_count,
    )
    await db.commit()

    # Post-commit audit (fresh sessions, FR-088 + FR-089).
    try:
        async with AsyncSessionLocal() as project_audit_session:
            try:
                await AuditLogService(project_audit_session).write_project_event(
                    actor_user_id=current_user.id,
                    project_id=project_id,
                    action="project.restore",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail={
                        "previous_status": previous_status,
                        "new_owner_id": str(payload.new_owner_user_id),
                        "restored_member_count": restored_count,
                    },
                    before={"status": previous_status},
                    after={
                        "status": ProjectStatus.ACTIVE.value,
                        "owner_id": str(payload.new_owner_user_id),
                    },
                )
                await project_audit_session.commit()
            except Exception:
                await project_audit_session.rollback()
                raise

        async with AsyncSessionLocal() as platform_audit_session:
            try:
                await AuditLogService(
                    platform_audit_session
                ).write_platform_event(
                    actor_user_id=current_user.id,
                    action="platform.project.restore",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail={
                        "project_id": str(project_id),
                        "new_owner_id": str(payload.new_owner_user_id),
                        "restored_member_count": restored_count,
                    },
                )
                await platform_audit_session.commit()
            except Exception:
                await platform_audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — audit never blocks restore
        logger.warning(
            "project.restore audit write failed (FR-088/89 soft alert): "
            "project_id=%s actor=%s error=%r",
            project_id,
            current_user.id,
            exc,
        )

    return response


# ---------------------------------------------------------------------------
# Phase 15 Batch 5a — Superuser CRUD admin endpoints (FR-111 / FR-072 / FR-084)
# ---------------------------------------------------------------------------
#
# All endpoints below are platform-scope and gated by the
# ``is_superuser_only`` Step 0a branch in :func:`is_allowed`. The Step -1
# universal API-key veto (FR-084) denies any caller authenticated via
# API key irrespective of scopes — this is the structural defence
# enforced by ``test_superuser_api_key_forbidden.py``.


async def _gate_platform_superuser_action(
    *,
    action: Action,
    current_user: User,
    request: Request,
) -> None:
    """Re-run :func:`is_allowed` after the helper-level superuser probe.

    ``_require_authenticated_superuser`` already proved the caller is a
    session superuser (the :class:`Superuser` row exists and has
    ``revoked_at IS NULL``). This second pass routes through the
    canonical permission gate so the Step -1 API-key veto + the Step 0a
    platform branch stay authoritative — defence in depth against any
    future regression that lets API-key principals reach this module.
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
            detail={
                "error": "ERR_SUPERUSER_ONLY",
                "message": (
                    f"action {action.name!r} is restricted to superuser sessions"
                ),
            },
        )


# ---------------------------------------------------------------------------
# GET /admin/superusers — list active + revoked
# ---------------------------------------------------------------------------


@router.get(
    "/superusers",
    response_model=SuperuserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List superusers (Superuser, FR-111)",
    description=(
        "Return every ``superusers`` row (active + revoked) plus the "
        "summary counts the admin dashboard needs to render the "
        "M-of-N status banner."
    ),
)
async def list_superusers(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> SuperuserListResponse:
    """Return all superuser rows with their derived state."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_LIST_ACTION,
        current_user=current_user,
        request=request,
    )

    rows_stmt = sa.select(Superuser).order_by(Superuser.added_at.desc())
    rows = (await db.execute(rows_stmt)).scalars().all()

    items: list[SuperuserSummary] = []
    active_count = 0
    for row in rows:
        if row.revoked_at is None:
            active_count += 1
        items.append(
            SuperuserSummary(
                id=row.id,
                user_id=row.user_id,
                added_by_id=row.added_by_id,
                added_at=row.added_at,
                revoked_at=row.revoked_at,
                allowed_ip_cidrs=list(row.allowed_ip_cidrs or []),
                webauthn_credential_count=len(row.webauthn_credentials or []),
            )
        )

    break_glass_active = await superuser_service.is_break_glass_active(db)

    return SuperuserListResponse(
        items=items,
        active_count=active_count,
        min_superusers=superuser_service.MIN_SUPERUSERS,
        break_glass_active=break_glass_active,
    )


# ---------------------------------------------------------------------------
# POST /admin/superusers — promote a user (M-of-N or direct)
# ---------------------------------------------------------------------------


@router.post(
    "/superusers",
    response_model=SuperuserActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add a superuser (Superuser, FR-111)",
    description=(
        "Open an M-of-N approval ticket OR (when active count < 3) "
        "promote directly. Returns 202 with ``status='pending'`` for the "
        "M-of-N path and 201-equivalent ``status='direct'`` for the "
        "creation-time exception."
    ),
    # Phase 16 Batch 6g-3: gate destructive admin via step-up token.
    dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_DESTRUCTIVE))],
)
async def add_superuser_endpoint(
    payload: SuperuserAddRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> SuperuserActionResponse:
    """Promote a user to superuser via the engine."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_ADD_ACTION,
        current_user=current_user,
        request=request,
    )

    requester_superuser_id = _require_superuser_id(current_user)

    try:
        outcome = await superuser_service.add_superuser(
            db,
            target_user_id=payload.target_user_id,
            requester_superuser_id=requester_superuser_id,
            actor_user_id=current_user.id,
            allowed_ip_cidrs=payload.allowed_ip_cidrs,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except superuser_service.AlreadySuperuserError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_ALREADY_SUPERUSER",
                "message": str(exc),
            },
        ) from exc
    except SuperuserServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "ERR_SUPERUSER_ADD_FAILED",
                "message": str(exc),
            },
        ) from exc

    response = SuperuserActionResponse(
        status=outcome.status,
        superuser_id=outcome.superuser_id,
        approval_request_id=outcome.approval_request_id,
        detail=dict(outcome.detail),
    )

    await db.commit()
    await superuser_service.trigger_post_commit_audit(outcome)
    return response


# ---------------------------------------------------------------------------
# POST /admin/superusers/{superuser_id}/revoke — open M-of-N revoke ticket
# ---------------------------------------------------------------------------


@router.post(
    "/superusers/{superuser_id}/revoke",
    response_model=SuperuserActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Revoke a superuser (Superuser, FR-111)",
    description=(
        "Open an M-of-N approval ticket to revoke a superuser. Always "
        "M-of-N gated; the genesis exception applies to additions only. "
        "The DB trigger ``superuser_last_protection`` (FR-111a) is the "
        "last-line defence against revoking the final row."
    ),
    # Phase 16 Batch 6g-3: gate destructive admin via step-up token.
    dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_DESTRUCTIVE))],
)
async def revoke_superuser_endpoint(
    superuser_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> SuperuserActionResponse:
    """Open an M-of-N revoke ticket for ``superuser_id``."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_REVOKE_ACTION,
        current_user=current_user,
        request=request,
    )

    requester_superuser_id = _require_superuser_id(current_user)

    try:
        outcome = await superuser_service.revoke_superuser(
            db,
            target_superuser_id=superuser_id,
            requester_superuser_id=requester_superuser_id,
            actor_user_id=current_user.id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except NotSuperuserError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ERR_SUPERUSER_NOT_FOUND",
                "message": str(exc),
            },
        ) from exc

    response = SuperuserActionResponse(
        status=outcome.status,
        superuser_id=outcome.superuser_id,
        approval_request_id=outcome.approval_request_id,
        detail=dict(outcome.detail),
    )

    await db.commit()
    await superuser_service.trigger_post_commit_audit(outcome)
    return response


# ---------------------------------------------------------------------------
# GET /admin/superusers/approval-requests — list pending M-of-N tickets
# ---------------------------------------------------------------------------


@router.get(
    "/superusers/approval-requests",
    response_model=SuperuserApprovalRequestListResponse,
    status_code=status.HTTP_200_OK,
    summary="List M-of-N approval requests (Superuser, FR-111)",
    description=(
        "Return every ``superuser_approval_requests`` row, ordered by "
        "creation time (newest first). The optional ``status`` query "
        "parameter narrows the set to ``pending`` / ``applied`` / "
        "``rejected``."
    ),
)
async def list_approval_requests(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
    status_filter: str | None = None,
) -> SuperuserApprovalRequestListResponse:
    """Return approval requests (optionally filtered by status)."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_APPROVAL_REQUEST_LIST_ACTION,
        current_user=current_user,
        request=request,
    )

    stmt = sa.select(SuperuserApprovalRequest).order_by(
        SuperuserApprovalRequest.created_at.desc()
    )
    if status_filter is not None:
        stmt = stmt.where(SuperuserApprovalRequest.status == status_filter)

    rows = (await db.execute(stmt)).scalars().all()
    items = [
        SuperuserApprovalRequestSummary(
            id=row.id,
            action=row.action,
            # Phase 15 Batch 5a R2 — Codex Major 1: never expose raw
            # JSONB ``detail`` / ``approvals``. The service layer
            # embeds operator-supplied secrets (e.g. WebAuthn raw
            # public-key payloads) into ``superuser.add`` ticket
            # detail; the redaction helpers above enforce a
            # fail-closed allowlist.
            detail=_redact_approval_detail(
                dict(row.detail) if row.detail else None
            ),
            requested_by_id=row.requested_by_id,
            approvals=_redact_approvals_list(list(row.approvals or [])),
            status=row.status,
            created_at=row.created_at,
            executed_at=row.executed_at,
        )
        for row in rows
    ]
    pending_count = sum(1 for item in items if item.status == "pending")

    return SuperuserApprovalRequestListResponse(
        items=items,
        pending_count=pending_count,
        min_approvals=superuser_service.MIN_APPROVALS,
    )


# ---------------------------------------------------------------------------
# POST /admin/superusers/approval-requests/{id}/approve
# ---------------------------------------------------------------------------


@router.post(
    "/superusers/approval-requests/{approval_request_id}/approve",
    response_model=SuperuserActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve an M-of-N ticket (Superuser, FR-111)",
    description=(
        "Append the caller's approval to an existing pending ticket. "
        "When ``approvals`` reaches the spec quorum (= 2) the engine "
        "dispatches the underlying mutation in the same transaction."
    ),
    # Phase 16 Batch 6g-3: gate destructive admin via step-up token.
    dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_DESTRUCTIVE))],
)
async def approve_request_endpoint(
    approval_request_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> SuperuserActionResponse:
    """Co-sign a pending superuser approval ticket."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_APPROVE_REQUEST_ACTION,
        current_user=current_user,
        request=request,
    )

    approver_superuser_id = _require_superuser_id(current_user)

    try:
        outcome = await superuser_service.approve_request(
            db,
            request_id_uuid=approval_request_id,
            approver_superuser_id=approver_superuser_id,
            actor_user_id=current_user.id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except ApprovalRequestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ERR_APPROVAL_REQUEST_NOT_FOUND",
                "message": str(exc),
            },
        ) from exc
    except ApprovalRequestStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_APPROVAL_REQUEST_STATE_INVALID",
                "message": str(exc),
            },
        ) from exc
    except DuplicateApprovalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_DUPLICATE_APPROVER",
                "message": str(exc),
            },
        ) from exc
    except LastSuperuserProtectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_LAST_SUPERUSER_PROTECTION",
                "message": str(exc),
            },
        ) from exc
    except AlreadySuperuserError as exc:
        # Phase 15 Batch 5a R2 — Codex Minor 1: a stale ``superuser.add``
        # ticket whose target was already promoted (via a sibling
        # creation-time exception or a parallel approve) raises
        # AlreadySuperuserError on the apply path. Surface a clean
        # 409 instead of the previous unhandled 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "stale_add_ticket_target_already_superuser",
                "message": str(exc),
            },
        ) from exc
    except NotSuperuserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "ERR_NOT_SUPERUSER",
                "message": str(exc),
            },
        ) from exc

    response = SuperuserActionResponse(
        status=outcome.status,
        superuser_id=outcome.superuser_id,
        approval_request_id=outcome.approval_request_id,
        detail=dict(outcome.detail),
    )

    await db.commit()
    await superuser_service.trigger_post_commit_audit(outcome)
    return response


# ---------------------------------------------------------------------------
# POST /admin/superusers/approval-requests/{id}/reject
# ---------------------------------------------------------------------------


@router.post(
    "/superusers/approval-requests/{approval_request_id}/reject",
    response_model=SuperuserActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject an M-of-N ticket (Superuser, FR-111)",
    description=(
        "Mark an existing pending ticket as ``rejected`` with a "
        "mandatory free-form reason. The decision is recorded on the "
        "JSONB ``approvals`` array so the dashboard renders the full "
        "history."
    ),
    # Phase 16 Batch 6g-3: gate destructive admin via step-up token.
    dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_DESTRUCTIVE))],
)
async def reject_request_endpoint(
    approval_request_id: UUID,
    payload: SuperuserRejectRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> SuperuserActionResponse:
    """Reject a pending superuser approval ticket."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_REJECT_REQUEST_ACTION,
        current_user=current_user,
        request=request,
    )

    rejector_superuser_id = _require_superuser_id(current_user)

    try:
        outcome = await superuser_service.reject_request(
            db,
            request_id_uuid=approval_request_id,
            rejector_superuser_id=rejector_superuser_id,
            reason=payload.reason,
            actor_user_id=current_user.id,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except ApprovalRequestNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ERR_APPROVAL_REQUEST_NOT_FOUND",
                "message": str(exc),
            },
        ) from exc
    except ApprovalRequestStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_APPROVAL_REQUEST_STATE_INVALID",
                "message": str(exc),
            },
        ) from exc

    response = SuperuserActionResponse(
        status=outcome.status,
        superuser_id=outcome.superuser_id,
        approval_request_id=outcome.approval_request_id,
        detail=dict(outcome.detail),
    )

    await db.commit()
    await superuser_service.trigger_post_commit_audit(outcome)
    return response


# ---------------------------------------------------------------------------
# POST /admin/superusers/break-glass/enter
# ---------------------------------------------------------------------------


@router.post(
    "/superusers/break-glass/enter",
    response_model=SuperuserBreakGlassStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Enter break-glass mode (Superuser, FR-111)",
    description=(
        "Engage the 72 h emergency window. A replacement superuser MUST "
        "be added within 24 h. Idempotent: a second call within the "
        "window preserves the original ``started_at``."
    ),
    # Phase 16 Batch 6g-3: gate destructive admin via step-up token.
    dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_DESTRUCTIVE))],
)
async def enter_break_glass(
    payload: SuperuserBreakGlassEnterRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> SuperuserBreakGlassStatusResponse:
    """Engage the break-glass timer."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_BREAK_GLASS_ENTER_ACTION,
        current_user=current_user,
        request=request,
    )

    outcome = await superuser_service.enter_break_glass_mode(
        db,
        reason=payload.reason,
        actor_user_id=current_user.id,
        request_id=_request_id(request),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    await db.commit()
    await superuser_service.trigger_post_commit_audit(outcome)

    # Re-read status (a fresh session is not strictly required since the
    # caller-owned session has just committed) so the response reflects
    # the persisted ``system_settings`` row whether the call started a
    # new window or returned an idempotent already-active outcome.
    return await _read_break_glass_status(db)


# ---------------------------------------------------------------------------
# GET /admin/superusers/break-glass/status
# ---------------------------------------------------------------------------


@router.get(
    "/superusers/break-glass/status",
    response_model=SuperuserBreakGlassStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Read break-glass status (Superuser, FR-111)",
    description=(
        "Return the current break-glass window ``started_at`` / "
        "``expires_at`` and the FR-111 24 h replacement deadline."
    ),
)
async def get_break_glass_status(
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> SuperuserBreakGlassStatusResponse:
    """Return whether break-glass mode is currently active."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_BREAK_GLASS_STATUS_ACTION,
        current_user=current_user,
        request=request,
    )
    return await _read_break_glass_status(db)


async def _read_break_glass_status(
    db: DbSession,
) -> SuperuserBreakGlassStatusResponse:
    """Read the ``system_settings`` row and assemble the status DTO.

    Centralised so :func:`enter_break_glass` and
    :func:`get_break_glass_status` agree on the parsing rules.
    """
    started_raw = await superuser_service._system_setting_get(
        db, superuser_service._SETTING_BREAK_GLASS_STARTED_AT
    )
    reason_raw = await superuser_service._system_setting_get(
        db, superuser_service._SETTING_BREAK_GLASS_REASON
    )
    if started_raw is None:
        return SuperuserBreakGlassStatusResponse(
            active=False,
            started_at=None,
            expires_at=None,
            replacement_deadline_at=None,
            reason=None,
        )
    try:
        started_at = datetime.fromisoformat(str(started_raw))
    except (TypeError, ValueError):
        # Mirrors :func:`is_break_glass_active` parsing fallback.
        return SuperuserBreakGlassStatusResponse(
            active=False,
            started_at=None,
            expires_at=None,
            replacement_deadline_at=None,
            reason=str(reason_raw) if reason_raw is not None else None,
        )
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    expires_at = started_at + superuser_service.BREAK_GLASS_WINDOW
    replacement_deadline = (
        started_at + superuser_service.BREAK_GLASS_REPLACEMENT_DEADLINE
    )
    now = datetime.now(UTC)
    return SuperuserBreakGlassStatusResponse(
        active=now < expires_at,
        started_at=started_at,
        expires_at=expires_at,
        replacement_deadline_at=replacement_deadline,
        reason=str(reason_raw) if reason_raw is not None else None,
    )


# ---------------------------------------------------------------------------
# PATCH /admin/superusers/{id}/ip-allowlist
# ---------------------------------------------------------------------------


@router.patch(
    "/superusers/{superuser_id}/ip-allowlist",
    response_model=SuperuserIpAllowlistResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a superuser's IP allowlist (Superuser, FR-072)",
    description=(
        "Replace ``superusers.allowed_ip_cidrs`` wholesale. The auth "
        "middleware (FR-072) parses each CIDR and rejects mutating "
        "requests originating outside the allowlist; syntax validation "
        "is delegated to that layer."
    ),
    # Phase 16 Batch 6g-3: gate destructive admin via step-up token.
    dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_DESTRUCTIVE))],
)
async def update_ip_allowlist(
    superuser_id: UUID,
    payload: SuperuserIpAllowlistUpdateRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> SuperuserIpAllowlistResponse:
    """Persist a new IP allowlist on the target superuser row."""
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None
    await _gate_platform_superuser_action(
        action=SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION,
        current_user=current_user,
        request=request,
    )

    target_stmt = (
        sa.select(Superuser)
        .where(Superuser.id == superuser_id)
        .with_for_update()
    )
    target = (await db.execute(target_stmt)).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ERR_SUPERUSER_NOT_FOUND",
                "message": f"superuser {superuser_id} not found",
            },
        )
    if target.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_SUPERUSER_REVOKED",
                "message": (
                    f"superuser {superuser_id} has been revoked; "
                    "cannot mutate allowlist"
                ),
            },
        )

    now = datetime.now(UTC)
    new_cidrs = list(payload.allowed_ip_cidrs)
    before_cidrs = list(target.allowed_ip_cidrs or [])
    target.allowed_ip_cidrs = new_cidrs
    target.updated_at = now
    await db.flush()

    response = SuperuserIpAllowlistResponse(
        superuser_id=superuser_id,
        allowed_ip_cidrs=new_cidrs,
        updated_at=now,
    )

    await db.commit()

    # Post-commit platform audit (FR-089, FR-088 soft alert).
    try:
        async with AsyncSessionLocal() as audit_session:
            try:
                await AuditLogService(audit_session).write_platform_event(
                    actor_user_id=current_user.id,
                    action="superuser.ip_allowlist.updated",
                    request_id=_request_id(request),
                    ip=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail={
                        "superuser_id": str(superuser_id),
                        "before": before_cidrs,
                        "after": new_cidrs,
                    },
                    before={"allowed_ip_cidrs": before_cidrs},
                    after={"allowed_ip_cidrs": new_cidrs},
                )
                await audit_session.commit()
            except Exception:
                await audit_session.rollback()
                raise
    except Exception as exc:  # noqa: BLE001 — audit must never block persisted change
        logger.warning(
            "superuser.ip_allowlist.updated audit write failed "
            "(FR-089 soft alert): superuser_id=%s actor=%s error=%r",
            superuser_id,
            current_user.id,
            exc,
        )

    return response


# ---------------------------------------------------------------------------
# POST /admin/users/{user_id}/reset-password  (spec/011 §FR-011-201, T311)
# ---------------------------------------------------------------------------
#
# System-superuser-only password reset endpoint. Gated by:
#
#   * ``gate_action(ADMIN_USER_RESET_PASSWORD_ACTION)`` — platform-scope
#     Action with ``is_superuser_only=True`` (Step -1 API-key veto +
#     Step 0a platform branch in :func:`is_allowed`).
#   * ``require_step_up_token(SCOPE_ADMIN_RECOVERY)`` — FR-011-206
#     AND-condition (password + 2FA) step-up enforcement. The verifier
#     additionally refuses ``admin_destructive``-scoped tokens, so the
#     spec/006 step-up path cannot be replayed against this endpoint.
#
# The handler delegates the actual mutation to
# :func:`echoroo.services.admin_password_reset.reset_password`, which
# owns:
#
#   * argon2-hashing the generated temporary password into
#     ``users.password_hash``;
#   * setting ``users.must_change_password = True`` and
#     ``users.temp_password_expires_at = now() + 24h``;
#   * rotating ``users.security_stamp`` so every outstanding session
#     token for the target user is invalidated (FR-055 + FR-011-203);
#   * revoking every active :class:`TrustedDevice` row for the target
#     user via :meth:`TrustedDeviceService.revoke_all_for_user`
#     (defence in depth on top of the flush listener);
#   * emitting a ``platform.user.password_reset_by_superuser`` audit row
#     (or the ``_self`` variant when ``actor == target``, FR-011-210)
#     in a *fresh* AsyncSession — the audit writer requires a clean
#     SERIALIZABLE-compatible connection (FR-093).
#
# The handler is responsible for:
#
#   * supplying the request-envelope context (request_id / ip /
#     user_agent) the audit row needs;
#   * setting ``Cache-Control: no-store, no-cache, must-revalidate,
#     private`` and ``Referrer-Policy: no-referrer`` response headers
#     (FR-011-202) so neither browser history nor intermediate proxies
#     can retain the click-to-reveal temp password;
#   * committing the surrounding transaction so the User row update +
#     trusted-device revocations land atomically alongside the audit.
#
# **Self-reset (FR-011-210)**: when the superuser invokes the endpoint
# against their own ``user_id``, the service emits the ``_self`` audit
# variant and revokes all of the superuser's other sessions + trusted
# devices in the same way. The superuser remains authenticated on the
# *current* session (the rotation invalidates *other* refresh-token
# families) until they log out — but the next page load they make will
# pass through :class:`ForcedPasswordChangeMiddleware` and 423 them to
# ``/change-password``. The ``must_change_password = True`` write is
# applied to *the actor's own row* in this case, which is the
# documented behaviour.


@router.post(
    "/users/{user_id}/reset-password",
    response_model=AdminPasswordResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset a target user's password (system superuser only)",
    description=(
        "spec/011 §FR-011-201..210. Generate a one-time temporary "
        "password, hash it into ``users.password_hash``, set "
        "``must_change_password=true`` + 24h TTL, invalidate the "
        "target user's other sessions, revoke every active trusted "
        "device, and emit a ``platform.user.password_reset_by_superuser`` "
        "(or ``_self`` for self-reset) audit row. The plaintext temp "
        "password is returned exactly once in the response body and is "
        "never persisted anywhere except via its argon2 hash."
    ),
    operation_id="adminResetUserPassword",
    # Step-up gate per FR-011-206: caller must have completed an
    # AND-condition (password + 2FA) challenge within the last 5
    # minutes. ``admin_destructive`` tokens (spec/006) are explicitly
    # refused by the verifier — see
    # :func:`echoroo.services.step_up_token_service.verify_step_up_token`.
    dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_RECOVERY))],
)
async def reset_user_password(
    user_id: UUID,
    payload: AdminPasswordResetBody,
    response: Response,
    current_user: OptionalCurrentUser,
    request: Request,
    db: DbSession,
) -> AdminPasswordResetResponse:
    """Issue a one-time temp password for ``user_id`` (spec/011 T311)."""
    # 1. Auth + superuser gate. ``_require_authenticated_superuser``
    #    re-probes the ``superusers`` table so a stale ``is_superuser``
    #    transient stamp cannot bypass the gate.
    await _require_authenticated_superuser(current_user, db)
    assert current_user is not None  # narrowed by the helper above

    # 2. Canonical permission gate. ``ADMIN_USER_RESET_PASSWORD_ACTION``
    #    is platform-scope + superuser-only — the Step -1 API-key veto +
    #    Step 0a branch in :func:`is_allowed` enforce that no project
    #    admin / member / API-key principal can reach this code path
    #    even if the route handler is ever wired into a different
    #    Authentication transport.
    await _gate_platform_superuser_action(
        action=ADMIN_USER_RESET_PASSWORD_ACTION,
        current_user=current_user,
        request=request,
    )

    # 3. Delegate the mutation. The service owns hashing, forced-change
    #    state, security-stamp rotation (triggering session +
    #    trusted-device invalidation), the explicit
    #    ``revoke_all_for_user`` defence-in-depth call, and the audit
    #    write (in a fresh session).
    try:
        temp_password = await admin_password_reset.reset_password(
            db,
            actor_id=current_user.id,
            target_user_id=user_id,
            reason=payload.reason,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except LookupError as exc:
        # Target user does not exist (or is soft-deleted). The
        # ``users`` table is the canonical source — we surface the
        # generic 404 without distinguishing soft-deleted from
        # never-existed so an enumeration attempt cannot probe the
        # account-deletion table indirectly.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "ERR_USER_NOT_FOUND",
                "message": "User not found.",
            },
        ) from exc

    # 4. Commit the surrounding transaction so the User row update +
    #    trusted-device revocations are durable. The audit row already
    #    committed in its own fresh session inside the service (see
    #    ``admin_password_reset.reset_password`` docstring §Audit).
    await db.commit()

    # 5. FR-011-202 response-header invariant. The
    #    :class:`AdminPasswordResetResponse` payload carries the
    #    plaintext temp password — neither the browser nor any
    #    intermediate proxy may cache or retain the value. The
    #    ``Referrer-Policy`` header additionally prevents the temp
    #    password from leaking via the ``Referer`` request header on
    #    any subsequent click out of the reveal dialog.
    response.headers["Cache-Control"] = (
        "no-store, no-cache, must-revalidate, private"
    )
    response.headers["Referrer-Policy"] = "no-referrer"

    # The ``temp_password_expires_at`` we report to the caller MUST
    # match the value the service just wrote to the User row, so we
    # re-fetch the target's expiry from the just-committed row. The
    # service used ``datetime.now(UTC) + timedelta(hours=24)`` so a
    # local recomputation here would drift by a few milliseconds.
    target = await db.get(User, user_id)
    assert target is not None  # service raised LookupError otherwise
    expires_at = target.temp_password_expires_at
    assert expires_at is not None  # service always sets this

    return AdminPasswordResetResponse(
        temporary_password=temp_password,
        expires_at=expires_at,
    )


# ---------------------------------------------------------------------------
# POST /admin/users/{user_id}/reset-2fa  (Phase 17 follow-up — STUB ONLY)
# ---------------------------------------------------------------------------
#
# Codex Round X advice (Phase 17 backlog A-11): the contract path
# ``/users/{userId}/reset-2fa`` is declared in
# ``specs/006-permissions-redesign/contracts/admin.yaml`` but the full
# behaviour (4-factor verification + 24 h delay job + 72 h cooldown + the
# ``skip_delay`` M-of-N approval ticket) is non-trivial and **must** ship
# as a dedicated PR with audit / Celery / state-machine support. Until
# then we register the path with a body schema validator and a
# superuser-only guard so:
#
# * The OpenAPI surface stays in lockstep with the contract — closing the
#   ``test_admin_paths_exist`` drift surfaced after PR #9 merged.
# * Authentication / CSRF transport is exercised by the standard
#   middleware chain (cookie + CSRF + IP allowlist + WebAuthn) just like
#   every other admin endpoint, so we don't accidentally ship a softer
#   gate when the real handler arrives.
# * Pydantic validates the request body — a malformed payload still
#   returns 422, which prevents a future implementer from inadvertently
#   relaxing the schema.
# * The handler returns ``501 Not Implemented`` so downstream callers
#   cannot mistake the stub for a working operation. ``202`` or partial
#   verification was rejected in review precisely because it would let
#   an unfinished security workflow leak into production behaviour.
#
# Tracker: ``specs/006-permissions-redesign/PHASE17_BACKLOG.md`` item
# A-11.


@router.post(
    "/users/{user_id}/reset-2fa",
    status_code=status.HTTP_202_ACCEPTED,
    summary="2FA reset for a user (admin operation, FR-072)",
    description=(
        "Phase 17 backlog A-11. Open a 2FA reset request bound to "
        "``user_id``. The 4-factor identity proof is performed via "
        "``POST /web-api/v1/auth/confirm-identity-for-2fa-reset`` — "
        "the operator pastes the resulting ``confirmation_token`` "
        "into this body. Default flow (``skip_delay=false``) creates "
        "a row in ``pending_delay`` and the Celery beat poller "
        "dispatches after 24 h. ``skip_delay=true`` opens an M-of-N "
        "``SuperuserApprovalRequest`` (action "
        "``two_factor_reset.skip_delay``); quorum (two co-signers) "
        "flips the row to ``approved`` for immediate dispatch."
    ),
    operation_id="reset2FA",
    # spec/011 §FR-011-306 / T400: admin 2FA reset is a *recovery*
    # action, not a generic destructive one. It MUST be gated by the
    # ``admin_recovery`` step-up scope (AND-condition password + 2FA),
    # consistent with the admin password-reset endpoint above (which
    # already uses ``SCOPE_ADMIN_RECOVERY``). The verifier refuses a
    # webauthn-only ``admin_destructive`` token here so a half-completed
    # challenge cannot drive the recovery surface.
    dependencies=[Depends(require_step_up_token(SCOPE_ADMIN_RECOVERY))],
)
async def reset_two_factor(
    user_id: UUID,
    payload: ResetTwoFactorRequest,
    current_user: OptionalCurrentUser,
    request: Request,
    db: DbSession,
) -> dict[str, str | None]:
    """Open a Phase 17 A-11 admin 2FA reset request."""
    # 1. Auth + superuser gate.
    await _require_authenticated_superuser(current_user, db)
    superuser_id = _require_superuser_id(current_user)

    # 2. Resolve target user. 404 keeps parity with the rest of /admin.
    target = await db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "ERR_USER_NOT_FOUND", "message": "User not found."},
        )

    # 3. Open the request. The service performs:
    #   - confirmation token consume (HMAC + nonce one-time-use)
    #   - active-request guard (partial unique index pre-check)
    #   - row insert (+ M-of-N ticket if skip_delay=True)
    from echoroo.services import two_factor_reset_service
    from echoroo.services.two_factor_confirmation_token import (
        ConfirmationTokenAlreadyConsumedError,
        ConfirmationTokenError,
        ConfirmationTokenExpiredError,
        ConfirmationTokenInvalidError,
        ConfirmationTokenUserMismatchError,
    )

    try:
        outcome = await two_factor_reset_service.create_request(
            db,
            target_user=target,
            requested_by_superuser_id=superuser_id,
            confirmation_token=payload.confirmation_token,
            support_ticket_id=payload.support_ticket_id,
            reason=payload.reason,
            skip_delay=payload.skip_delay,
            request_id=_request_id(request),
            ip=_client_ip(request),
            user_agent=_user_agent(request),
        )
        await db.commit()
    except ConfirmationTokenAlreadyConsumedError as exc:
        # Round-2 Fix-4: emit a dedicated audit row so a leaked-token
        # replay is visible in ``platform_audit_log`` separately from
        # the generic invalid-token path. The HTTP response stays 409
        # (same surface as a fresh-but-malformed token) so the operator
        # cannot use the API to distinguish "never existed" from
        # "already used".
        #
        # Capture identity-bearing fields BEFORE ``db.rollback()`` so
        # the resulting session-state expiry does not force a fresh
        # SELECT on ``current_user.id`` from a closed greenlet — which
        # would surface as a confusing ``MissingGreenlet`` instead of
        # the intended 409.
        replay_actor_id = current_user.id if current_user else superuser_id
        replay_target_id = str(user_id)
        replay_operator_id = str(superuser_id)
        replay_ticket_id = payload.support_ticket_id
        replay_ip = _client_ip(request)
        replay_ip_hash = hashlib.sha256(replay_ip.encode()).hexdigest()
        replay_request_id = _request_id(request)
        replay_user_agent = _user_agent(request)
        await db.rollback()
        await two_factor_reset_service._write_platform_audit(  # noqa: SLF001
            actor_user_id=replay_actor_id,
            action=two_factor_reset_service.AUDIT_ACTION_CONFIRMATION_TOKEN_REPLAY,
            detail={
                "target_user_id": replay_target_id,
                "operator_id": replay_operator_id,
                "support_ticket_id": replay_ticket_id,
                "ip_hash": replay_ip_hash,
            },
            request_id=replay_request_id,
            ip=replay_ip,
            user_agent=replay_user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_INVALID_CONFIRMATION_TOKEN",
                "message": (
                    "Confirmation token is invalid, expired, or already "
                    "consumed. Re-issue via "
                    "/auth/confirm-identity-for-2fa-reset."
                ),
            },
        ) from exc
    except (
        ConfirmationTokenInvalidError,
        ConfirmationTokenExpiredError,
        ConfirmationTokenUserMismatchError,
    ) as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_INVALID_CONFIRMATION_TOKEN",
                "message": (
                    "Confirmation token is invalid, expired, or already "
                    "consumed. Re-issue via "
                    "/auth/confirm-identity-for-2fa-reset."
                ),
            },
        ) from exc
    except two_factor_reset_service.ActiveResetRequestExistsError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_ACTIVE_RESET_REQUEST",
                "message": (
                    "An in-flight 2FA reset request already exists for "
                    "this user. Cancel or wait for the existing request "
                    "before opening a new one."
                ),
            },
        ) from exc
    except IntegrityError as exc:
        # Round-2 Fix-3: race window between the SELECT pre-check inside
        # ``create_request`` and the INSERT — two concurrent operators
        # can both pass the pre-check, then one wins the partial unique
        # index ``ux_two_factor_reset_requests_active_user`` and the
        # other surfaces here. Translate to the same 409 the explicit
        # ``ActiveResetRequestExistsError`` path already returns so the
        # caller sees a deterministic envelope.
        # Round-3 Fix R2-4: the constraint name comes from the service
        # module's ``ACTIVE_REQUEST_UNIQUE_CONSTRAINT`` Final so a
        # future index rename only has to touch one place.
        await db.rollback()
        constraint = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = (
            getattr(constraint, "constraint_name", "") if constraint else ""
        )
        message = str(getattr(exc, "orig", exc) or exc)
        if (
            two_factor_reset_service.ACTIVE_REQUEST_UNIQUE_CONSTRAINT
            in (constraint_name or "")
            or two_factor_reset_service.ACTIVE_REQUEST_UNIQUE_CONSTRAINT in message
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "ERR_ACTIVE_RESET_REQUEST",
                    "message": (
                        "An in-flight 2FA reset request already exists for "
                        "this user. Cancel or wait for the existing request "
                        "before opening a new one."
                    ),
                },
            ) from exc
        raise
    except ConfirmationTokenError as exc:
        # Catch-all guard against future subclasses.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "ERR_INVALID_CONFIRMATION_TOKEN",
                "message": "Confirmation token failed verification.",
            },
        ) from exc

    # 4. Audit row(s). Service helper writes the requested + token_verified pair.
    await two_factor_reset_service.trigger_create_request_audit(
        outcome=outcome,
        actor_user_id=current_user.id if current_user else superuser_id,
        target_user_id=user_id,
        support_ticket_id=payload.support_ticket_id,
        reason=payload.reason,
        skip_delay=payload.skip_delay,
        confirmation_token_nonce=outcome.confirmation_token_nonce,
        request_id=_request_id(request),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )

    return {
        "request_id": str(outcome.request_id),
        "status": outcome.status,
        "dispatch_at": (
            outcome.dispatch_at.isoformat() if outcome.dispatch_at else None
        ),
        "expires_at": outcome.expires_at.isoformat(),
        "approval_request_id": (
            str(outcome.approval_request_id)
            if outcome.approval_request_id
            else None
        ),
    }


__all__ = ["router"]
