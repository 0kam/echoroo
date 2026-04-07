"""Base repository with common CRUD patterns."""

from typing import Generic, TypeVar
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic base repository providing common database session management and delete operation.

    Subclasses should define their model class via the generic type parameter.
    Methods like create, update, and get_by_id are intentionally left to subclasses
    because relationship eager-loading options differ per repository.

    Usage::

        class SiteRepository(BaseRepository[Site]):
            model = Site

            async def get_by_id(self, site_id: UUID) -> Site | None:
                result = await self.db.execute(select(Site).where(Site.id == site_id))
                return result.scalar_one_or_none()
    """

    model: type[T]

    def __init__(self, db: AsyncSession) -> None:
        """Initialize repository with database session.

        Args:
            db: SQLAlchemy async session
        """
        self.db = db

    async def delete(self, entity_id: UUID) -> None:
        """Delete a record by primary key ID.

        Args:
            entity_id: UUID primary key of the record to delete
        """
        await self.db.execute(delete(self.model).where(self.model.id == entity_id))  # type: ignore[attr-defined]
        await self.db.flush()
