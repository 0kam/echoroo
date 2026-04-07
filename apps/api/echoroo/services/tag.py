"""Tag service for business logic."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from echoroo.core.pagination import paginate
from echoroo.models.enums import TagCategory
from echoroo.models.tag import Tag
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


class TagService:
    """Service for tag management business logic."""

    def __init__(
        self,
        tag_repo: TagRepository,
        gbif_service: object | None = None,
    ) -> None:
        """Initialize service with repository and optional GBIF service.

        Args:
            tag_repo: Tag repository instance
            gbif_service: Optional GBIFService instance; created lazily if None
        """
        self.tag_repo = tag_repo
        self._gbif_service = gbif_service

    async def list_tags(
        self,
        project_id: UUID,
        category: TagCategory | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> TagListResponse:
        """List tags for a project with optional filtering and pagination.

        Args:
            project_id: Project's UUID
            category: Optional tag category filter
            search: Optional search string
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Paginated tag list response
        """
        pagination = paginate(page, page_size)

        tags, total = await self.tag_repo.list_by_project(
            project_id=project_id,
            category=category,
            search=search,
            page=pagination.page,
            page_size=pagination.page_size,
        )

        return TagListResponse(
            items=[TagResponse.model_validate(t) for t in tags],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pagination.total_pages(total),
        )

    async def create(self, project_id: UUID, request: TagCreate) -> TagResponse:
        """Create a new tag.

        Args:
            project_id: Project's UUID
            request: Tag creation data

        Returns:
            Created tag response
        """
        tag = Tag(
            project_id=project_id,
            parent_id=request.parent_id,
            name=request.name,
            category=request.category,
            gbif_taxon_key=request.gbif_taxon_key,
            scientific_name=request.scientific_name,
            common_name=request.common_name,
        )

        created_tag = await self.tag_repo.create(tag)
        return TagResponse.model_validate(created_tag)

    async def get_detail(self, tag_id: UUID) -> TagDetailResponse:
        """Get tag detail with children and usage count.

        Args:
            tag_id: Tag's UUID

        Returns:
            Tag detail response with children and usage_count

        Raises:
            HTTPException: If tag not found
        """
        tag = await self.tag_repo.get_by_id(tag_id)
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )

        children = [TagResponse.model_validate(child) for child in tag.children]

        return TagDetailResponse(
            **TagResponse.model_validate(tag).model_dump(),
            children=children,
            usage_count=0,
        )

    async def update(self, tag_id: UUID, request: TagUpdate) -> TagResponse:
        """Update tag fields.

        Args:
            tag_id: Tag's UUID
            request: Update data

        Returns:
            Updated tag response

        Raises:
            HTTPException: If tag not found
        """
        tag = await self.tag_repo.get_by_id(tag_id)
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )

        if request.name is not None:
            tag.name = request.name
        if request.parent_id is not None:
            tag.parent_id = request.parent_id
        if request.common_name is not None:
            tag.common_name = request.common_name

        updated_tag = await self.tag_repo.update(tag)
        return TagResponse.model_validate(updated_tag)

    async def delete(self, tag_id: UUID) -> None:
        """Delete a tag.

        Args:
            tag_id: Tag's UUID

        Raises:
            HTTPException: If tag not found
        """
        tag = await self.tag_repo.get_by_id(tag_id)
        if not tag:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )

        await self.tag_repo.delete(tag_id)

    async def gbif_suggest(self, query: str, limit: int = 10) -> list[GBIFSuggestion]:
        """Suggest GBIF species matching query string.

        Delegates to GBIFService.search_species() and maps the response to
        GBIFSuggestion schema objects. Returns empty list on any failure.

        Args:
            query: Search query string
            limit: Maximum number of suggestions to return (default: 10)

        Returns:
            List of GBIF species suggestions
        """
        if self._gbif_service is None:
            from echoroo.services.gbif import GBIFService
            self._gbif_service = GBIFService()

        from echoroo.services.gbif import GBIFService as _GBIFService
        gbif: _GBIFService = self._gbif_service  # type: ignore[assignment]

        data = await gbif.search_species(query, limit=limit)

        suggestions: list[GBIFSuggestion] = []
        for item in data:
            try:
                suggestion = GBIFSuggestion(
                    key=item["key"],
                    canonical_name=str(item.get("canonicalName", item.get("scientificName", ""))),
                    scientific_name=str(item.get("scientificName", "")),
                    rank=str(item.get("rank", "UNKNOWN")),
                    kingdom=str(item["kingdom"]) if "kingdom" in item else None,
                    phylum=str(item["phylum"]) if "phylum" in item else None,
                    class_name=str(item["class"]) if "class" in item else None,
                    order=str(item["order"]) if "order" in item else None,
                    family=str(item["family"]) if "family" in item else None,
                )
                suggestions.append(suggestion)
            except (KeyError, ValueError):
                continue

        return suggestions

    async def get_statistics(self, project_id: UUID) -> list[TagStatistic]:
        """Get tag usage statistics for a project.

        Args:
            project_id: Project's UUID

        Returns:
            List of tag statistics ordered by usage count descending
        """
        rows = await self.tag_repo.get_statistics(project_id)
        return [
            TagStatistic(
                tag=TagResponse.model_validate(tag),
                usage_count=usage_count,
            )
            for tag, usage_count in rows
        ]
