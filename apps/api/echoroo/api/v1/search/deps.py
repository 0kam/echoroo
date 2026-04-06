"""Shared dependencies for the search API.

Provides FastAPI dependency factories and type aliases used across
the search sub-modules.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from echoroo.core.database import DbSession
from echoroo.services.search import SimilaritySearchService
from echoroo.services.search_session import SearchSessionService, get_search_session_service


def get_search_service(db: DbSession) -> SimilaritySearchService:
    """Get SimilaritySearchService instance.

    Args:
        db: Database session

    Returns:
        SimilaritySearchService instance
    """
    return SimilaritySearchService(db)


SearchServiceDep = Annotated[SimilaritySearchService, Depends(get_search_service)]
SearchSessionServiceDep = Annotated[SearchSessionService, Depends(get_search_session_service)]
