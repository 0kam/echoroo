"""ConfirmedRegion repository for database operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.confirmed_region import ConfirmedRegion


class ConfirmedRegionRepository:
    """Repository for ConfirmedRegion entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, region_id: UUID) -> ConfirmedRegion | None:
        """Get confirmed region by ID with relationships loaded.

        Args:
            region_id: ConfirmedRegion's UUID

        Returns:
            ConfirmedRegion instance or None if not found
        """
        result = await self.db.execute(
            select(ConfirmedRegion)
            .where(ConfirmedRegion.id == region_id)
            .options(
                selectinload(ConfirmedRegion.recording),
                selectinload(ConfirmedRegion.reviewed_by),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_recording(
        self,
        recording_id: UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ConfirmedRegion], int]:
        """List confirmed regions for a specific recording.

        Args:
            recording_id: Recording's UUID
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (list of confirmed regions, total count)
        """
        conditions = [ConfirmedRegion.recording_id == recording_id]

        count_result = await self.db.execute(
            select(func.count()).select_from(ConfirmedRegion).where(*conditions)
        )
        total: int = count_result.scalar_one()

        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(ConfirmedRegion)
            .where(*conditions)
            .options(
                selectinload(ConfirmedRegion.recording),
                selectinload(ConfirmedRegion.reviewed_by),
            )
            .order_by(ConfirmedRegion.start_time.asc())
            .offset(offset)
            .limit(page_size)
        )
        regions = list(result.scalars().all())

        return regions, total

    async def create(self, region: ConfirmedRegion) -> ConfirmedRegion:
        """Create a new confirmed region.

        Args:
            region: ConfirmedRegion instance to create

        Returns:
            Created confirmed region instance
        """
        self.db.add(region)
        await self.db.flush()
        await self.db.refresh(region, ["recording", "reviewed_by"])
        return region

    async def delete(self, region_id: UUID) -> None:
        """Delete a confirmed region by ID.

        Args:
            region_id: ConfirmedRegion's UUID
        """
        await self.db.execute(delete(ConfirmedRegion).where(ConfirmedRegion.id == region_id))
        await self.db.flush()
