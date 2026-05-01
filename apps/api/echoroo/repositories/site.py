"""Site repository for database operations."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from echoroo.models.site import Site
from echoroo.repositories.base import BaseRepository


class SiteRepository(BaseRepository[Site]):
    """Repository for Site entity operations."""

    model = Site

    async def get_by_id(self, site_id: UUID) -> Site | None:
        """Get site by ID.

        Args:
            site_id: Site's UUID

        Returns:
            Site instance or None if not found
        """
        result = await self.db.execute(select(Site).where(Site.id == site_id))
        return result.scalar_one_or_none()

    async def get_by_id_with_stats(self, site_id: UUID) -> Site | None:
        """Get site by ID with datasets and recordings loaded.

        Args:
            site_id: Site's UUID

        Returns:
            Site instance with relationships loaded, or None if not found
        """
        from echoroo.models.dataset import Dataset

        result = await self.db.execute(
            select(Site)
            .where(Site.id == site_id)
            .options(selectinload(Site.datasets).selectinload(Dataset.recordings))
        )
        return result.scalar_one_or_none()

    async def get_by_project_and_name(self, project_id: UUID, name: str) -> Site | None:
        """Get site by project ID and name.

        Args:
            project_id: Project's UUID
            name: Site name

        Returns:
            Site instance or None if not found
        """
        result = await self.db.execute(
            select(Site).where(Site.project_id == project_id, Site.name == name)
        )
        return result.scalar_one_or_none()

    async def get_by_project_and_h3(self, project_id: UUID, h3_index_member: str) -> Site | None:
        """Get site by project ID and H3 member cell.

        Phase 13 P4 / T807: column ``h3_index_member`` matches the spec
        data-model §3.10 / FR-028 canonical name.

        Args:
            project_id: Project's UUID
            h3_index_member: H3 cell identifier at member precision

        Returns:
            Site instance or None if not found
        """
        result = await self.db.execute(
            select(Site).where(
                Site.project_id == project_id,
                Site.h3_index_member == h3_index_member,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self, project_id: UUID, page: int = 1, page_size: int = 20
    ) -> tuple[list[Site], int]:
        """List sites for a project with pagination.

        Args:
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (list of sites, total count)
        """
        # Get total count
        count_result = await self.db.execute(
            select(func.count()).select_from(Site).where(Site.project_id == project_id)
        )
        total: int = count_result.scalar_one()

        # Get paginated results
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Site)
            .where(Site.project_id == project_id)
            .order_by(Site.name)
            .offset(offset)
            .limit(page_size)
        )
        sites = list(result.scalars().all())

        return sites, total

    async def create(self, site: Site) -> Site:
        """Create a new site.

        Args:
            site: Site instance to create

        Returns:
            Created site instance
        """
        self.db.add(site)
        await self.db.flush()
        await self.db.refresh(site)
        return site

    async def update(self, site: Site) -> Site:
        """Update an existing site.

        Args:
            site: Site instance to update

        Returns:
            Updated site instance
        """
        await self.db.flush()
        await self.db.refresh(site)
        return site

