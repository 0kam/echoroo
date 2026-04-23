"""Tag service for business logic."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

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
from echoroo.services.vernacular import resolve_vernacular_names


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
        locale: str = "en",
    ) -> TagListResponse:
        """List tags for a project with optional filtering and pagination.

        Args:
            project_id: Project's UUID
            category: Optional tag category filter
            search: Optional search string
            page: Page number (1-indexed)
            page_size: Items per page
            locale: Locale code used to populate ``vernacular_name`` on each tag

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

        vernacular_map = await resolve_vernacular_names(
            self.tag_repo.db,
            [t.taxon_id for t in tags],
            locale,
        )

        return TagListResponse(
            items=[self._to_response(t, vernacular_map) for t in tags],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pagination.total_pages(total),
        )

    @staticmethod
    def _to_response(
        tag: Tag,
        vernacular_map: dict[UUID, str] | None = None,
    ) -> TagResponse:
        """Convert a Tag model to a TagResponse with optional vernacular name.

        Args:
            tag: Tag ORM instance
            vernacular_map: Optional ``{taxon_id: name}`` mapping used to
                populate ``TagResponse.vernacular_name``. When ``None`` or the
                tag has no ``taxon_id`` / no matching entry, the field stays
                ``None``.

        Returns:
            TagResponse schema instance
        """
        response = TagResponse.model_validate(tag)
        if vernacular_map is not None and tag.taxon_id is not None:
            response.vernacular_name = vernacular_map.get(tag.taxon_id)
        return response

    async def create(
        self,
        project_id: UUID,
        request: TagCreate,
        locale: str = "en",
    ) -> TagResponse:
        """Create a new tag.

        If a tag with the same project_id + name + category already exists
        (IntegrityError from unique constraint), return the existing tag
        instead of raising an error.

        Args:
            project_id: Project's UUID
            request: Tag creation data
            locale: Locale code used to populate ``vernacular_name`` on the response

        Returns:
            Created or existing tag response
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

        try:
            created_tag = await self.tag_repo.create(tag)
        except IntegrityError:
            await self.tag_repo.db.rollback()
            # Duplicate tag — return the existing one
            existing = await self.tag_repo.find_by_name_and_category(
                project_id=project_id,
                name=request.name,
                category=request.category,
            )
            if existing:
                vernacular_map = await resolve_vernacular_names(
                    self.tag_repo.db, [existing.taxon_id], locale
                )
                return self._to_response(existing, vernacular_map)
            raise

        vernacular_map = await resolve_vernacular_names(
            self.tag_repo.db, [created_tag.taxon_id], locale
        )
        return self._to_response(created_tag, vernacular_map)

    async def get_detail(
        self,
        tag_id: UUID,
        locale: str = "en",
    ) -> TagDetailResponse:
        """Get tag detail with children and usage count.

        Args:
            tag_id: Tag's UUID
            locale: Locale code used to populate ``vernacular_name`` on the tag
                and each of its children

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

        taxon_ids: list[UUID | None] = [tag.taxon_id]
        taxon_ids.extend(child.taxon_id for child in tag.children)
        vernacular_map = await resolve_vernacular_names(
            self.tag_repo.db, taxon_ids, locale
        )

        children = [self._to_response(child, vernacular_map) for child in tag.children]

        return TagDetailResponse(
            **self._to_response(tag, vernacular_map).model_dump(),
            children=children,
            usage_count=0,
        )

    async def update(
        self,
        tag_id: UUID,
        request: TagUpdate,
        locale: str = "en",
    ) -> TagResponse:
        """Update tag fields.

        Args:
            tag_id: Tag's UUID
            request: Update data
            locale: Locale code used to populate ``vernacular_name`` on the response

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
        vernacular_map = await resolve_vernacular_names(
            self.tag_repo.db, [updated_tag.taxon_id], locale
        )
        return self._to_response(updated_tag, vernacular_map)

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

    async def get_statistics(
        self,
        project_id: UUID,
        locale: str = "en",
    ) -> list[TagStatistic]:
        """Get tag usage statistics for a project.

        Args:
            project_id: Project's UUID
            locale: Locale code used to populate ``vernacular_name`` on each tag

        Returns:
            List of tag statistics ordered by usage count descending
        """
        rows = await self.tag_repo.get_statistics(project_id)
        vernacular_map = await resolve_vernacular_names(
            self.tag_repo.db,
            [tag.taxon_id for tag, _ in rows],
            locale,
        )
        return [
            TagStatistic(
                tag=self._to_response(tag, vernacular_map),
                usage_count=usage_count,
            )
            for tag, usage_count in rows
        ]
