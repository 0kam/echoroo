"""DetectionRun repository for database operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.detection_run import DetectionRun


class DetectionRunRepository:
    """Repository for DetectionRun entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, run_id: UUID) -> DetectionRun | None:
        """Get detection run by ID with relationships loaded.

        Args:
            run_id: DetectionRun's UUID

        Returns:
            DetectionRun instance or None if not found
        """
        result = await self.db.execute(
            select(DetectionRun)
            .where(DetectionRun.id == run_id)
            .options(
                selectinload(DetectionRun.project),
                selectinload(DetectionRun.dataset),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[DetectionRun], int]:
        """List detection runs for a project with pagination.

        Args:
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (list of detection runs, total count)
        """
        conditions = [DetectionRun.project_id == project_id]

        count_result = await self.db.execute(
            select(func.count()).select_from(DetectionRun).where(*conditions)
        )
        total: int = count_result.scalar_one()

        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(DetectionRun)
            .where(*conditions)
            .options(
                selectinload(DetectionRun.project),
                selectinload(DetectionRun.dataset),
            )
            .order_by(DetectionRun.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        runs = list(result.scalars().all())

        return runs, total

    async def create(self, run: DetectionRun) -> DetectionRun:
        """Create a new detection run.

        Args:
            run: DetectionRun instance to create

        Returns:
            Created detection run instance
        """
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run, ["project", "dataset"])
        return run

    async def update(self, run: DetectionRun) -> DetectionRun:
        """Update an existing detection run.

        Args:
            run: DetectionRun instance with updated fields

        Returns:
            Updated detection run instance
        """
        await self.db.flush()
        await self.db.refresh(run, ["project", "dataset"])
        return run

    async def delete(self, run_id: UUID) -> None:
        """Delete a detection run by ID.

        Args:
            run_id: DetectionRun's UUID
        """
        await self.db.execute(delete(DetectionRun).where(DetectionRun.id == run_id))
        await self.db.flush()
