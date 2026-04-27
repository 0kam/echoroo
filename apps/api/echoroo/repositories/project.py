"""Project repository for database operations."""

from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete, func, or_, select
from sqlalchemy.orm import selectinload

from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from echoroo.repositories.base import BaseRepository


class ProjectRepository(BaseRepository[Project]):
    """Repository for Project entity operations."""

    model = Project

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
        """Get all projects accessible by a user with pagination.

        Phase 9 / T410 / FR-019: an authenticated caller sees the union of:

            * projects they own,
            * projects where they are an active member,
            * **Public + Active** projects (FR-016 enumeration baseline),
            * **Restricted + Active** projects (FR-019 meta-only enumeration).

        The first two clauses keep Dormant / Archived projects accessible to
        their members; the last two open up cross-project discovery for
        non-members. Response-level scrubbing of ``restricted_config``
        happens in the endpoint layer (see ``api/web_v1/projects/_core.py``)
        so the repository stays free of role / response shape concerns.

        Args:
            user_id: User's UUID
            page: Page number (1-indexed)
            limit: Items per page

        Returns:
            Tuple of (list of projects, total count)
        """
        # FR-019 visibility surface: Public + Active OR Restricted + Active.
        # FR-016 / FR-019 / FR-018 collapse to the same SQL clause for the
        # list endpoint because the response filter handles the per-row
        # meta scrub downstream.
        public_or_restricted_active = (
            Project.visibility.in_(
                [ProjectVisibility.PUBLIC, ProjectVisibility.RESTRICTED]
            )
        ) & (Project.status == ProjectStatus.ACTIVE)

        # Build query for projects where user is owner / member OR the
        # project is publicly enumerable per FR-019.
        #
        # Phase 9 polish round 2 Major 3: the membership clause must filter
        # ``ProjectMember.removed_at IS NULL`` so a user who was removed
        # from a project no longer sees it under the membership branch.
        # Without this clause, ``ProjectMember`` rows that were soft-
        # deleted via the ``DELETE /members/{id}`` endpoint would still
        # surface their old projects in this list (the same partial-unique
        # invariant is encoded in ``models/project.py:215``
        # ``ux_project_members_active``).
        active_membership = (ProjectMember.user_id == user_id) & (
            ProjectMember.removed_at.is_(None)
        )

        query = (
            select(Project)
            .distinct()
            .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                or_(
                    Project.owner_id == user_id,
                    active_membership,
                    public_or_restricted_active,
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
                    active_membership,
                    public_or_restricted_active,
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

    async def get_overview_sites(
        self, project_id: UUID
    ) -> list[Row[Any]]:
        """Get site summaries for project overview.

        Returns site id, name, h3_index, dataset_count, recording_count per site.

        Args:
            project_id: Project's UUID

        Returns:
            List of tuples: (id, name, h3_index, dataset_count, recording_count)
        """
        result = await self.db.execute(
            select(
                Site.id,
                Site.name,
                Site.h3_index,
                func.count(func.distinct(Dataset.id)).label("dataset_count"),
                func.count(Recording.id).label("recording_count"),
            )
            .select_from(Site)
            .outerjoin(Dataset, Dataset.site_id == Site.id)
            .outerjoin(Recording, Recording.dataset_id == Dataset.id)
            .where(Site.project_id == project_id)
            .group_by(Site.id, Site.name, Site.h3_index)
            .order_by(Site.name)
        )
        return list(result.all())

    async def get_recording_calendar(
        self, project_id: UUID
    ) -> list[Row[Any]]:
        """Get monthly recording activity for a project.

        Args:
            project_id: Project's UUID

        Returns:
            List of tuples: (year, month, site_count, recording_count)
        """
        year_col = func.extract("year", Recording.datetime).label("year")
        month_col = func.extract("month", Recording.datetime).label("month")

        result = await self.db.execute(
            select(
                year_col,
                month_col,
                func.count(func.distinct(Site.id)).label("site_count"),
                func.count(Recording.id).label("recording_count"),
            )
            .select_from(Recording)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .join(Site, Dataset.site_id == Site.id)
            .where(
                Dataset.project_id == project_id,
                Recording.datetime.is_not(None),
            )
            .group_by(year_col, month_col)
            .order_by(year_col, month_col)
        )
        return list(result.all())

    async def get_overview_totals(
        self, project_id: UUID
    ) -> tuple[int, int, float]:
        """Get aggregate totals for a project overview.

        Args:
            project_id: Project's UUID

        Returns:
            Tuple of (total_recordings, total_sites, total_duration)
        """
        result = await self.db.execute(
            select(
                func.count(Recording.id).label("total_recordings"),
                func.count(func.distinct(Site.id)).label("total_sites"),
                func.coalesce(func.sum(Recording.duration), 0.0).label("total_duration"),
            )
            .select_from(Recording)
            .join(Dataset, Recording.dataset_id == Dataset.id)
            .join(Site, Dataset.site_id == Site.id)
            .where(Dataset.project_id == project_id)
        )
        row = result.one()
        return int(row.total_recordings), int(row.total_sites), float(row.total_duration)

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
        return member is not None and member.role == ProjectMemberRole.ADMIN

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
        # Phase 9 polish round 2 Major 3: only count active memberships
        # (``removed_at IS NULL``) so a user who was previously removed
        # from a project no longer satisfies "has project access".
        result = await self.db.execute(
            select(Project)
            .distinct()
            .outerjoin(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                Project.id == project_id,
                or_(
                    Project.owner_id == user_id,
                    (ProjectMember.user_id == user_id)
                    & (ProjectMember.removed_at.is_(None)),
                ),
            )
        )
        return result.scalar_one_or_none() is not None
