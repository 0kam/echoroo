"""Repository for SearchSession database operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from echoroo.models.search_session import SearchSession
from echoroo.repositories.base import BaseRepository


class SearchSessionRepository(BaseRepository[SearchSession]):
    """Repository for SearchSession entity operations."""

    model = SearchSession

    async def exists_in_project(self, session_id: UUID, project_id: UUID) -> bool:
        """Return True when the search session belongs to the project."""
        result = await self.db.execute(
            select(SearchSession.id)
            .where(SearchSession.id == session_id)
            .where(SearchSession.project_id == project_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
