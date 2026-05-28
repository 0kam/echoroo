"""License repository for database operations."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.dataset import Dataset
from echoroo.models.license import License
from echoroo.models.project import Project
from echoroo.schemas.license import LicenseCreate, LicenseUpdate


class LicenseRepository:
    """Repository for License entity operations."""

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def get_by_id(self, license_id: str) -> License | None:
        """Get license by ID.

        Args:
            license_id: License identifier code

        Returns:
            License instance or None if not found
        """
        result = await self.db.execute(select(License).where(License.id == license_id))
        return result.scalar_one_or_none()

    async def get_all(self) -> list[License]:
        """Get all licenses.

        Returns:
            List of all licenses ordered by short_name
        """
        result = await self.db.execute(select(License).order_by(License.short_name))
        return list(result.scalars().all())

    async def list_all(self) -> list[License]:
        """Return every license ordered by ``short_name`` ascending.

        spec/012 alias for :meth:`get_all`. The public list endpoint
        (``GET /api/v1/licenses`` + ``GET /web-api/v1/licenses``)
        depends on the ASC ordering so the UI dropdown is stable across
        requests; see ``specs/012-license-master-unification/contracts/
        web-licenses.yaml`` for the contract.
        """
        return await self.get_all()

    async def count_dependents(self, license_id: str) -> tuple[int, int]:
        """Return ``(project_count, dataset_count)`` for a license.

        spec/012 FR-006 / FR-012 / FR-015 require the admin DELETE
        handler to surface BOTH counts when refusing a deletion. The two
        queries are intentionally separate ``SELECT COUNT(*)`` rather
        than a single UNION / JOIN so each table can use its own
        ``ix_*_license_id`` index without the query planner falling back
        to a sequential scan on the larger join shape. The two counts
        are returned as a tuple to keep the call site noise-free.

        The pair is computed in a single transaction context but two
        separate statements — concurrent INSERTs between the two
        ``COUNT(*)`` calls can therefore appear "skewed" by one row in
        a worst-case race. Callers MUST treat the pair as advisory and
        rely on the FK ``ON DELETE RESTRICT`` as the authoritative gate
        (see :func:`echoroo.services.license.LicenseService.delete_license`
        for the re-count fallback).
        """
        project_q = await self.db.execute(
            select(func.count()).select_from(Project).where(
                Project.license_id == license_id
            )
        )
        project_count = int(project_q.scalar_one() or 0)

        dataset_q = await self.db.execute(
            select(func.count()).select_from(Dataset).where(
                Dataset.license_id == license_id
            )
        )
        dataset_count = int(dataset_q.scalar_one() or 0)

        return project_count, dataset_count

    async def create(self, data: LicenseCreate) -> License:
        """Create a new license.

        Args:
            data: License creation data

        Returns:
            Created license instance
        """
        license_obj = License(
            id=data.id,
            name=data.name,
            short_name=data.short_name,
            url=data.url,
            description=data.description,
        )
        self.db.add(license_obj)
        await self.db.flush()
        await self.db.refresh(license_obj)
        return license_obj

    async def update(self, license_id: str, data: LicenseUpdate) -> License | None:
        """Update an existing license.

        Args:
            license_id: License identifier code
            data: License update data

        Returns:
            Updated license instance or None if not found
        """
        license_obj = await self.get_by_id(license_id)
        if not license_obj:
            return None

        # Update only provided fields
        if data.name is not None:
            license_obj.name = data.name

        if data.short_name is not None:
            license_obj.short_name = data.short_name

        if data.url is not None:
            license_obj.url = data.url

        if data.description is not None:
            license_obj.description = data.description

        await self.db.flush()
        await self.db.refresh(license_obj)
        return license_obj

    async def delete(self, license_id: str) -> bool:
        """Delete a license.

        Args:
            license_id: License identifier code

        Returns:
            True if license was deleted, False if not found
        """
        license_obj = await self.get_by_id(license_id)
        if not license_obj:
            return False

        await self.db.delete(license_obj)
        await self.db.flush()
        return True
