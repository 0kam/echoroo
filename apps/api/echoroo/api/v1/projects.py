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

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select as sa_select

from echoroo.core.actions import (
    PROJECT_DELETE_ACTION,
    PROJECT_GET_ACTION,
    PROJECT_MEMBER_INVITE_ACTION,
    PROJECT_MEMBER_LIST_ACTION,
    PROJECT_MEMBER_REMOVE_ACTION,
    PROJECT_MEMBER_UPDATE_ROLE_ACTION,
    PROJECT_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import Action, is_allowed
from echoroo.middleware.auth import CurrentUser
from echoroo.models.project import Project
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.user import UserRepository
from echoroo.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectMemberAddRequest,
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
    ProjectOverviewResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from echoroo.services.project import ProjectService

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


# ---------------------------------------------------------------------------
# Internal helpers (Phase 3 permission gate — mirrors v1/detections.py)
# ---------------------------------------------------------------------------


async def _load_project(db: DbSession, project_id: UUID) -> Project:
    """Load the Project ORM row needed by :func:`is_allowed`.

    The gate reads ``visibility`` / ``restricted_config`` / ``status`` /
    ``owner_id`` from the row, so a regular ORM load is sufficient.
    """
    project_result = await db.execute(sa_select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


async def _gate(
    *,
    action: Action,
    project_id: UUID,
    current_user: Any,
    request: Request,
    db: DbSession,
) -> Project:
    """Run the Stage-1 :func:`is_allowed` gate for ``action`` on ``project_id``.

    Returns the loaded :class:`Project` row so callers can pass it through to
    the service layer (e.g. for response filtering / restricted_config reads)
    without issuing a second SELECT.
    """
    project = await _load_project(db, project_id)
    allowed, _ = is_allowed(
        action=action,
        user=current_user,
        project=project,
        request=request,
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="action denied")
    return project


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
    description="Get all projects accessible by current user (owned or member of)",
)
async def list_projects(
    current_user: CurrentUser,
    service: ProjectServiceDep,
    page: int = 1,
    limit: int = 20,
) -> ProjectListResponse:
    """List all projects accessible by the current user.

    Args:
        current_user: Current authenticated user
        service: Project service instance
        page: Page number (default: 1)
        limit: Items per page (default: 20, max: 100)

    Returns:
        Paginated list of projects

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
    await _gate(
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
    await _gate(
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
    await _gate(
        action=PROJECT_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.delete_project(current_user.id, project_id)
    await db.commit()


@router.get(
    "/{project_id}/overview",
    response_model=ProjectOverviewResponse,
    summary="Get project overview",
    description="Get aggregated statistics for a project: sites, recording calendar, and totals",
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
    await _gate(
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
    await _gate(
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
    await _gate(
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
    await _gate(
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
    await _gate(
        action=PROJECT_MEMBER_REMOVE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.remove_member(current_user.id, project_id, user_id)
    await db.commit()
