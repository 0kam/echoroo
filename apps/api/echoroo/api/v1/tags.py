"""Tag management API endpoints.

Phase 3 (T121, FR-006 / FR-008 / FR-008a): the tag CREATE path operation now
routes through the central :func:`is_allowed` gate using
:data:`TAG_CREATE_ACTION` (:data:`Permission.CREATE_TAG`). Read endpoints keep
their existing behaviour — they are not yet wrapped because tag visibility is
implicit through the parent project read permission, but the gate hook is in
place via ``_gate`` and can be enabled when the matrix entry is finalised.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select as sa_select

from echoroo.core.actions import TAG_CREATE_ACTION
from echoroo.core.database import DbSession
from echoroo.core.permissions import Action, is_allowed
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import TagCategory
from echoroo.models.project import Project
from echoroo.repositories.tag import TagRepository
from echoroo.schemas.tag import (
    GBIFSuggestion,
    TagCreate,
    TagDetailResponse,
    TagListResponse,
    TagResponse,
    TagStatistic,
    TagUpdate,
)
from echoroo.services.tag import TagService

router = APIRouter(prefix="/projects/{project_id}/tags", tags=["tags"])


def get_tag_service(db: DbSession) -> TagService:
    """Get TagService instance.

    Args:
        db: Database session

    Returns:
        TagService instance
    """
    return TagService(tag_repo=TagRepository(db))


TagServiceDep = Annotated[TagService, Depends(get_tag_service)]


# ---------------------------------------------------------------------------
# Internal helpers (Phase 3 permission gate)
# ---------------------------------------------------------------------------


async def _load_project(db: DbSession, project_id: UUID) -> Project:
    """Load the Project ORM row needed by :func:`is_allowed`."""
    project_result = await db.execute(sa_select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


async def _gate(
    *,
    action: Action,
    project_id: UUID,
    current_user: Any,
    request: Request,
    db: DbSession,
) -> Project:
    """Run the Stage-1 :func:`is_allowed` gate for ``action`` on ``project_id``."""
    project = await _load_project(db, project_id)
    allowed, _ = is_allowed(
        action=action,
        user=current_user,
        project=project,
        request=request,
    )
    if not allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="action denied")
    return project


@router.get(
    "",
    response_model=TagListResponse,
    summary="List tags",
    description="List tags for a project with optional category and search filters",
)
async def list_tags(
    project_id: UUID,
    current_user: CurrentUser,
    service: TagServiceDep,
    category: TagCategory | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> TagListResponse:
    """List tags for a project.

    Read endpoint — kept on the legacy auth-only check pending the Phase 3
    matrix entry for ``tag.list``. The CREATE endpoint below already gates
    through :data:`TAG_CREATE_ACTION`.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Tag service instance
        category: Optional category filter
        search: Optional search string
        page: Page number (default: 1)
        page_size: Items per page (default: 50)
        locale: Locale code used to populate ``vernacular_name`` on each tag

    Returns:
        Paginated list of tags

    Raises:
        401: Not authenticated
    """
    return await service.list_tags(
        project_id=project_id,
        category=category,
        search=search,
        page=page,
        page_size=page_size,
        locale=locale,
    )


@router.post(
    "",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tag",
    description="Create a new tag for a project",
)
async def create_tag(
    project_id: UUID,
    request: TagCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: TagServiceDep,
    db: DbSession,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> TagResponse:
    """Create a new tag.

    Guarded by :data:`TAG_CREATE_ACTION` (:data:`Permission.CREATE_TAG`).

    Args:
        project_id: Project's UUID
        request: Tag creation payload (Pydantic body)
        http_request: FastAPI :class:`Request` used by the gate to stash
            stage-1 state on ``request.state``. Named ``http_request`` to
            avoid colliding with the body parameter ``request``.
        current_user: Current authenticated user
        service: Tag service instance
        db: Database session
        locale: Locale code used to populate ``vernacular_name`` on the response

    Returns:
        Created tag

    Raises:
        401: Not authenticated
        403: Permission denied
        422: Validation error
    """
    await _gate(
        action=TAG_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    tag = await service.create(project_id=project_id, request=request, locale=locale)
    await db.commit()
    return tag


@router.get(
    "/gbif-suggest",
    response_model=list[GBIFSuggestion],
    summary="GBIF species suggestions",
    description="Get species name suggestions from the GBIF API",
)
async def gbif_suggest(
    project_id: UUID,
    current_user: CurrentUser,
    service: TagServiceDep,
    q: str,
    limit: int = 10,
) -> list[GBIFSuggestion]:
    """Get GBIF species suggestions.

    NOTE: This route must appear before /{tag_id} to avoid routing conflicts.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Tag service instance
        q: Search query string (required)
        limit: Maximum suggestions to return (default: 10)

    Returns:
        List of GBIF species suggestions

    Raises:
        401: Not authenticated
    """
    return await service.gbif_suggest(query=q, limit=limit)


@router.get(
    "/statistics",
    response_model=list[TagStatistic],
    summary="Tag usage statistics",
    description="Get tag usage statistics for a project",
)
async def get_statistics(
    project_id: UUID,
    current_user: CurrentUser,
    service: TagServiceDep,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> list[TagStatistic]:
    """Get tag usage statistics.

    NOTE: This route must appear before /{tag_id} to avoid routing conflicts.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Tag service instance
        locale: Locale code used to populate ``vernacular_name`` on each tag

    Returns:
        List of tag statistics ordered by usage count descending

    Raises:
        401: Not authenticated
    """
    return await service.get_statistics(project_id=project_id, locale=locale)


@router.get(
    "/{tag_id}",
    response_model=TagDetailResponse,
    summary="Get tag detail",
    description="Get tag details including child tags",
)
async def get_tag(
    project_id: UUID,
    tag_id: UUID,
    current_user: CurrentUser,
    service: TagServiceDep,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> TagDetailResponse:
    """Get tag by ID with children.

    Args:
        project_id: Project's UUID
        tag_id: Tag's UUID
        current_user: Current authenticated user
        service: Tag service instance
        locale: Locale code used to populate ``vernacular_name`` on the tag
            and each of its children

    Returns:
        Tag detail with children and usage count

    Raises:
        401: Not authenticated
        404: Tag not found
    """
    return await service.get_detail(tag_id=tag_id, locale=locale)


@router.patch(
    "/{tag_id}",
    response_model=TagResponse,
    summary="Update tag",
    description="Update tag name, parent, or common name",
)
async def update_tag(
    project_id: UUID,
    tag_id: UUID,
    request: TagUpdate,
    current_user: CurrentUser,
    service: TagServiceDep,
    db: DbSession,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> TagResponse:
    """Update tag.

    Args:
        project_id: Project's UUID
        tag_id: Tag's UUID
        request: Update data
        current_user: Current authenticated user
        service: Tag service instance
        db: Database session
        locale: Locale code used to populate ``vernacular_name`` on the response

    Returns:
        Updated tag

    Raises:
        401: Not authenticated
        404: Tag not found
    """
    tag = await service.update(tag_id=tag_id, request=request, locale=locale)
    await db.commit()
    return tag


@router.delete(
    "/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete tag",
    description="Delete a tag by ID",
)
async def delete_tag(
    project_id: UUID,
    tag_id: UUID,
    current_user: CurrentUser,
    service: TagServiceDep,
    db: DbSession,
) -> None:
    """Delete tag.

    Args:
        project_id: Project's UUID
        tag_id: Tag's UUID
        current_user: Current authenticated user
        service: Tag service instance
        db: Database session

    Raises:
        401: Not authenticated
        404: Tag not found
    """
    await service.delete(tag_id=tag_id)
    await db.commit()
