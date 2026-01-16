"""Site service for business logic."""

from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.site import Site
from echoroo.repositories.project import ProjectRepository
from echoroo.repositories.site import SiteRepository
from echoroo.schemas.site import (
    SiteCreate,
    SiteDetailResponse,
    SiteListResponse,
    SiteResponse,
    SiteUpdate,
)
from echoroo.services.h3_utils import (
    h3_coordinate_uncertainty,
    h3_to_boundary,
    h3_to_center,
    validate_h3_index,
)


class SiteService:
    """Service for site management business logic."""

    def __init__(
        self, site_repo: SiteRepository, project_repo: ProjectRepository
    ) -> None:
        """Initialize service with repositories.

        Args:
            site_repo: Site repository instance
            project_repo: Project repository instance
        """
        self.site_repo = site_repo
        self.project_repo = project_repo

    async def list_sites(
        self, user_id: UUID, project_id: UUID, page: int = 1, page_size: int = 20
    ) -> SiteListResponse:
        """List all sites for a project.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            SiteListResponse with paginated sites

        Raises:
            HTTPException: If access denied
        """
        # Check project access
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to project",
            )

        # Validate pagination
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 100:
            page_size = 20

        sites, total = await self.site_repo.list_by_project(project_id, page, page_size)
        pages = (total + page_size - 1) // page_size

        return SiteListResponse(
            items=[SiteResponse.model_validate(s) for s in sites],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        )

    async def create_site(
        self, user_id: UUID, project_id: UUID, request: SiteCreate
    ) -> SiteResponse:
        """Create a new site in a project.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            request: Site creation data

        Returns:
            Created site

        Raises:
            HTTPException: If not admin, invalid H3 index, or duplicate site
        """
        # Check project access
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required to create sites",
            )

        # Validate H3 index
        is_valid, resolution, error = validate_h3_index(request.h3_index)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid H3 index: {error}",
            )

        # Check for duplicate name
        existing = await self.site_repo.get_by_project_and_name(project_id, request.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Site with this name already exists in project",
            )

        # Check for duplicate H3 index
        existing_h3 = await self.site_repo.get_by_project_and_h3(project_id, request.h3_index)
        if existing_h3:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Site with this H3 index already exists in project",
            )

        # Create site
        site = Site(
            project_id=project_id,
            name=request.name,
            h3_index=request.h3_index,
        )

        created_site = await self.site_repo.create(site)
        return SiteResponse.model_validate(created_site)

    async def get_site(
        self, user_id: UUID, project_id: UUID, site_id: UUID
    ) -> SiteDetailResponse:
        """Get site details.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            site_id: Site's UUID

        Returns:
            Site detail with statistics

        Raises:
            HTTPException: If access denied or site not found
        """
        # Check project access
        has_access = await self.project_repo.has_project_access(project_id, user_id)
        if not has_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to project",
            )

        site = await self.site_repo.get_by_id_with_stats(site_id)
        if not site or site.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Site not found",
            )

        # Get H3 properties
        lat, lng = h3_to_center(site.h3_index)
        boundary = h3_to_boundary(site.h3_index)
        uncertainty = h3_coordinate_uncertainty(site.h3_index)

        # Calculate recording stats from datasets (already eager loaded)
        dataset_count = len(site.datasets) if site.datasets else 0
        recording_count = 0
        total_duration = 0.0

        if site.datasets:
            for dataset in site.datasets:
                if dataset.recordings:
                    recording_count += len(dataset.recordings)
                    for recording in dataset.recordings:
                        if recording.duration is not None:
                            total_duration += float(recording.duration)

        # Build detail response with statistics
        return SiteDetailResponse(
            id=site.id,
            project_id=site.project_id,
            name=site.name,
            h3_index=site.h3_index,
            created_at=site.created_at,
            updated_at=site.updated_at,
            dataset_count=dataset_count,
            recording_count=recording_count,
            total_duration=total_duration,
            latitude=lat,
            longitude=lng,
            coordinate_uncertainty=uncertainty,
            boundary=boundary,
        )

    async def update_site(
        self, user_id: UUID, project_id: UUID, site_id: UUID, request: SiteUpdate
    ) -> SiteResponse:
        """Update site settings.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            site_id: Site's UUID
            request: Update data

        Returns:
            Updated site

        Raises:
            HTTPException: If not admin, site not found, or duplicate site
        """
        # Check admin access
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required to update sites",
            )

        site = await self.site_repo.get_by_id(site_id)
        if not site or site.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Site not found",
            )

        # Update fields if provided
        if request.name is not None:
            # Check for duplicate name
            existing = await self.site_repo.get_by_project_and_name(project_id, request.name)
            if existing and existing.id != site_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Site with this name already exists in project",
                )
            site.name = request.name

        if request.h3_index is not None:
            # Validate H3 index
            is_valid, resolution, error = validate_h3_index(request.h3_index)
            if not is_valid:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid H3 index: {error}",
                )

            # Check for duplicate H3 index
            existing_h3 = await self.site_repo.get_by_project_and_h3(project_id, request.h3_index)
            if existing_h3 and existing_h3.id != site_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Site with this H3 index already exists in project",
                )
            site.h3_index = request.h3_index

        updated_site = await self.site_repo.update(site)
        return SiteResponse.model_validate(updated_site)

    async def delete_site(
        self, user_id: UUID, project_id: UUID, site_id: UUID
    ) -> None:
        """Delete a site and all associated data.

        Args:
            user_id: Current user's UUID
            project_id: Project's UUID
            site_id: Site's UUID

        Raises:
            HTTPException: If not admin or site not found
        """
        # Check admin access
        is_admin = await self.project_repo.is_project_admin(project_id, user_id)
        if not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required to delete sites",
            )

        site = await self.site_repo.get_by_id(site_id)
        if not site or site.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Site not found",
            )

        await self.site_repo.delete(site_id)
