"""Sites API endpoints."""

from types import SimpleNamespace
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from echoroo.core.actions import (
    SITE_CREATE_ACTION,
    SITE_DELETE_ACTION,
    SITE_GET_ACTION,
    SITE_LIST_ACTION,
    SITE_UPDATE_ACTION,
)
from echoroo.core.database import DbSession
from echoroo.core.permissions import H3_RES_15, Permission, gate_action
from echoroo.core.response_filter import apply_response_filter
from echoroo.middleware.auth import CurrentUser
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.site import SiteRepository
from echoroo.schemas.site import (
    SiteCreate,
    SiteDetailResponse,
    SiteListResponse,
    SiteResponse,
    SiteUpdate,
)
from echoroo.services.site import SiteService

router = APIRouter(prefix="/projects/{project_id}/sites", tags=["sites"])


def get_site_service(db: DbSession) -> SiteService:
    """Get SiteService instance.

    Args:
        db: Database session

    Returns:
        SiteService instance
    """
    return SiteService(SiteRepository(db), ProjectRepository(db))


SiteServiceDep = Annotated[SiteService, Depends(get_site_service)]
SiteResponseT = TypeVar("SiteResponseT", bound=SiteResponse)


def _site_filter_resource(site: SiteResponse) -> SimpleNamespace:
    """Adapt Site responses to the Stage-2 filter's member H3 contract.

    Phase 13 P4 / T807: ``SiteResponse.h3_index_member`` is now the
    canonical field name on the Pydantic shape (matches ORM column +
    spec data-model §3.10), so the adapter passes through the value
    directly. The filter-internal name remains ``h3_index_member`` /
    ``h3_index_member_resolution`` and is unchanged.
    """
    return SimpleNamespace(
        h3_index_member=site.h3_index_member,
        h3_index_member_resolution=site.h3_index_member_resolution,
    )


def _h3_resolution(h3_index: str) -> int:
    try:
        import h3 as _h3
    except ImportError:  # pragma: no cover - h3 is an application dependency
        return H3_RES_15

    try:
        return int(_h3.get_resolution(h3_index))
    except Exception:  # noqa: BLE001 - malformed stored data should not break filtering
        return H3_RES_15


def _filter_site_response(
    *,
    site: SiteResponseT,
    request: Request,
    project: object,
) -> SiteResponseT:
    state = request.state
    effective: frozenset[Permission] = getattr(state, "effective_permissions", frozenset())
    role: str = getattr(state, "normalized_role", "Guest")
    apply_response_filter(
        obj=site,
        effective_permissions=effective,
        normalized_role=role,
        project=project,
        resource=_site_filter_resource(site),
        taxon_sensitivity_map={},
        override_map={},
    )
    return site


@router.get(
    "",
    response_model=SiteListResponse,
    summary="List sites",
    description="Get all sites for a project",
)
async def list_sites(
    project_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: SiteServiceDep,
    db: DbSession,
    page: int = 1,
    page_size: int = 20,
) -> SiteListResponse:
    """List all sites for a project.

    Args:
        project_id: Project's UUID
        current_user: Current authenticated user
        service: Site service instance
        page: Page number (default: 1)
        page_size: Items per page (default: 20, max: 100)

    Returns:
        Paginated list of sites

    Raises:
        401: Not authenticated
        403: Access denied
    """
    project = await gate_action(
        action=SITE_LIST_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    response = await service.list_sites(
        current_user.id,
        project_id,
        page,
        page_size,
        enforce_access=False,
    )
    for item in response.items:
        _filter_site_response(site=item, request=request, project=project)
    return response


@router.post(
    "",
    response_model=SiteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create site",
    description="Create a new site in a project (admin only)",
)
async def create_site(
    project_id: UUID,
    request: SiteCreate,
    http_request: Request,
    current_user: CurrentUser,
    service: SiteServiceDep,
    db: DbSession,
) -> SiteResponse:
    """Create a new site in a project.

    Args:
        project_id: Project's UUID
        request: Site creation data
        current_user: Current authenticated user
        service: Site service instance
        db: Database session

    Returns:
        Created site

    Raises:
        400: Invalid H3 index
        401: Not authenticated
        403: Not project admin
        409: Duplicate site name or H3 index
    """
    project = await gate_action(
        action=SITE_CREATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    site = await service.create_site(
        current_user.id,
        project_id,
        request,
        enforce_access=False,
    )
    await db.commit()
    return _filter_site_response(site=site, request=http_request, project=project)


@router.get(
    "/{site_id}",
    response_model=SiteDetailResponse,
    summary="Get site",
    description="Get site details with statistics",
)
async def get_site(
    project_id: UUID,
    site_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: SiteServiceDep,
    db: DbSession,
) -> SiteDetailResponse:
    """Get site details.

    Args:
        project_id: Project's UUID
        site_id: Site's UUID
        current_user: Current authenticated user
        service: Site service instance

    Returns:
        Site details with statistics

    Raises:
        401: Not authenticated
        403: Access denied
        404: Site not found
    """
    project = await gate_action(
        action=SITE_GET_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    site = await service.get_site(
        current_user.id,
        project_id,
        site_id,
        enforce_access=False,
    )
    return _filter_site_response(site=site, request=request, project=project)


@router.patch(
    "/{site_id}",
    response_model=SiteResponse,
    summary="Update site",
    description="Update site settings (admin only)",
)
async def update_site(
    project_id: UUID,
    site_id: UUID,
    request: SiteUpdate,
    http_request: Request,
    current_user: CurrentUser,
    service: SiteServiceDep,
    db: DbSession,
) -> SiteResponse:
    """Update site settings.

    Args:
        project_id: Project's UUID
        site_id: Site's UUID
        request: Update data
        current_user: Current authenticated user
        service: Site service instance
        db: Database session

    Returns:
        Updated site

    Raises:
        400: Invalid H3 index
        401: Not authenticated
        403: Not project admin
        404: Site not found
        409: Duplicate site name or H3 index
    """
    project = await gate_action(
        action=SITE_UPDATE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=http_request,
        db=db,
    )
    site = await service.update_site(
        current_user.id,
        project_id,
        site_id,
        request,
        enforce_access=False,
    )
    await db.commit()
    return _filter_site_response(site=site, request=http_request, project=project)


@router.delete(
    "/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete site",
    description="Delete site and all associated data (admin only)",
)
async def delete_site(
    project_id: UUID,
    site_id: UUID,
    request: Request,
    current_user: CurrentUser,
    service: SiteServiceDep,
    db: DbSession,
) -> None:
    """Delete a site and all associated data.

    Args:
        project_id: Project's UUID
        site_id: Site's UUID
        current_user: Current authenticated user
        service: Site service instance
        db: Database session

    Raises:
        401: Not authenticated
        403: Not project admin
        404: Site not found
    """
    await gate_action(
        action=SITE_DELETE_ACTION,
        project_id=project_id,
        current_user=current_user,
        request=request,
        db=db,
    )
    await service.delete_site(
        current_user.id,
        project_id,
        site_id,
        enforce_access=False,
    )
    await db.commit()
