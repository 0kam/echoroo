"""License repository for database operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.license import License
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
