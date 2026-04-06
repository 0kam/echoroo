"""ClipAnnotation repository for database operations."""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.selectable import Select

from echoroo.models.clip_annotation import ClipAnnotation, clip_annotation_tags
from echoroo.models.sound_event_annotation import SoundEventAnnotation
from echoroo.repositories.base import BaseRepository


class ClipAnnotationRepository(BaseRepository[ClipAnnotation]):
    """Repository for ClipAnnotation entity operations."""

    model = ClipAnnotation

    def _base_query(self) -> Select[tuple[ClipAnnotation]]:
        """Build a base select query with all standard relationships loaded.

        Returns:
            SQLAlchemy select statement with eager loading options applied
        """
        return select(ClipAnnotation).options(
            selectinload(ClipAnnotation.tags),
            selectinload(ClipAnnotation.sound_events).selectinload(SoundEventAnnotation.tags),
            selectinload(ClipAnnotation.notes),
        )

    async def get_by_id(self, clip_annotation_id: UUID) -> ClipAnnotation | None:
        """Get clip annotation by ID with tags, sound_events, and notes relationships loaded.

        Args:
            clip_annotation_id: ClipAnnotation's UUID

        Returns:
            ClipAnnotation instance or None if not found
        """
        result = await self.db.execute(
            self._base_query().where(ClipAnnotation.id == clip_annotation_id)
        )
        return result.scalar_one_or_none()

    async def get_by_task_id(self, task_id: UUID) -> ClipAnnotation | None:
        """Get clip annotation by its associated annotation task ID.

        Args:
            task_id: AnnotationTask's UUID

        Returns:
            ClipAnnotation instance or None if not found
        """
        result = await self.db.execute(
            self._base_query().where(ClipAnnotation.task_id == task_id)
        )
        return result.scalar_one_or_none()

    async def create(self, clip_annotation: ClipAnnotation) -> ClipAnnotation:
        """Create a new clip annotation.

        Args:
            clip_annotation: ClipAnnotation instance to create

        Returns:
            Created clip annotation instance
        """
        self.db.add(clip_annotation)
        await self.db.flush()
        await self.db.refresh(clip_annotation, ["tags", "sound_events", "notes"])
        return clip_annotation

    async def add_tag(self, clip_annotation_id: UUID, tag_id: UUID) -> None:
        """Add a tag to a clip annotation via the association table.

        Args:
            clip_annotation_id: ClipAnnotation's UUID
            tag_id: Tag's UUID
        """
        await self.db.execute(
            insert(clip_annotation_tags)
            .values(
                clip_annotation_id=clip_annotation_id,
                tag_id=tag_id,
            )
            .on_conflict_do_nothing()
        )
        await self.db.flush()
        # Expire any cached ClipAnnotation so subsequent get_by_id reloads tags from DB
        self._expire_clip_annotation(clip_annotation_id)

    async def remove_tag(self, clip_annotation_id: UUID, tag_id: UUID) -> None:
        """Remove a tag from a clip annotation via the association table.

        Args:
            clip_annotation_id: ClipAnnotation's UUID
            tag_id: Tag's UUID
        """
        await self.db.execute(
            delete(clip_annotation_tags).where(
                clip_annotation_tags.c.clip_annotation_id == clip_annotation_id,
                clip_annotation_tags.c.tag_id == tag_id,
            )
        )
        await self.db.flush()
        # Expire any cached ClipAnnotation so subsequent get_by_id reloads tags from DB
        self._expire_clip_annotation(clip_annotation_id)

    def _expire_clip_annotation(self, clip_annotation_id: UUID) -> None:
        """Expire a cached ClipAnnotation instance in the session identity map.

        This ensures the next load will fetch fresh data including updated tags.

        Args:
            clip_annotation_id: ClipAnnotation's UUID to expire
        """
        for obj in self.db.sync_session.identity_map.values():
            if isinstance(obj, ClipAnnotation) and obj.id == clip_annotation_id:
                self.db.expire(obj)
                break

    async def update_review(self, clip_annotation: ClipAnnotation) -> ClipAnnotation:
        """Update review fields (review_status, reviewed_by_id, reviewed_at) on a clip annotation.

        Args:
            clip_annotation: ClipAnnotation instance with updated review fields

        Returns:
            Updated clip annotation instance
        """
        await self.db.flush()
        await self.db.refresh(clip_annotation, ["tags", "sound_events", "notes"])
        return clip_annotation
