"""Project tag BFF adapters (spec/009 PR 3a).

Spec/009 PR 3a moves the project Tag CRUD + helper surface from
``/api/v1`` to ``/web-api/v1``. The legacy ``/api/v1/tags.py`` handlers
continue to own service orchestration and locale-aware vernacular name
resolution; the BFF layer only adds the cookie + CSRF gating and
re-uses :func:`gate_action` for the permission decision on mutations.

Endpoints (7):

* GET    ``/{pid}/tags``                  (legacy: auth-only, no Action)
* POST   ``/{pid}/tags``                  → ``TAG_CREATE_ACTION``
* GET    ``/{pid}/tags/gbif-suggest``     (legacy: auth-only, no Action)
* GET    ``/{pid}/tags/statistics``       (legacy: auth-only, no Action)
* GET    ``/{pid}/tags/{tid}``            (legacy: auth-only, no Action)
* PATCH  ``/{pid}/tags/{tid}``            → ``TAG_UPDATE_ACTION``
* DELETE ``/{pid}/tags/{tid}``            → ``TAG_DELETE_ACTION``

Read endpoints are intentionally NOT gated through ``gate_action`` here
because the legacy handlers do not gate them either. Tag visibility is
implicit through the parent project read permission, and introducing a
new gate at the BFF layer would diverge from the legacy contract
mid-migration. A future task may introduce dedicated
``TAG_LIST_ACTION`` / ``TAG_GET_ACTION`` / ``TAG_GBIF_SUGGEST_ACTION`` /
``TAG_STATISTICS_ACTION`` Actions and align both surfaces.

None of these endpoints declare a ``Recording`` / ``Detection`` /
``Site`` response model, so ``scripts/lint_response_filter.py`` does not
require an allowlist entry.

NOTE: the route order — ``gbif-suggest`` and ``statistics`` before
``/{tag_id}`` — must match the legacy router because otherwise FastAPI
will resolve the literal segments against the ``{tag_id}`` UUID pattern.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from echoroo.api.v1 import tags as legacy_tags
from echoroo.core.actions import (
    TAG_CREATE_ACTION,
    TAG_DELETE_ACTION,
    TAG_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.models.enums import TagCategory
from echoroo.schemas.tag import (
    GBIFSuggestion,
    TagCreate,
    TagDetailResponse,
    TagListResponse,
    TagResponse,
    TagStatistic,
    TagUpdate,
)

router = APIRouter()


@router.get(
    "/{project_id}/tags",
    response_model=TagListResponse,
    summary="List tags",
    description="BFF adapter for the legacy project tag list endpoint.",
)
async def list_tags(
    project_id: UUID,
    current_user: CurrentUser,
    service: legacy_tags.TagServiceDep,
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
    """Delegate tag listing to the legacy handler."""
    return await legacy_tags.list_tags(
        project_id=project_id,
        current_user=current_user,
        service=service,
        category=category,
        search=search,
        page=page,
        page_size=page_size,
        locale=locale,
    )


@router.post(
    "/{project_id}/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tag",
    description="BFF adapter for the legacy project tag create endpoint.",
)
async def create_tag(
    project_id: UUID,
    request: TagCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_tags.TagServiceDep,
    db: DbSession,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> TagResponse:
    """Delegate tag create to the legacy handler."""
    await gate_action(
        action=TAG_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_tags.create_tag(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
        locale=locale,
    )


@router.get(
    "/{project_id}/tags/gbif-suggest",
    response_model=list[GBIFSuggestion],
    summary="GBIF species suggestions",
    description="BFF adapter for the legacy GBIF taxonomy suggest endpoint.",
)
async def gbif_suggest(
    project_id: UUID,
    current_user: CurrentUser,
    service: legacy_tags.TagServiceDep,
    q: str,
    limit: int = 10,
) -> list[GBIFSuggestion]:
    """Delegate GBIF suggestions to the legacy handler.

    NOTE: route order — declared BEFORE ``/{tag_id}`` so the literal
    ``gbif-suggest`` segment wins.
    """
    return await legacy_tags.gbif_suggest(
        project_id=project_id,
        current_user=current_user,
        service=service,
        q=q,
        limit=limit,
    )


@router.get(
    "/{project_id}/tags/statistics",
    response_model=list[TagStatistic],
    summary="Tag usage statistics",
    description="BFF adapter for the legacy project tag statistics endpoint.",
)
async def get_statistics(
    project_id: UUID,
    current_user: CurrentUser,
    service: legacy_tags.TagServiceDep,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> list[TagStatistic]:
    """Delegate tag statistics to the legacy handler.

    NOTE: route order — declared BEFORE ``/{tag_id}`` so the literal
    ``statistics`` segment wins.
    """
    return await legacy_tags.get_statistics(
        project_id=project_id,
        current_user=current_user,
        service=service,
        locale=locale,
    )


@router.get(
    "/{project_id}/tags/{tag_id}",
    response_model=TagDetailResponse,
    summary="Get tag detail",
    description="BFF adapter for the legacy project tag detail endpoint.",
)
async def get_tag(
    project_id: UUID,
    tag_id: UUID,
    current_user: CurrentUser,
    service: legacy_tags.TagServiceDep,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> TagDetailResponse:
    """Delegate tag detail to the legacy handler."""
    return await legacy_tags.get_tag(
        project_id=project_id,
        tag_id=tag_id,
        current_user=current_user,
        service=service,
        locale=locale,
    )


@router.patch(
    "/{project_id}/tags/{tag_id}",
    response_model=TagResponse,
    summary="Update tag",
    description="BFF adapter for the legacy project tag update endpoint.",
)
async def update_tag(
    project_id: UUID,
    tag_id: UUID,
    request: TagUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_tags.TagServiceDep,
    db: DbSession,
    locale: str = Query(
        "en",
        pattern="^(en|ja)$",
        description="Locale code for vernacular name resolution (en, ja)",
    ),
) -> TagResponse:
    """Delegate tag update to the legacy handler."""
    await gate_action(
        action=TAG_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_tags.update_tag(
        project_id=project_id,
        tag_id=tag_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
        locale=locale,
    )


@router.delete(
    "/{project_id}/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete tag",
    description="BFF adapter for the legacy project tag delete endpoint.",
)
async def delete_tag(
    project_id: UUID,
    tag_id: UUID,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_tags.TagServiceDep,
    db: DbSession,
) -> None:
    """Delegate tag delete to the legacy handler."""
    await gate_action(
        action=TAG_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    await legacy_tags.delete_tag(
        project_id=project_id,
        tag_id=tag_id,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )
