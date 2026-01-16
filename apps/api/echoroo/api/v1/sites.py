"""Sites API endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from echoroo.core.database import DbSession
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


@router.get(
    "",
    response_model=SiteListResponse,
    summary="List sites",
    description="Get all sites for a project",
)
async def list_sites(
    project_id: UUID,
    current_user: CurrentUser,
    service: SiteServiceDep,
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
    return await service.list_sites(current_user.id, project_id, page, page_size)


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
    site = await service.create_site(current_user.id, project_id, request)
    await db.commit()
    return site


@router.get(
    "/{site_id}",
    response_model=SiteDetailResponse,
    summary="Get site",
    description="Get site details with statistics",
)
async def get_site(
    project_id: UUID,
    site_id: UUID,
    current_user: CurrentUser,
    service: SiteServiceDep,
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
    return await service.get_site(current_user.id, project_id, site_id)


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
    site = await service.update_site(current_user.id, project_id, site_id, request)
    await db.commit()
    return site


@router.delete(
    "/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete site",
    description="Delete site and all associated data (admin only)",
)
async def delete_site(
    project_id: UUID,
    site_id: UUID,
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
    await service.delete_site(current_user.id, project_id, site_id)
    await db.commit()
