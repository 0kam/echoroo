"""Dataset repository for database operations."""

from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from echoroo.models.dataset import Dataset
from echoroo.models.enums import DatasetStatus, DatasetVisibility


class DatasetRepository:
    """Repository for Dataset entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, dataset_id: UUID) -> Dataset | None:
        """Get dataset by ID with relationships loaded.

        Args:
            dataset_id: Dataset's UUID

        Returns:
            Dataset instance or None if not found
        """
        result = await self.db.execute(
            select(Dataset)
            .where(Dataset.id == dataset_id)
            .options(
                selectinload(Dataset.site),
                selectinload(Dataset.recorder),
                selectinload(Dataset.license),
                selectinload(Dataset.created_by),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_project_and_name(self, project_id: UUID, name: str) -> Dataset | None:
        """Get dataset by project ID and name.

        Args:
            project_id: Project's UUID
            name: Dataset name

        Returns:
            Dataset instance or None if not found
        """
        result = await self.db.execute(
            select(Dataset).where(Dataset.project_id == project_id, Dataset.name == name)
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: UUID,
        page: int = 1,
        page_size: int = 20,
        site_id: UUID | None = None,
        status: DatasetStatus | None = None,
        visibility: DatasetVisibility | None = None,
        search: str | None = None,
    ) -> tuple[list[Dataset], int]:
        """List datasets for a project with pagination and filters.

        Args:
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page
            site_id: Filter by site ID
            status: Filter by status
            visibility: Filter by visibility
            search: Search in name and description

        Returns:
            Tuple of (list of datasets, total count)
        """
        query = select(Dataset).where(Dataset.project_id == project_id)

        # Apply filters
        if site_id:
            query = query.where(Dataset.site_id == site_id)
        if status:
            query = query.where(Dataset.status == status)
        if visibility:
            query = query.where(Dataset.visibility == visibility)
        if search:
            query = query.where(
                or_(
                    Dataset.name.ilike(f"%{search}%"),
                    Dataset.description.ilike(f"%{search}%"),
                )
            )

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total: int = count_result.scalar_one()

        # Get paginated results
        offset = (page - 1) * page_size
        query = query.order_by(Dataset.created_at.desc()).offset(offset).limit(page_size)

        result = await self.db.execute(query)
        datasets = list(result.scalars().all())

        return datasets, total

    async def list_by_site(self, site_id: UUID) -> list[Dataset]:
        """List all datasets for a site.

        Args:
            site_id: Site's UUID

        Returns:
            List of Dataset instances
        """
        result = await self.db.execute(
            select(Dataset).where(Dataset.site_id == site_id).order_by(Dataset.name)
        )
        return list(result.scalars().all())

    async def create(self, dataset: Dataset) -> Dataset:
        """Create a new dataset.

        Args:
            dataset: Dataset instance to create

        Returns:
            Created dataset instance
        """
        self.db.add(dataset)
        await self.db.flush()
        await self.db.refresh(dataset, ["site", "recorder", "license", "created_by"])
        return dataset

    async def update(self, dataset: Dataset) -> Dataset:
        """Update an existing dataset.

        Args:
            dataset: Dataset instance to update

        Returns:
            Updated dataset instance
        """
        await self.db.flush()
        await self.db.refresh(dataset, ["site", "recorder", "license", "created_by"])
        return dataset

    async def delete(self, dataset_id: UUID) -> None:
        """Delete a dataset by ID.

        Args:
            dataset_id: Dataset's UUID
        """
        await self.db.execute(delete(Dataset).where(Dataset.id == dataset_id))
        await self.db.flush()

    async def update_import_status(
        self,
        dataset_id: UUID,
        status: DatasetStatus,
        total_files: int | None = None,
        processed_files: int | None = None,
        error: str | None = None,
    ) -> None:
        """Update dataset import status.

        Args:
            dataset_id: Dataset's UUID
            status: New status
            total_files: Total files discovered
            processed_files: Files processed
            error: Error message if failed
        """
        dataset = await self.get_by_id(dataset_id)
        if dataset:
            dataset.status = status
            if total_files is not None:
                dataset.total_files = total_files
            if processed_files is not None:
                dataset.processed_files = processed_files
            dataset.processing_error = error
            await self.db.flush()
