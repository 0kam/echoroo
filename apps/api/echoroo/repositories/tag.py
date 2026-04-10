"""Tag repository for database operations."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from echoroo.models.clip_annotation import clip_annotation_tags
from echoroo.models.enums import TagCategory
from echoroo.models.sound_event_annotation import sound_event_annotation_tags
from echoroo.models.tag import Tag
from echoroo.repositories.base import BaseRepository


class TagRepository(BaseRepository[Tag]):
    """Repository for Tag entity operations."""

    model = Tag

    async def get_by_id(self, tag_id: UUID) -> Tag | None:
        """Get tag by ID with project and children relationships loaded.

        Args:
            tag_id: Tag's UUID

        Returns:
            Tag instance or None if not found
        """
        result = await self.db.execute(
            select(Tag).where(Tag.id == tag_id).options(
                selectinload(Tag.project),
                selectinload(Tag.children),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: UUID,
        category: TagCategory | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Tag], int]:
        """List tags for a project with optional filtering and pagination.

        Args:
            project_id: Project's UUID
            category: Optional tag category filter
            search: Optional search string to filter by name, scientific_name, or common_name
            page: Page number (1-indexed)
            page_size: Items per page

        Returns:
            Tuple of (list of tags, total count)
        """
        # Build base filter conditions
        conditions = [Tag.project_id == project_id]
        if category is not None:
            conditions.append(Tag.category == category)
        if search is not None:
            search_pattern = f"%{search}%"
            conditions.append(
                or_(
                    Tag.name.ilike(search_pattern),
                    Tag.scientific_name.ilike(search_pattern),
                    Tag.common_name.ilike(search_pattern),
                )
            )

        # Get total count
        count_result = await self.db.execute(
            select(func.count()).select_from(Tag).where(*conditions)
        )
        total: int = count_result.scalar_one()

        # Build paginated query
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Tag)
            .where(*conditions)
            .options(selectinload(Tag.project))
            .order_by(Tag.category.asc(), Tag.name.asc())
            .offset(offset)
            .limit(page_size)
        )
        tags = list(result.scalars().all())

        return tags, total

    async def create(self, tag: Tag) -> Tag:
        """Create a new tag.

        Args:
            tag: Tag instance to create

        Returns:
            Created tag instance
        """
        self.db.add(tag)
        await self.db.flush()
        await self.db.refresh(tag, ["project"])
        return tag

    async def update(self, tag: Tag) -> Tag:
        """Update an existing tag.

        Args:
            tag: Tag instance to update

        Returns:
            Updated tag instance
        """
        await self.db.flush()
        await self.db.refresh(tag, ["project"])
        return tag


    async def find_by_name_and_category(
        self,
        project_id: UUID,
        name: str,
        category: TagCategory,
    ) -> Tag | None:
        """Find a tag by project, name, and category.

        Args:
            project_id: Project UUID to scope the lookup.
            name: Tag name to match.
            category: Tag category to match.

        Returns:
            Tag instance or None if not found.
        """
        result = await self.db.execute(
            select(Tag)
            .where(Tag.project_id == project_id)
            .where(Tag.name == name)
            .where(Tag.category == category)
            .options(selectinload(Tag.project))
        )
        return result.scalar_one_or_none()

    async def get_or_create_species(
        self,
        project_id: UUID,
        scientific_name: str,
        common_name: str,
        taxon_id: UUID | None = None,
    ) -> Tag:
        """Get an existing species tag by scientific name or create a new one.

        Queries by project_id and scientific_name. Creates a new tag with
        category=SPECIES when no match is found.

        If taxon_id is provided and an existing tag has no taxon_id linked,
        the existing tag is updated to link the taxon.

        Args:
            project_id: Project UUID to scope the lookup.
            scientific_name: Scientific species name (e.g. "Turdus merula").
            common_name: Common species name (e.g. "Eurasian Blackbird").
            taxon_id: Optional UUID of the global Taxon record to link.

        Returns:
            Existing or newly created Tag instance.
        """
        result = await self.db.execute(
            select(Tag)
            .where(Tag.project_id == project_id)
            .where(Tag.scientific_name == scientific_name)
            .where(Tag.category == TagCategory.SPECIES)
            .options(selectinload(Tag.project))
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            if taxon_id and existing.taxon_id is None:
                existing.taxon_id = taxon_id
                await self.db.flush()
            return existing

        tag = Tag(
            project_id=project_id,
            name=scientific_name,
            category=TagCategory.SPECIES,
            scientific_name=scientific_name,
            common_name=common_name,
            taxon_id=taxon_id,
        )
        self.db.add(tag)
        await self.db.flush()
        await self.db.refresh(tag, ["project"])
        return tag

    async def get_statistics(self, project_id: UUID) -> list[tuple[Tag, int]]:
        """Get tags with their usage counts across clip and sound event annotations.

        Counts usage from both clip_annotation_tags and sound_event_annotation_tags
        association tables and returns the combined total per tag.

        Args:
            project_id: Project's UUID

        Returns:
            List of (Tag, usage_count) tuples ordered by usage_count descending
        """
        # Count from clip_annotation_tags
        clip_tag_count_subq = (
            select(
                clip_annotation_tags.c.tag_id,
                func.count().label("cnt"),
            )
            .group_by(clip_annotation_tags.c.tag_id)
            .subquery("clip_tag_counts")
        )

        # Count from sound_event_annotation_tags
        sea_tag_count_subq = (
            select(
                sound_event_annotation_tags.c.tag_id,
                func.count().label("cnt"),
            )
            .group_by(sound_event_annotation_tags.c.tag_id)
            .subquery("sea_tag_counts")
        )

        # Combine counts using COALESCE to handle tags with zero usage
        combined_count = (
            func.coalesce(clip_tag_count_subq.c.cnt, 0)
            + func.coalesce(sea_tag_count_subq.c.cnt, 0)
        ).label("usage_count")

        result = await self.db.execute(
            select(Tag, combined_count)
            .outerjoin(clip_tag_count_subq, clip_tag_count_subq.c.tag_id == Tag.id)
            .outerjoin(sea_tag_count_subq, sea_tag_count_subq.c.tag_id == Tag.id)
            .where(Tag.project_id == project_id)
            .options(selectinload(Tag.project))
            .order_by(combined_count.desc(), Tag.name.asc())
        )

        return [(row.Tag, row.usage_count) for row in result.all()]
