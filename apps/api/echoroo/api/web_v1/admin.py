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
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from echoroo.core.actions import (
    PLATFORM_IUCN_FORCE_RESYNC_ACTION,
    PROJECT_ARCHIVE_ACTION,
    PROJECT_RESTORE_ACTION,
    PROJECT_TAXON_OVERRIDE_APPROVE_ACTION,
    PROJECT_TAXON_OVERRIDE_REJECT_ACTION,
)
from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.permissions import gate_action, is_allowed, load_project_or_404
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.enums import ProjectStatus
from echoroo.models.project import ProjectMember
from echoroo.models.user import User
from echoroo.schemas.admin import (
    ArchiveRequest,
    ArchiveResponse,
    IucnForceResyncResponse,
    RestoreRequest,
    RestoreResponse,
    TaxonOverrideRejectRequest,
    TaxonOverrideResponse,
)
from echoroo.services.audit_service import AuditLogService
from echoroo.services.outbox_service import enqueue as outbox_enqueue
from echoroo.services.superuser_approval_service import (
    TaxonOverrideDecisionOutcome,
    approve_taxon_override,
    reject_taxon_override,
    trigger_decision_post_commit_audit,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


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


__all__ = ["router"]
