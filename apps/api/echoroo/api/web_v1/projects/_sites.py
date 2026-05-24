"""Project site BFF adapters (spec/009 PR 3a).

Spec/009 PR 3a moves the project Site CRUD surface from ``/api/v1`` to
``/web-api/v1``. The legacy ``/api/v1/sites.py`` handlers continue to own
service orchestration plus the Stage-2 H3 geospatial filter
(``_filter_site_response``); the BFF layer only adds the cookie + CSRF
gating and re-uses :func:`gate_action` for the permission decision.

Endpoints (5):

* GET    ``/{pid}/sites``                  → ``SITE_LIST_ACTION``
* POST   ``/{pid}/sites``                  → ``SITE_CREATE_ACTION``
* GET    ``/{pid}/sites/{sid}``            → ``SITE_GET_ACTION``
* PATCH  ``/{pid}/sites/{sid}``            → ``SITE_UPDATE_ACTION``
* DELETE ``/{pid}/sites/{sid}``            → ``SITE_DELETE_ACTION``

The thin adapters for ``create_site`` / ``update_site`` are intentionally
allowlisted in ``scripts/allowlists/response_filter_allowlist.txt``
alongside the legacy entries: the BFF returns whatever the legacy
handler returns (which already runs the filter), so the lint's
fingerprint matches the BFF function name even though no new filter call
is needed in this file. The allowlist will be retired when the
underlying legacy fix lands (Phase 3 US11 T1xx scope).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status

from echoroo.api.v1 import sites as legacy_sites
from echoroo.core.actions import (
    SITE_CREATE_ACTION,
    SITE_DELETE_ACTION,
    SITE_GET_ACTION,
    SITE_LIST_ACTION,
    SITE_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import gate_action
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.site import (
    SiteCreate,
    SiteDetailResponse,
    SiteListResponse,
    SiteResponse,
    SiteUpdate,
)

router = APIRouter()


@router.get(
    "/{project_id}/sites",
    response_model=SiteListResponse,
    summary="List sites",
    description="BFF adapter for the legacy project site list endpoint.",
)
async def list_sites(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_sites.SiteServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> SiteListResponse:
    """Delegate site listing to the legacy handler."""
    await gate_action(
        action=SITE_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_sites.list_sites(
        project_id=project_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{project_id}/sites",
    response_model=SiteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create site",
    description="BFF adapter for the legacy project site create endpoint.",
)
async def create_site(
    project_id: UUID,
    request: SiteCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_sites.SiteServiceDep,
    db: DbSession,
) -> SiteResponse:
    """Delegate site creation to the legacy handler."""
    await gate_action(
        action=SITE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_sites.create_site(
        project_id=project_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.get(
    "/{project_id}/sites/{site_id}",
    response_model=SiteDetailResponse,
    summary="Get site",
    description="BFF adapter for the legacy project site detail endpoint.",
)
async def get_site(
    project_id: UUID,
    site_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_sites.SiteServiceDep,
    db: DbSession,
) -> SiteDetailResponse:
    """Delegate site detail to the legacy handler."""
    await gate_action(
        action=SITE_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    return await legacy_sites.get_site(
        project_id=project_id,
        site_id=site_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.patch(
    "/{project_id}/sites/{site_id}",
    response_model=SiteResponse,
    summary="Update site",
    description="BFF adapter for the legacy project site update endpoint.",
)
async def update_site(
    project_id: UUID,
    site_id: UUID,
    request: SiteUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: legacy_sites.SiteServiceDep,
    db: DbSession,
) -> SiteResponse:
    """Delegate site update to the legacy handler."""
    await gate_action(
        action=SITE_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    return await legacy_sites.update_site(
        project_id=project_id,
        site_id=site_id,
        request=request,
        http_request=http_request,
        current_user=current_user,
        service=service,
        db=db,
    )


@router.delete(
    "/{project_id}/sites/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete site",
    description="BFF adapter for the legacy project site delete endpoint.",
)
async def delete_site(
    project_id: UUID,
    site_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: legacy_sites.SiteServiceDep,
    db: DbSession,
) -> None:
    """Delegate site delete to the legacy handler."""
    await gate_action(
        action=SITE_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await legacy_sites.delete_site(
        project_id=project_id,
        site_id=site_id,
        request=request,
        current_user=current_user,
        service=service,
        db=db,
    )
