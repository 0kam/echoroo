"""Project dataset license endpoints (T118 + Phase 7 polish round 2 致命 1).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module:

* ``PATCH /{project_id}/license``       — set or replace the project's
  dataset license metadata (FR-085 / FR-087).
* ``GET /{project_id}/license-history`` — return the immutable history
  of license changes for the project (FR-087).

License changes are append-only: the active row is mirrored to a
history table on every PATCH, so FR-087 can render a full audit trail
without joining the audit log. The handlers also emit a
``project.license.update`` row to ``project_audit_log`` so cross-table
chain integrity verification stays straightforward.

Both endpoints are mounted under the parent package's ``/projects``
prefix and share the underlying business logic with the programmatic
``/api/v1/projects/{id}/license`` surface — the same
:func:`echoroo.services.license_service.change_license` helper is
invoked, so the contract lives at the service layer and the router
modules stay thin.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from echoroo.core.actions import (
    PROJECT_LICENSE_HISTORY_ACTION,
    PROJECT_LICENSE_UPDATE_ACTION,
)
from echoroo.core.database import AsyncSessionLocal, DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.schemas.project import (
    ProjectLicenseHistoryEntry,
    ProjectLicenseHistoryResponse,
    ProjectLicenseUpdateRequest,
    ProjectResponse,
)
from echoroo.services.audit_service import AuditLogService
from echoroo.services.license_service import change_license, list_license_history
from echoroo.services.project import (
    resolve_current_user_role,
    scrub_owner_email_for_visibility,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request) -> str:
    return request.headers.get("user-agent") or ""


def _request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or ""


async def _write_license_audit(
    *,
    actor_user_id: UUID | None,
    project_id: UUID,
    request: Request,
    detail: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """Append a ``project.license.update`` row to ``project_audit_log``.

    Uses a fresh session so the audit row's serialisable transaction
    cannot piggy-back on the request-scoped ``DbSession`` (which has
    already issued non-isolation-level statements). Mirrors the pattern
    in :func:`echoroo.api.web_v1.audit._write_meta_audit_in_fresh_session`.
    """
    async with AsyncSessionLocal() as audit_session:
        try:
            service = AuditLogService(audit_session)
            await service.write_project_event(
                actor_user_id=actor_user_id,
                project_id=project_id,
                action="project.license.update",
                request_id=_request_id(request),
                ip=_client_ip(request),
                user_agent=_user_agent(request),
                detail=detail,
                before=before,
                after=after,
            )
            await audit_session.commit()
        except Exception:
            await audit_session.rollback()
            raise


@router.patch(
    "/{project_id}/license",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update project license (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic "
        "``PATCH /api/v1/projects/{project_id}/license`` route. "
        "Owner / Admin (MANAGE_LICENSE) only — Admins hold MANAGE_LICENSE "
        "per the canonical matrix (FR-085, FR-010). Every PATCH appends a "
        "row to ``project_license_history`` (FR-087) and an audit event to "
        "``project_audit_log`` (FR-088)."
    ),
)
async def update_project_license(
    project_id: UUID,
    payload: ProjectLicenseUpdateRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> ProjectResponse:
    """Replace the project license via the first-party Web UI surface.

    Phase 7 polish round 4 (Major 1): authentication is resolved via
    :data:`OptionalCurrentUser` so the production cookie-session chain
    (``AuthRouterMiddleware`` populates ``request.state.principal`` from
    the ``session_id`` cookie + signed access JWT) flows through the same
    dependency the read-only ``/web-api/v1`` endpoints already use. The
    handler explicitly rejects unauthenticated callers with **401** —
    license mutation is not a Public surface. CSRF enforcement happens
    upstream in :class:`echoroo.middleware.csrf.CsrfMiddleware` which is
    mounted by the application factory; reaching this handler with an
    invalid CSRF token is impossible in production.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    project = await gate_action(
        action=PROJECT_LICENSE_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    before_license = project.license.value if project.license else None
    history_row = await change_license(
        session=db,
        project_id=project.id,
        new_license=payload.license,
        actor_user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(project)

    # Audit row written in its own transaction so a serialisable failure
    # in the audit chain cannot retroactively undo the license change
    # (FR-092: audit + business mutation are coupled at-most-once-each
    # but never roll each other back). We deliberately do NOT roll back
    # the license change here — the history row already gives FR-087
    # immutability, and the FR-088 audit gap is a soft alert, not a hard
    # block. Phase 7 polish round 3 (Minor 1): emit a WARNING log when
    # the audit write fails so the gap is visible to ops monitoring
    # rather than silently swallowed (the previous ``contextlib.suppress``
    # claimed the failure was "logged" but did not actually log).
    try:
        await _write_license_audit(
            actor_user_id=current_user.id,
            project_id=project.id,
            request=request,
            detail={
                "history_id": str(history_row.id),
                "old_license": before_license,
                "new_license": payload.license.value,
            },
            before={"license": before_license},
            after={"license": payload.license.value},
        )
    except Exception as exc:  # noqa: BLE001 — audit must never block license mutation
        logger.warning(
            "project.license.update audit write failed (FR-088 soft alert): "
            "project_id=%s history_id=%s old=%s new=%s actor=%s error=%r",
            project.id,
            history_row.id,
            before_license,
            payload.license.value,
            current_user.id,
            exc,
        )

    response = ProjectResponse.model_validate(project)
    # Phase 9 polish round 2 致命 1 + Major 2 (2026-04-27): scrub
    # owner.email + resolve caller role so the contract holds for the
    # license-PATCH response too. The caller already cleared the
    # MANAGE_LICENSE gate (Owner / Admin).
    scrub_owner_email_for_visibility(
        response, project=project, current_user=current_user
    )
    response.current_user_role = await resolve_current_user_role(
        db, project=project, current_user=current_user
    )
    return response


@router.get(
    "/{project_id}/license-history",
    response_model=ProjectLicenseHistoryResponse,
    summary="Get project license history (Web UI)",
    description=(
        "Return every license-history row for the project (oldest-first)."
        " Visible to anyone holding ``VIEW_PROJECT_METADATA`` per the "
        "canonical matrix — FR-087 immutability is enforced at the "
        "storage layer, not the read."
    ),
)
async def get_project_license_history(
    project_id: UUID,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> ProjectLicenseHistoryResponse:
    """Return the license trail for ``project_id`` (Web UI surface).

    Phase 7 polish round 4 (Major 1): same session-aware authentication
    pattern as :func:`update_project_license`. ``OptionalCurrentUser``
    resolves both cookie-session principals and Bearer credentials; an
    unauthenticated caller is rejected with 401 because the canonical
    matrix gates ``VIEW_PROJECT_METADATA`` for the Restricted-visibility
    cell (Public projects route through the Guest-aware ``GET
    /{project_id}`` endpoint instead).
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    await gate_action(
        action=PROJECT_LICENSE_HISTORY_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    rows = await list_license_history(db, project_id)
    return ProjectLicenseHistoryResponse(
        items=[ProjectLicenseHistoryEntry.model_validate(row) for row in rows]
    )


__all__ = ["router"]
