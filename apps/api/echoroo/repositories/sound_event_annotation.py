"""SoundEventAnnotation repository for database operations."""

from uuid import UUID

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import selectinload

from echoroo.models.sound_event_annotation import SoundEventAnnotation, sound_event_annotation_tags
from echoroo.repositories.base import BaseRepository


class SoundEventAnnotationRepository(BaseRepository[SoundEventAnnotation]):
    """Repository for SoundEventAnnotation entity operations."""

    model = SoundEventAnnotation

    async def get_by_id(self, sound_event_id: UUID) -> SoundEventAnnotation | None:
        """Get sound event annotation by ID with tags relationship loaded.

        Args:
            sound_event_id: SoundEventAnnotation's UUID

        Returns:
            SoundEventAnnotation instance or None if not found
        """
        result = await self.db.execute(
            select(SoundEventAnnotation)
            .where(SoundEventAnnotation.id == sound_event_id)
            .options(selectinload(SoundEventAnnotation.tags))
        )
        return result.scalar_one_or_none()

    async def list_by_clip_annotation(
        self, clip_annotation_id: UUID
    ) -> list[SoundEventAnnotation]:
        """List all sound event annotations belonging to a clip annotation.

        Args:
            clip_annotation_id: ClipAnnotation's UUID

        Returns:
            List of SoundEventAnnotation instances ordered by creation time
        """
        result = await self.db.execute(
            select(SoundEventAnnotation)
            .where(SoundEventAnnotation.clip_annotation_id == clip_annotation_id)
            .options(selectinload(SoundEventAnnotation.tags))
            .order_by(SoundEventAnnotation.created_at.asc())
        )
        return list(result.scalars().all())

    async def create(self, sound_event: SoundEventAnnotation) -> SoundEventAnnotation:
        """Create a new sound event annotation.

        Args:
            sound_event: SoundEventAnnotation instance to create

        Returns:
            Created sound event annotation instance
        """
        self.db.add(sound_event)
        await self.db.flush()
        await self.db.refresh(sound_event, ["tags"])
        return sound_event

    async def update(self, sound_event: SoundEventAnnotation) -> SoundEventAnnotation:
        """Update an existing sound event annotation.

        Args:
            sound_event: SoundEventAnnotation instance to update

        Returns:
            Updated sound event annotation instance
        """
        await self.db.flush()
        await self.db.refresh(sound_event, ["tags"])
        return sound_event


    async def add_tag(self, sound_event_id: UUID, tag_id: UUID) -> None:
        """Add a tag to a sound event annotation via the association table.

        Args:
            sound_event_id: SoundEventAnnotation's UUID
            tag_id: Tag's UUID
        """
        await self.db.execute(
            insert(sound_event_annotation_tags).values(
                sound_event_annotation_id=sound_event_id,
                tag_id=tag_id,
            )
        )
        await self.db.flush()

    async def remove_tag(self, sound_event_id: UUID, tag_id: UUID) -> None:
        """Remove a tag from a sound event annotation via the association table.

        Args:
            sound_event_id: SoundEventAnnotation's UUID
            tag_id: Tag's UUID
        """
        await self.db.execute(
            delete(sound_event_annotation_tags).where(
                sound_event_annotation_tags.c.sound_event_annotation_id == sound_event_id,
                sound_event_annotation_tags.c.tag_id == tag_id,
            )
        )
        await self.db.flush()
