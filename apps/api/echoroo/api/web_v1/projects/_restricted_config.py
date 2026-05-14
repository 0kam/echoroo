"""Restricted-config toggle endpoint (T400, FR-014 / FR-020-022 / FR-023 / FR-024).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml:174-197``
+ the ``RestrictedConfig`` schema at lines 430-454.

Path operations owned by this module:

* ``PATCH /{project_id}/restricted-config`` — flip the per-project
  Restricted-mode capability flags. Owner / Admin (``EDIT_PROJECT``) only.
  All eight keys (``allow_media_playback``, ``allow_detection_view``,
  ``mask_species_in_detection``, ``allow_download``, ``allow_export``,
  ``allow_voting_and_comments``, ``public_location_precision_h3_res``,
  ``allow_precise_location_to_viewer``) are required; unknown keys are
  rejected with 422 (``Extra.forbid``); ``public_location_precision_h3_res``
  accepts any integer from 3 through 15 per FR-021.

The endpoint mirrors the Bearer ``/api/v1`` surface declared in
:mod:`echoroo.api.v1.projects` so the same business logic
(:func:`echoroo.services.restricted_config_service.update_restricted_config`)
backs both transport surfaces. Cookie + CSRF transport is enforced by the
production middleware chain (CsrfMiddleware + AuthRouterMiddleware) — this
handler only resolves the principal and runs the Stage-1 permission gate.

Visibility precondition (FR-001 / FR-014):
    The toggles only apply to ``visibility='restricted'`` projects. A PATCH
    against a Public project returns 422 with the
    ``ERR_RESTRICTED_CONFIG_NOT_APPLICABLE`` semantic — the matrix already
    grants Public viewers the full Public bundle, so flipping these flags
    has no effect and the misuse should surface to the caller.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from echoroo.core.actions import PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import OptionalCurrentUser
from echoroo.models.enums import ProjectVisibility
from echoroo.schemas.project import (
    ProjectResponse,
    RestrictedConfigUpdateRequest,
)
from echoroo.services.project import (
    resolve_current_user_role,
    scrub_owner_email_for_visibility,
)
from echoroo.services.restricted_config_service import (
    trigger_post_commit_side_effects,
    update_restricted_config,
)

logger = logging.getLogger(__name__)


router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers (mirrors :mod:`._license`).
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


# ---------------------------------------------------------------------------
# T400 — PATCH /{project_id}/restricted-config (Web UI surface)
# ---------------------------------------------------------------------------


@router.patch(
    "/{project_id}/restricted-config",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update Restricted-mode capability toggles (Web UI)",
    description=(
        "Cookie + CSRF Web UI surface mirroring the programmatic "
        "``PATCH /api/v1/projects/{project_id}/restricted-config`` route. "
        "Owner / Admin (``EDIT_PROJECT``) only. The request body must "
        "specify all eight RestrictedConfig keys; unknown keys are 422 "
        "(``Extra.forbid``). The toggles only apply to "
        "``visibility='restricted'`` projects — a PATCH against a Public "
        "project returns 422. Each successful PATCH bumps "
        "``restricted_config_version`` and appends a "
        "``project.restricted_config.update`` row to ``project_audit_log`` "
        "(FR-024 / FR-088). ``public_location_precision_h3_res`` accepts "
        "any integer from 3 through 15. The ``allow_detection_view`` ON->OFF transition "
        "additionally enqueues an asynchronous search-index rebuild "
        "(FR-025a)."
    ),
)
async def update_project_restricted_config(
    project_id: UUID,
    payload: RestrictedConfigUpdateRequest,
    request: Request,
    current_user: OptionalCurrentUser,
    db: DbSession,
) -> ProjectResponse:
    """Replace the project's Restricted-mode capability toggles (Web UI).

    Authentication is resolved via :data:`OptionalCurrentUser` so the
    production cookie-session chain (``AuthRouterMiddleware`` populates
    ``request.state.principal`` from the ``session_id`` cookie + signed
    access JWT) flows through the same dependency the read-only
    ``/web-api/v1`` endpoints already use. The handler explicitly rejects
    unauthenticated callers with **401** — restricted-config mutation is
    not a Public surface. CSRF enforcement happens upstream in
    :class:`echoroo.middleware.csrf.CsrfMiddleware` which is mounted by
    the application factory; reaching this handler with an invalid CSRF
    token is impossible in production.

    Args:
        project_id: Target project UUID.
        payload: Validated request body (``Extra.forbid`` + Literal H3 res).
        request: FastAPI request (used by the Stage-1 gate).
        current_user: Optional principal (cookie or Bearer).
        db: Async database session.

    Returns:
        :class:`ProjectResponse` reflecting the new ``restricted_config`` +
        bumped ``restricted_config_version`` so the Web UI can mirror the
        change without a follow-up GET.

    Raises:
        401: Caller is unauthenticated.
        403: Caller lacks ``EDIT_PROJECT`` (Member / Viewer / non-member).
        404: Project not found.
        422: ``visibility != 'restricted'`` — the toggles do not apply.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    project = await gate_action(
        action=PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )

    # FR-001 / FR-014: the toggles only matter on Restricted-visibility
    # projects. The matrix already grants Public viewers the full Public
    # bundle, so flipping these flags is a misuse — surface as 422 so the
    # Web UI can render a meaningful error rather than the change silently
    # taking effect.
    if project.visibility != ProjectVisibility.RESTRICTED:
        # Phase 8 polish round 2 Major 1 — surface the contract envelope
        # ``ERR_RESTRICTED_CONFIG_NOT_APPLICABLE`` so callers can branch on
        # the dedicated error code (mirrors ``ERR_LICENSE_REQUIRED`` from
        # Phase 7). The global :func:`http_exception_handler` lets dict
        # ``detail`` payloads through unchanged when they already carry an
        # ``error`` key.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "ERR_RESTRICTED_CONFIG_NOT_APPLICABLE",
                "message": (
                    "restricted_config only applies to "
                    "visibility='restricted' projects (FR-001 / FR-014)."
                ),
            },
        )

    outcome = await update_restricted_config(
        session=db,
        project_id=project.id,
        new_config=payload,
        actor_user_id=current_user.id,
        request_id=_request_id(request),
        ip=_client_ip(request),
        user_agent=_user_agent(request),
    )
    # Phase 8 polish round 2 致命 1 — atomicity contract:
    #   1. Snapshot the response shape from the in-memory state the
    #      service just wrote (commit can expire JSONB attributes in some
    #      test fixtures).
    #   2. Commit the main TX so the toggle change is durable.
    #   3. ONLY THEN fire audit + Celery enqueue, so a rolled-back main TX
    #      cannot leave a phantom audit row or a phantom worker job.
    response = ProjectResponse.model_validate(outcome.project)
    # Phase 9 polish round 2 致命 1 + Major 2 (2026-04-27): scrub owner
    # email + resolve caller role so the restricted-config PATCH
    # response carries the same privacy contract as the rest of the
    # project surfaces.
    scrub_owner_email_for_visibility(
        response, project=outcome.project, current_user=current_user
    )
    response.current_user_role = await resolve_current_user_role(
        db, project=outcome.project, current_user=current_user
    )
    await db.commit()
    await trigger_post_commit_side_effects(outcome)
    return response


__all__ = ["router"]
