"""Tag service for business logic."""

import math
from uuid import UUID

import httpx
from fastapi import HTTPException, status

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

    def __init__(self, tag_repo: TagRepository) -> None:
        """Initialize service with repository.

        Args:
            tag_repo: Tag repository instance
        """
        self.tag_repo = tag_repo

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
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 200:
            page_size = 50

        tags, total = await self.tag_repo.list_by_project(
            project_id=project_id,
            category=category,
            search=search,
            page=page,
            page_size=page_size,
        )

        pages = math.ceil(total / page_size) if total > 0 else 1

        return TagListResponse(
            items=[TagResponse.model_validate(t) for t in tags],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
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

        Calls the GBIF species suggest API and maps the response to
        GBIFSuggestion schema objects. Returns empty list on any failure.

        Args:
            query: Search query string
            limit: Maximum number of suggestions to return (default: 10)

        Returns:
            List of GBIF species suggestions
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.gbif.org/v1/species/suggest",
                    params={"q": query, "limit": limit},
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            return []

        suggestions: list[GBIFSuggestion] = []
        for item in data:
            try:
                suggestion = GBIFSuggestion(
                    key=item["key"],
                    canonical_name=item.get("canonicalName", item.get("scientificName", "")),
                    scientific_name=item.get("scientificName", ""),
                    rank=item.get("rank", "UNKNOWN"),
                    kingdom=item.get("kingdom"),
                    phylum=item.get("phylum"),
                    class_name=item.get("class"),
                    order=item.get("order"),
                    family=item.get("family"),
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
