"""Project repository for database operations."""

from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.enums import ProjectRole
from echoroo.models.project import Project, ProjectMember


class ProjectRepository:
    """Repository for Project entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, project_id: UUID) -> Project | None:
        """Get project by ID with owner relationship loaded.

        Args:
            project_id: Project's UUID

        Returns:
            Project instance or None if not found
        """
        result = await self.db.execute(
            select(Project)
            .where(Project.id == project_id)
            .options(selectinload(Project.owner))
        )
        return result.scalar_one_or_none()

    async def get_accessible_projects(
        self, user_id: UUID, page: int = 1, limit: int = 20
    ) -> tuple[list[Project], int]:
        """Get all projects accessible by a user (owned or member of) with pagination.

        Args:
            user_id: User's UUID
            page: Page number (1-indexed)
            limit: Items per page

        Returns:
            Tuple of (list of projects, total count)
        """
        # Build query for projects where user is owner or member
        query = (
            select(Project)
            .distinct()
            .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                or_(
                    Project.owner_id == user_id,
                    ProjectMember.user_id == user_id,
                )
            )
            .options(selectinload(Project.owner))
            .order_by(Project.created_at.desc())
        )

        # Get total count
        count_query = (
            select(func.count(func.distinct(Project.id)))
            .select_from(Project)
            .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                or_(
                    Project.owner_id == user_id,
                    ProjectMember.user_id == user_id,
                )
            )
        )
        total_result = await self.db.execute(count_query)
        total: int = total_result.scalar_one()

        # Apply pagination
        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        projects = list(result.scalars().unique().all())

        return projects, total

    async def create(self, project: Project) -> Project:
        """Create a new project.

        Args:
            project: Project instance to create

        Returns:
            Created project instance
        """
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project, ["owner"])
        return project

    async def update(self, project: Project) -> Project:
        """Update an existing project.

        Args:
            project: Project instance to update

        Returns:
            Updated project instance
        """
        await self.db.flush()
        await self.db.refresh(project, ["owner"])
        return project

    async def delete(self, project_id: UUID) -> None:
        """Delete a project by ID.

        Args:
            project_id: Project's UUID
        """
        await self.db.execute(delete(Project).where(Project.id == project_id))
        await self.db.flush()

    async def get_member(self, project_id: UUID, user_id: UUID) -> ProjectMember | None:
        """Get a project member by project and user ID.

        Args:
            project_id: Project's UUID
            user_id: User's UUID

        Returns:
            ProjectMember instance or None if not found
        """
        result = await self.db.execute(
            select(ProjectMember)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
            .options(selectinload(ProjectMember.user))
        )
        return result.scalar_one_or_none()

    async def list_members(self, project_id: UUID) -> list[ProjectMember]:
        """List all members of a project.

        Args:
            project_id: Project's UUID

        Returns:
            List of ProjectMember instances
        """
        result = await self.db.execute(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id)
            .options(selectinload(ProjectMember.user))
            .order_by(ProjectMember.joined_at.asc())
        )
        return list(result.scalars().all())

    async def add_member(self, member: ProjectMember) -> ProjectMember:
        """Add a member to a project.

        Args:
            member: ProjectMember instance to create

        Returns:
            Created ProjectMember instance
        """
        self.db.add(member)
        await self.db.flush()
        await self.db.refresh(member, ["user"])
        return member

    async def update_member(self, member: ProjectMember) -> ProjectMember:
        """Update a project member.

        Args:
            member: ProjectMember instance to update

        Returns:
            Updated ProjectMember instance
        """
        await self.db.flush()
        await self.db.refresh(member, ["user"])
        return member

    async def remove_member(self, project_id: UUID, user_id: UUID) -> None:
        """Remove a member from a project.

        Args:
            project_id: Project's UUID
            user_id: User's UUID
        """
        await self.db.execute(
            delete(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        await self.db.flush()

    async def is_project_admin(self, project_id: UUID, user_id: UUID) -> bool:
        """Check if a user is a project admin (owner or admin role).

        Args:
            project_id: Project's UUID
            user_id: User's UUID

        Returns:
            True if user is owner or has admin role
        """
        # Check if user is owner
        project = await self.get_by_id(project_id)
        if project and project.owner_id == user_id:
            return True

        # Check if user has admin role
        member = await self.get_member(project_id, user_id)
        return member is not None and member.role == ProjectRole.ADMIN

    async def is_project_owner(self, project_id: UUID, user_id: UUID) -> bool:
        """Check if a user is the project owner.

        Args:
            project_id: Project's UUID
            user_id: User's UUID

        Returns:
            True if user is the project owner
        """
        project = await self.get_by_id(project_id)
        return project is not None and project.owner_id == user_id

    async def has_project_access(self, project_id: UUID, user_id: UUID) -> bool:
        """Check if a user has access to a project (owner or member).

        Args:
            project_id: Project's UUID
            user_id: User's UUID

        Returns:
            True if user has access to the project
        """
        result = await self.db.execute(
            select(Project)
            .distinct()
            .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                Project.id == project_id,
                or_(
                    Project.owner_id == user_id,
                    ProjectMember.user_id == user_id,
                ),
            )
        )
        return result.scalar_one_or_none() is not None
