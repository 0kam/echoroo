"""Project management endpoints.

Phase 3 (T126, FR-003 / FR-008 / FR-008a / FR-057 / FR-063 / FR-064):
single-project read / mutating endpoints route through the central
:func:`is_allowed` gate via the Action catalog in
:mod:`echoroo.core.actions`. Aggregate / auth-only endpoints
(``GET /projects`` list, ``POST /projects`` create) keep their existing
authentication-only contract because the central Stage-1 gate cannot
evaluate them without a concrete ``project_id`` (see ``core/actions.py``
header docstring for the documented exclusion list).

Endpoints in this module that are **not yet** registered as Actions in
``core/actions.py`` (e.g. ``transfer-ownership``, ``restricted-config``,
``license``, ``license-history``, ``invitations``) live in the
``web_v1/projects/`` package and are guarded there. Mutating endpoints
on this v1 surface that do not yet have a registered Action keep the
legacy ``check_project_access`` membership check so the existing
contract test suite keeps passing.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from echoroo.core.actions import (
    PROJECT_DELETE_ACTION,
    PROJECT_GET_ACTION,
    PROJECT_LICENSE_HISTORY_ACTION,
    PROJECT_LICENSE_UPDATE_ACTION,
    PROJECT_MEMBER_INVITE_ACTION,
    PROJECT_MEMBER_LIST_ACTION,
    PROJECT_MEMBER_REMOVE_ACTION,
    PROJECT_MEMBER_UPDATE_ROLE_ACTION,
    PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION,
    PROJECT_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import ProjectVisibility
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.user import UserRepository
from echoroo.schemas.project import (
    ProjectCreateRequest,
    ProjectLicenseHistoryEntry,
    ProjectLicenseHistoryResponse,
    ProjectLicenseUpdateRequest,
    ProjectMemberAddRequest,
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
    ProjectOverviewResponse,
    ProjectResponse,
    ProjectSummaryListResponse,
    ProjectUpdateRequest,
    RestrictedConfigUpdateRequest,
)
from echoroo.services.license_service import change_license, list_license_history
from echoroo.services.project import (
    ProjectService,
    resolve_current_user_role,
    scrub_owner_email_for_visibility,
)
from echoroo.services.restricted_config_service import (
    trigger_post_commit_side_effects,
    update_restricted_config,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_service(db: DbSession) -> ProjectService:
    """Get project service instance.

    Args:
        db: Database session

    Returns:
        ProjectService instance
    """
    project_repo = ProjectRepository(db)
    user_repo = UserRepository(db)
    return ProjectService(project_repo, user_repo)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


@router.get(
    "",
    response_model=ProjectSummaryListResponse,
    summary="List projects",
    description=(
        "Return projects accessible to the caller as :class:`ProjectSummary` "
        "rows (contracts/projects.yaml:7 covers both ``/api/v1`` and "
        "``/web-api/v1``; the contract list shape is "
        "``ProjectListResponse → ProjectSummary``). The summary deliberately "
        "omits ``restricted_config`` / owner sub-object / timestamps so a "
        "Restricted enumeration call cannot pivot from a row's metadata "
        "into anything else (FR-018 / FR-019 / FR-030). Owner / Admin can "
        "still inspect the full Restricted toggle state via the dedicated "
        "``GET /projects/{id}/restricted-config`` endpoint."
    ),
)
async def list_projects(
    current_user: CurrentUser,
    service: ProjectServiceDep,
    page: int = 1,
    limit: int = 20,
) -> ProjectSummaryListResponse:
    """List all projects accessible by the current user.

    Phase 9 polish round 3 致命 1 (2026-04-27): the response shape is the
    contract-correct :class:`ProjectSummaryListResponse`. The Web UI
    surface (``/web-api/v1/projects/``) and the programmatic surface
    (``/api/v1/projects``) both share the same shared helper
    (:func:`echoroo.services.project.build_project_summaries`) so the
    two routers stay byte-identical.

    Args:
        current_user: Current authenticated user
        service: Project service instance
        page: Page number (default: 1)
        limit: Items per page (default: 20, max: 100)

    Returns:
        Paginated :class:`ProjectSummaryListResponse`.

    Raises:
        401: Not authenticated
    """
    return await service.list_projects(current_user.id, page, limit)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create project",
    description="Create a new project. The creator becomes the project owner.",
)
async def create_project(
    request: ProjectCreateRequest,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectResponse:
    """Create a new project.

    Args:
        request: Project creation data
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Created project

    Raises:
        400: Validation error
        401: Not authenticated
    """
    project = await service.create_project(current_user.id, request)
    await db.commit()
    return project


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project",
    description="Get project details (requires access)",
    responses={
        404: {"description": "Project not found"},
    },
)
async def get_project(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectResponse:
    """Get project details.

    Guarded by :data:`PROJECT_GET_ACTION`
    (:data:`Permission.VIEW_PROJECT_METADATA`). Public / Restricted projects
    allow Guest reads via the canonical matrix; the gate enforces it.

    Args:
        project_id: Project's UUID
        request: FastAPI request (used by ``is_allowed`` to stash stage-1 state)
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Project details

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Project not found
    """
    await gate_action(
        action=PROJECT_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.get_project(current_user.id, project_id)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
    description="Update project settings (admin only)",
    responses={
        403: {"description": "Permission denied"},
    },
)
async def update_project(
    project_id: UUID,
    request: ProjectUpdateRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectResponse:
    """Update project settings.

    Guarded by :data:`PROJECT_UPDATE_ACTION` (:data:`Permission.EDIT_PROJECT`).

    Only project admins (owner or admin role) can update projects.

    Note (FR-003 mutable allowlist):
        ``visibility`` is **immutable** post-creation per spec FR-003 — clients
        attempting to change it should be rejected. Detailed mutable-field
        validation is handled in a follow-up task (see ``web_v1/projects/_core``
        for the canonical Web UI surface). This v1 path operation only enforces
        the central permission gate; field-level validation continues to be
        executed by ``ProjectService.update_project`` against the schema.

    Args:
        project_id: Project's UUID
        request: Update data
        http_request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Updated project

    Raises:
        400: Validation error
        401: Not authenticated
        403: Permission denied
        404: Project not found
    """
    await gate_action(
        action=PROJECT_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    project = await service.update_project(current_user.id, project_id, request)
    await db.commit()
    return project


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete project",
    description="Delete project (owner only)",
)
async def delete_project(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> None:
    """Delete a project.

    Guarded by :data:`PROJECT_DELETE_ACTION`
    (:data:`Permission.DELETE_PROJECT`). Only the project owner has this
    permission per the canonical matrix.

    Args:
        project_id: Project's UUID
        request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Project not found
    """
    await gate_action(
        action=PROJECT_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.delete_project(current_user.id, project_id)
    await db.commit()


# =============================================================================
# Phase 7 polish round 2 (致命 1) — license PATCH + history GET
# =============================================================================
#
# Contract: ``contracts/projects.yaml:325-357``. Both surfaces (Bearer
# under ``/api/v1`` and Cookie+CSRF under ``/web-api/v1``) are exposed
# because the OpenAPI ``security`` block lists both ``apiKeyAuth`` and
# ``sessionCookie+csrfToken``. The Web UI router
# (``api/web_v1/projects/_license.py``) re-uses the same service helpers
# so the business logic stays single-sourced.


@router.patch(
    "/{project_id}/license",
    response_model=ProjectResponse,
    summary="Update project license",
    description=(
        "Change the project's data license (FR-085 / FR-087). Owner / "
        "Admin (MANAGE_LICENSE) only — both roles hold ``MANAGE_LICENSE`` "
        "per the canonical matrix (FR-010 / FR-085). Every PATCH appends "
        "a row to ``project_license_history`` (FR-087); same-license "
        "PATCHes are still recorded so audit consumers see one row per "
        "request."
    ),
)
async def update_project_license(
    project_id: UUID,
    request: ProjectLicenseUpdateRequest,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ProjectResponse:
    """Replace the project license.

    Guarded by :data:`PROJECT_LICENSE_UPDATE_ACTION`
    (:data:`Permission.MANAGE_LICENSE`). The Stage-1 gate enforces the
    Owner / Admin (MANAGE_LICENSE) contract — both roles hold the
    permission per the canonical matrix (FR-010 / FR-085). The service
    layer takes a row-level lock so concurrent PATCHes serialise.

    Args:
        project_id: Target project UUID.
        request: Validated request body — ``license`` is the only field;
            ``ProjectLicenseUpdateRequest`` rejects extras with 422.
        http_request: FastAPI request (used by the Stage-1 gate).
        current_user: Authenticated user.
        db: Async database session.

    Returns:
        The updated :class:`ProjectResponse` so the client can mirror the
        new license without a follow-up GET.

    Raises:
        401: Not authenticated.
        403: Caller lacks ``MANAGE_LICENSE`` (Member / Viewer / non-member).
        404: Project not found.
    """
    project = await gate_action(
        action=PROJECT_LICENSE_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    await change_license(
        session=db,
        project_id=project.id,
        new_license=request.license,
        actor_user_id=current_user.id,
    )
    await db.commit()
    # Refresh so the response reflects the committed value (the prior
    # ``project`` row was pinned inside the ``with_for_update`` SELECT).
    await db.refresh(project)
    response = ProjectResponse.model_validate(project)
    # Phase 9 polish round 2 致命 1 + Major 2 (2026-04-27): scrub
    # owner.email + resolve caller role so the license-PATCH response
    # carries the same privacy contract as the detail surface.
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
    summary="Get project license history",
    description=(
        "Return every ``ProjectLicenseHistory`` row for the project, "
        "sorted oldest-first per OpenAPI contract (``履歴（昇順）``)."
    ),
)
async def get_project_license_history(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ProjectLicenseHistoryResponse:
    """Return the full license-change history.

    Guarded by :data:`PROJECT_LICENSE_HISTORY_ACTION`
    (:data:`Permission.VIEW_PROJECT_METADATA`) so anyone who can see the
    project metadata can also see its license trail (FR-087 immutability
    is at the storage level, not the read level).
    """
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


# =============================================================================
# Phase 8 (T400) — Restricted-config toggle PATCH (programmatic surface)
# =============================================================================
#
# Contract: ``contracts/projects.yaml:174-197`` + ``RestrictedConfig`` schema
# at lines 430-454. Both surfaces (Bearer under ``/api/v1`` and Cookie+CSRF
# under ``/web-api/v1``) are exposed because the OpenAPI ``security`` block
# lists both ``apiKeyAuth`` and ``sessionCookie+csrfToken``. The Web UI
# router (``api/web_v1/projects/_restricted_config.py``) re-uses the same
# service helper so the business logic stays single-sourced.


@router.patch(
    "/{project_id}/restricted-config",
    response_model=ProjectResponse,
    summary="Update Restricted-mode capability toggles",
    description=(
        "Flip per-project Restricted-mode capability flags (FR-014, "
        "FR-020-022, FR-023). Owner / Admin (``EDIT_PROJECT``) only — "
        "matches the canonical matrix. All eight RestrictedConfig keys "
        "are required; unknown keys are 422 (``Extra.forbid``). "
        "``public_location_precision_h3_res`` is constrained to "
        "``Literal[2, 5, 7, 9, 15]`` per FR-021. The toggles only apply "
        "to ``visibility='restricted'`` projects — a PATCH against a "
        "Public project returns 422. Each successful PATCH bumps "
        "``restricted_config_version`` and appends a "
        "``project.restricted_config.update`` row to ``project_audit_log`` "
        "(FR-024 / FR-088). The ``allow_detection_view`` ON->OFF transition "
        "additionally enqueues an asynchronous search-index rebuild "
        "(FR-025a)."
    ),
)
async def update_project_restricted_config(
    project_id: UUID,
    request: RestrictedConfigUpdateRequest,
    http_request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ProjectResponse:
    """Replace the project's Restricted-mode capability toggles.

    Guarded by :data:`PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION`
    (:data:`Permission.EDIT_PROJECT`). The Stage-1 gate enforces the
    Owner / Admin contract — both roles hold the permission per the
    canonical matrix (FR-010). The service layer takes a row-level lock
    so concurrent PATCHes serialise.

    Args:
        project_id: Target project UUID.
        request: Validated request body (``Extra.forbid`` + Literal H3 res).
        http_request: FastAPI request (used by the Stage-1 gate).
        current_user: Authenticated user.
        db: Async database session.

    Returns:
        :class:`ProjectResponse` reflecting the new ``restricted_config`` +
        bumped ``restricted_config_version``.

    Raises:
        401: Not authenticated.
        403: Caller lacks ``EDIT_PROJECT`` (Member / Viewer / non-member).
        404: Project not found.
        422: ``visibility != 'restricted'`` — toggles do not apply.
    """
    project = await gate_action(
        action=PROJECT_RESTRICTED_CONFIG_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )

    if project.visibility != ProjectVisibility.RESTRICTED:
        # Phase 8 polish round 2 Major 1 — emit the dedicated
        # ``ERR_RESTRICTED_CONFIG_NOT_APPLICABLE`` envelope so contract
        # consumers can distinguish "wrong visibility" from generic 422s
        # (mirrors ``ERR_LICENSE_REQUIRED`` from Phase 7). The global
        # :func:`http_exception_handler` passes dict ``detail`` payloads
        # through unchanged.
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
        new_config=request,
        actor_user_id=current_user.id,
        request_id=http_request.headers.get("x-request-id") or "",
        ip=(
            http_request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
            or (http_request.client.host if http_request.client else "")
        ),
        user_agent=http_request.headers.get("user-agent") or "",
    )
    # Phase 8 polish round 2 致命 1 — atomicity contract:
    # snapshot response shape -> commit main TX -> THEN fire audit + Celery.
    # Commit-before-side-effects guarantees a rolled-back main TX cannot
    # leave phantom rows / phantom worker jobs behind.
    response = ProjectResponse.model_validate(outcome.project)
    # Phase 9 polish round 2 致命 1 + Major 2: scrub owner.email + resolve
    # caller role so the restricted-config PATCH response carries the
    # same privacy contract as the detail surface.
    scrub_owner_email_for_visibility(
        response, project=outcome.project, current_user=current_user
    )
    response.current_user_role = await resolve_current_user_role(
        db, project=outcome.project, current_user=current_user
    )
    await db.commit()
    await trigger_post_commit_side_effects(outcome)
    return response


@router.get(
    "/{project_id}/overview",
    response_model=ProjectOverviewResponse,
    summary="Get project overview",
    description="Get aggregated statistics for a project: sites, recording calendar, and totals",
    responses={
        403: {"description": "Permission denied"},
        404: {"description": "Project not found"},
    },
)
async def get_project_overview(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectOverviewResponse:
    """Get aggregated project overview data.

    Guarded by :data:`PROJECT_GET_ACTION`
    (:data:`Permission.VIEW_PROJECT_METADATA`). The overview surfaces the
    same metadata that the per-project ``GET`` exposes, so it shares the
    metadata-read permission.

    Args:
        project_id: Project's UUID
        request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Project overview with sites, recording calendar, and totals

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Project not found
    """
    await gate_action(
        action=PROJECT_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await service.get_project_overview(current_user.id, project_id)


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberResponse],
    summary="List project members",
    description="Get all members of a project",
)
async def list_project_members(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> list[ProjectMemberResponse]:
    """List all members of a project.

    Guarded by :data:`PROJECT_MEMBER_LIST_ACTION`
    (:data:`Permission.MANAGE_MEMBERS`). Only project admins / owner have
    this permission per the canonical matrix.

    Args:
        project_id: Project's UUID
        request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        List of project members

    Raises:
        401: Not authenticated
        403: Permission denied
        404: Project not found
    """
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
    summary="Add project member",
    description="Invite user to project (admin only)",
    responses={
        # Phase 17 contract drift — declare 202 alongside the 201 wire status
        # for parity with ``contracts/projects.yaml`` ``inviteMember`` (FR-055
        # async invite-mail variant). The runtime wire status remains 201
        # (synchronous member create) — clients are not affected.
        202: {"description": "Invitation email queued (FR-055 async path)"},
    },
)
async def add_project_member(
    project_id: UUID,
    request: ProjectMemberAddRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Add a member to a project.

    Guarded by :data:`PROJECT_MEMBER_INVITE_ACTION`
    (:data:`Permission.MANAGE_MEMBERS`).

    Only project admins / owner can add members.

    Args:
        project_id: Project's UUID
        request: Member data (email and role)
        http_request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Created project member

    Raises:
        400: User already member
        401: Not authenticated
        403: Permission denied
        404: Project or user not found
    """
    await gate_action(
        action=PROJECT_MEMBER_INVITE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    member = await service.add_member(current_user.id, project_id, request)
    await db.commit()
    return member


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
    summary="Update member role",
    description="Change member role (admin only)",
)
async def update_project_member_role(
    project_id: UUID,
    user_id: UUID,
    request: ProjectMemberUpdateRequest,
    http_request: Request,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Update a member's role.

    Guarded by :data:`PROJECT_MEMBER_UPDATE_ROLE_ACTION`
    (:data:`Permission.MANAGE_MEMBERS`).

    Only project admins / owner can update member roles. Cannot change the
    owner's role.

    Args:
        project_id: Project's UUID
        user_id: Target member's user ID
        request: New role
        http_request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Updated project member

    Raises:
        400: Cannot change owner role
        401: Not authenticated
        403: Permission denied
        404: Member not found
    """
    await gate_action(
        action=PROJECT_MEMBER_UPDATE_ROLE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    member = await service.update_member_role(current_user.id, project_id, user_id, request)
    await db.commit()
    return member


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove project member",
    description="Remove member from project (admin only)",
)
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> None:
    """Remove a member from a project.

    Guarded by :data:`PROJECT_MEMBER_REMOVE_ACTION`
    (:data:`Permission.MANAGE_MEMBERS`).

    Only project admins / owner can remove members. Cannot remove the owner.

    Args:
        project_id: Project's UUID
        user_id: Member's user ID to remove
        request: FastAPI request used by the Stage-1 gate
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Raises:
        400: Cannot remove owner
        401: Not authenticated
        403: Permission denied
        404: Member not found
    """
    await gate_action(
        action=PROJECT_MEMBER_REMOVE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.remove_member(current_user.id, project_id, user_id)
    await db.commit()
