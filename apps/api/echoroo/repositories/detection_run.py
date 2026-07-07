"""DetectionRun repository for database operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionRunType
from echoroo.repositories.base import BaseRepository


class DetectionRunRepository(BaseRepository[DetectionRun]):
    """Repository for DetectionRun entity operations."""

    model = DetectionRun

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

    async def exists_in_project(self, run_id: UUID, project_id: UUID) -> bool:
        """Return True when the detection run belongs to the project."""
        result = await self.db.execute(
            select(DetectionRun.id)
            .where(DetectionRun.id == run_id)
            .where(DetectionRun.project_id == project_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 50,
        dataset_id: UUID | None = None,
        run_type: DetectionRunType | None = None,
    ) -> tuple[list[DetectionRun], int]:
        """List detection runs for a project with pagination.

        Args:
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            dataset_id: Optional filter by dataset UUID
            run_type: Optional filter by run kind (detection / embedding / custom).
                When provided, both the returned items and the total count are
                scoped to that run type so pagination stays per-type accurate.

        Returns:
            Tuple of (list of detection runs, total count)
        """
        conditions = [DetectionRun.project_id == project_id]
        if dataset_id is not None:
            conditions.append(DetectionRun.dataset_id == dataset_id)
        if run_type is not None:
            conditions.append(DetectionRun.run_type == run_type)

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
