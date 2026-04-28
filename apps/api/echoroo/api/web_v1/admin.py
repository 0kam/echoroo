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

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from echoroo.core.actions import (
    PLATFORM_IUCN_FORCE_RESYNC_ACTION,
    PROJECT_TAXON_OVERRIDE_APPROVE_ACTION,
    PROJECT_TAXON_OVERRIDE_REJECT_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action, is_allowed
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.schemas.admin import (
    IucnForceResyncResponse,
    TaxonOverrideRejectRequest,
    TaxonOverrideResponse,
)
from echoroo.services.audit_service import AuditLogService
from echoroo.services.superuser_approval_service import (
    approve_taxon_override,
    reject_taxon_override,
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


def _require_authenticated_superuser(current_user: OptionalCurrentUser) -> None:
    """Reject Guest callers up-front with a 401 envelope.

    The downstream :func:`is_allowed` / :func:`gate_action` calls already
    fail closed for non-superusers (FR-008b), but returning a 401 for an
    unauthenticated request is the spec-aligned envelope and saves a DB
    round-trip for the project lookup.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )


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
    _require_authenticated_superuser(current_user)
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

    try:
        override = await approve_taxon_override(
            db,
            override_id=override_id,
            approver_superuser_id=current_user.id,
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

    # Mirror the project-scope audit row written by the service into
    # ``platform_audit_log`` so the superuser dashboard renders without a
    # JOIN. The platform write participates in the same transaction.
    await AuditLogService(db).write_platform_event(
        actor_user_id=current_user.id,
        action="platform.project.taxon_override.approve_looser",
        request_id=_request_id(request),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail={
            "project_id": str(project_id),
            "override_id": str(override.id),
            "taxon_id": override.taxon_id,
            "sensitivity_h3_res": override.sensitivity_h3_res,
        },
    )

    await db.commit()
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
    _require_authenticated_superuser(current_user)
    assert current_user is not None

    await gate_action(
        action=PROJECT_TAXON_OVERRIDE_REJECT_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    try:
        override = await reject_taxon_override(
            db,
            override_id=override_id,
            approver_superuser_id=current_user.id,
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

    await AuditLogService(db).write_platform_event(
        actor_user_id=current_user.id,
        action="platform.project.taxon_override.reject_looser",
        request_id=_request_id(request),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
        detail={
            "project_id": str(project_id),
            "override_id": str(override.id),
            "taxon_id": override.taxon_id,
            "sensitivity_h3_res": override.sensitivity_h3_res,
            "rejected_reason": payload.reason,
        },
    )

    await db.commit()
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
    _require_authenticated_superuser(current_user)
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

    await AuditLogService(db).write_platform_event(
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
    await db.commit()

    return IucnForceResyncResponse(
        task_id=async_result.id,
        enqueued_at=enqueued_at,
    )


__all__ = ["router"]
