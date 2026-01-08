"""Common mixins for API classes."""

from typing import TYPE_CHECKING

import sqlalchemy.orm as orm
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo import exceptions, models, schemas

if TYPE_CHECKING:
    pass

__all__ = ["UserResolutionMixin"]


class UserResolutionMixin:
    """Mixin for resolving user schemas to user models.

    Provides a common _resolve_user method that converts SimpleUser schemas
    to full User models by fetching from the database.
    """

    async def _resolve_user(
        self,
        session: AsyncSession,
        user: models.User | schemas.SimpleUser | None,
    ) -> models.User | None:
        """Resolve a user schema to a user model.

        Args:
            session: Database session
            user: User model, SimpleUser schema, or None

        Returns:
            User model or None if input was None

        Raises:
            NotFoundError: If SimpleUser references non-existent user
        """
        if user is None:
            return None
        if isinstance(user, models.User):
            return user
        # user is SimpleUser schema
        db_user = await session.get(models.User, user.id)
        if db_user is None:
            raise exceptions.NotFoundError(f"User with id {user.id} not found")
        return db_user
