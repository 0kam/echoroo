"""Project management endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from echoroo.core.database import DbSession
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.user import UserRepository
from echoroo.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectMemberAddRequest,
    ProjectMemberResponse,
    ProjectMemberUpdateRequest,
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
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> ProjectResponse:
    """Get project details.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Project service instance

    Returns:
        Project details

    Raises:
        401: Not authenticated
        403: Access denied
        404: Project not found
    """
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
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectResponse:
    """Update project settings.

    Only project admins (owner or admin role) can update projects.

    Args:
        project_id: Project's UUID
        request: Update data
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Updated project

    Raises:
        400: Validation error
        401: Not authenticated
        403: Not project admin
        404: Project not found
    """
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
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> None:
    """Delete a project.

    Only the project owner can delete projects.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Raises:
        401: Not authenticated
        403: Not project owner
        404: Project not found
    """
    await service.delete_project(current_user.id, project_id)
    await db.commit()


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberResponse],
    summary="List project members",
    description="Get all members of a project",
)
async def list_project_members(
    project_id: UUID,
    current_user: CurrentUser,
    service: ProjectServiceDep,
) -> list[ProjectMemberResponse]:
    """List all members of a project.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Project service instance

    Returns:
        List of project members

    Raises:
        401: Not authenticated
        403: Access denied
        404: Project not found
    """
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
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Add a member to a project.

    Only project admins can add members.

    Args:
        project_id: Project's UUID
        request: Member data (email and role)
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Created project member

    Raises:
        400: User already member
        401: Not authenticated
        403: Not project admin
        404: Project or user not found
    """
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
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> ProjectMemberResponse:
    """Update a member's role.

    Only project admins can update member roles. Cannot change the owner's role.

    Args:
        project_id: Project's UUID
        user_id: Target member's user ID
        request: New role
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Returns:
        Updated project member

    Raises:
        400: Cannot change owner role
        401: Not authenticated
        403: Not project admin
        404: Member not found
    """
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
    current_user: CurrentUser,
    service: ProjectServiceDep,
    db: DbSession,
) -> None:
    """Remove a member from a project.

    Only project admins can remove members. Cannot remove the owner.

    Args:
        project_id: Project's UUID
        user_id: Member's user ID to remove
        current_user: Current authenticated user
        service: Project service instance
        db: Database session

    Raises:
        400: Cannot remove owner
        401: Not authenticated
        403: Not project admin
        404: Member not found
    """
    await service.remove_member(current_user.id, project_id, user_id)
    await db.commit()
