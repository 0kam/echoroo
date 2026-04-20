"""Shared dependencies for the search API.

Provides FastAPI dependency factories and type aliases used across
the search sub-modules.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from echoroo.core.database import DbSession
from echoroo.core.permissions import check_project_access
from echoroo.middleware.auth import CurrentUser
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


async def get_authorized_search_service(
    project_id: UUID,
    current_user: CurrentUser,
    db: DbSession,
    service: SearchServiceDep,
) -> SimilaritySearchService:
    """Verify project access and return the SimilaritySearchService.

    Combines the recurring pattern of (1) authorizing the current user against
    the project and (2) injecting the search service for similarity routes.

    Args:
        project_id: Project UUID (from path)
        current_user: Authenticated user
        db: Database session
        service: Injected SimilaritySearchService

    Returns:
        SimilaritySearchService scoped to the authorized project

    Raises:
        HTTPException: 403 if the user does not have access to the project
    """
    await check_project_access(project_id, current_user.id, db)
    return service


AuthorizedSearchServiceDep = Annotated[
    SimilaritySearchService, Depends(get_authorized_search_service)
]
