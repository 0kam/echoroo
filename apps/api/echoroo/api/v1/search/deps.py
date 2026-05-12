"""Shared dependencies for the search API.

Provides FastAPI dependency factories and type aliases used across
the search sub-modules.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from echoroo.core.actions import SEARCH_SESSION_LIST_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
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
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: SearchServiceDep,
) -> SimilaritySearchService:
    """Verify project access and return the SimilaritySearchService.

    Combines the recurring pattern of (1) authorizing the current user against
    the project and (2) injecting the search service for similarity routes.

    Phase 2A.6 (spec/007): the legacy ``check_project_access`` call is replaced
    by a ``gate_action`` invocation that maps to the broad
    :data:`SEARCH_SESSION_LIST_ACTION` (Permission.SEARCH_WITHIN_PROJECT). All
    search endpoints share this baseline permission, so a single gate at the
    dependency layer is sufficient as Stage-1 enforcement. Endpoint-specific
    SearchGate / service-layer checks continue to apply as defence-in-depth.

    Args:
        project_id: Project UUID (from path)
        request: FastAPI request (gate_action needs it for principal stash)
        current_user: Authenticated user
        db: Database session
        service: Injected SimilaritySearchService

    Returns:
        SimilaritySearchService scoped to the authorized project

    Raises:
        HTTPException: 403 if the user does not have access to the project
    """
    await gate_action(
        action=SEARCH_SESSION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return service


AuthorizedSearchServiceDep = Annotated[
    SimilaritySearchService, Depends(get_authorized_search_service)
]


async def get_authorized_session_service(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    service: SearchSessionServiceDep,
) -> SearchSessionService:
    """Verify project access and return the SearchSessionService.

    Combines the recurring pattern of (1) authorizing the current user against
    the project and (2) injecting the search session service for session routes.

    Phase 2A.6 (spec/007): same migration as
    :func:`get_authorized_search_service` — ``check_project_access`` is
    replaced by ``gate_action(SEARCH_SESSION_LIST_ACTION, ...)``.

    Args:
        project_id: Project UUID (from path)
        request: FastAPI request (gate_action needs it for principal stash)
        current_user: Authenticated user
        db: Database session
        service: Injected SearchSessionService

    Returns:
        SearchSessionService scoped to the authorized project

    Raises:
        HTTPException: 403 if the user does not have access to the project
    """
    await gate_action(
        action=SEARCH_SESSION_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return service


AuthorizedSearchSessionServiceDep = Annotated[
    SearchSessionService, Depends(get_authorized_session_service)
]
