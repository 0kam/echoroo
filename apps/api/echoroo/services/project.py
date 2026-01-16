"""Project service for business logic."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.project import Project, ProjectMember
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


class ProjectService:
    """Service for project management business logic."""

    def __init__(self, project_repo: ProjectRepository, user_repo: UserRepository) -> None:
        """Initialize service with repositories.

        Args:
            project_repo: Project repository instance
            user_repo: User repository instance
        """
        self.project_repo = project_repo
        self.user_repo = user_repo

    async def list_projects(
        self, user_id: UUID, page: int = 1, limit: int = 20
    ) -> ProjectListResponse:
        """List all projects accessible by the current user.

        Args:
            user_id: Current user's UUID
            page: Page number (1-indexed)
            limit: Items per page (max 100)

        Returns:
            ProjectListResponse with paginated projects
        """
        # Validate pagination parameters
        if page < 1:
            page = 1
        if limit < 1 or limit > 100:
            limit = 20

        projects, total = await self.project_repo.get_accessible_projects(user_id, page, limit)

        return ProjectListResponse(
            items=[ProjectResponse.model_validate(p) for p in projects],
            total=total,
            page=page,
            limit=limit,
        )

    async def create_project(
        self, user_id: UUID, request: ProjectCreateRequest
    ) -> ProjectResponse:
        """Create a new project.

        The user who creates the project becomes the owner.

        Args:
            user_id: User creating the project
            request: Project creation data

        Returns:
            Created project

        Raises:
            HTTPException: If user not found
        """
        # Verify user exists
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Create project
        project = Project(
            name=request.name,
            description=request.description,
            target_taxa=request.target_taxa,
            visibility=request.visibility,
            owner_id=user_id,
        )

        created_project = await self.project_repo.create(project)
        return ProjectResponse.model_validate(created_project)

    async def get_project(self, user_id: UUID, project_id: UUID) -> ProjectResponse:
        """Get project details.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID

        Returns:
            Project details

        Raises:
            HTTPException: If project not found or access denied
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check access (owner or member)
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        return ProjectResponse.model_validate(project)

    async def update_project(
        self, user_id: UUID, project_id: UUID, request: ProjectUpdateRequest
    ) -> ProjectResponse:
        """Update project settings.

        Only project admins (owner or admin role) can update projects.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            request: Update data

        Returns:
            Updated project

        Raises:
            HTTPException: If project not found or user is not admin
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if user is admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project admin",
            )

        # Update fields
        if request.name is not None:
            project.name = request.name
        if request.description is not None:
            project.description = request.description
        if request.target_taxa is not None:
            project.target_taxa = request.target_taxa
        if request.visibility is not None:
            project.visibility = request.visibility

        updated_project = await self.project_repo.update(project)
        return ProjectResponse.model_validate(updated_project)

    async def delete_project(self, user_id: UUID, project_id: UUID) -> None:
        """Delete a project.

        Only the project owner can delete projects.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID

        Raises:
            HTTPException: If project not found or user is not owner
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if user is owner
        if project.owner_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project owner",
            )

        await self.project_repo.delete(project_id)

    async def list_members(self, user_id: UUID, project_id: UUID) -> list[ProjectMemberResponse]:
        """List all members of a project.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID

        Returns:
            List of project members

        Raises:
            HTTPException: If project not found or access denied
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check access
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )

        members = await self.project_repo.list_members(project_id)
        return [ProjectMemberResponse.model_validate(m) for m in members]

    async def add_member(
        self, user_id: UUID, project_id: UUID, request: ProjectMemberAddRequest
    ) -> ProjectMemberResponse:
        """Add a member to a project.

        Only project admins can add members.

        Args:
            user_id: Current user's UUID (must be admin)
            project_id: Project's UUID
            request: Member data (email and role)

        Returns:
            Created project member

        Raises:
            HTTPException: If project not found, user not admin, target user not found,
                          or user already member
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if current user is admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project admin",
            )

        # Find target user by email
        target_user = await self.user_repo.get_by_email(request.email)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        # Check if user is already a member
        existing_member = await self.project_repo.get_member(project_id, target_user.id)
        if existing_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User already member",
            )

        # Create member
        member = ProjectMember(
            user_id=target_user.id,
            project_id=project_id,
            role=request.role,
            joined_at=datetime.now(UTC),
            invited_by_id=user_id,
        )

        created_member = await self.project_repo.add_member(member)
        return ProjectMemberResponse.model_validate(created_member)

    async def update_member_role(
        self,
        user_id: UUID,
        project_id: UUID,
        member_user_id: UUID,
        request: ProjectMemberUpdateRequest,
    ) -> ProjectMemberResponse:
        """Update a member's role.

        Only project admins can update member roles. Cannot change the owner's role.

        Args:
            user_id: Current user's UUID (must be admin)
            project_id: Project's UUID
            member_user_id: Target member's user ID
            request: New role

        Returns:
            Updated project member

        Raises:
            HTTPException: If project not found, user not admin, member not found,
                          or attempting to change owner role
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if current user is admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project admin",
            )

        # Cannot change owner role (owner is not in members table)
        if project.owner_id == member_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change owner role",
            )

        # Get member
        member = await self.project_repo.get_member(project_id, member_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )

        # Update role
        member.role = request.role
        updated_member = await self.project_repo.update_member(member)
        return ProjectMemberResponse.model_validate(updated_member)

    async def remove_member(
        self, user_id: UUID, project_id: UUID, member_user_id: UUID
    ) -> None:
        """Remove a member from a project.

        Only project admins can remove members. Cannot remove the owner.

        Args:
            user_id: Current user's UUID (must be admin)
            project_id: Project's UUID
            member_user_id: Member's user ID to remove

        Raises:
            HTTPException: If project not found, user not admin, member not found,
                          or attempting to remove owner
        """
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Check if current user is admin
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not project admin",
            )

        # Cannot remove owner
        if project.owner_id == member_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove owner",
            )

        # Check if member exists
        member = await self.project_repo.get_member(project_id, member_user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found",
            )

        await self.project_repo.remove_member(project_id, member_user_id)
