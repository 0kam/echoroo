"""AnnotationVote repository for vote database operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from echoroo.models.annotation_vote import AnnotationVote
from echoroo.models.enums import VoteType
from echoroo.repositories.base import BaseRepository


class AnnotationVoteRepository(BaseRepository[AnnotationVote]):
    """Repository for AnnotationVote entity operations."""

    model = AnnotationVote

    async def get_by_annotation_and_user(
        self,
        annotation_id: UUID,
        user_id: UUID,
    ) -> AnnotationVote | None:
        """Get an existing vote for a specific annotation and user.

        Args:
            annotation_id: Annotation's UUID
            user_id: User's UUID

        Returns:
            AnnotationVote instance or None if not found
        """
        result = await self.db.execute(
            select(AnnotationVote)
            .where(
                AnnotationVote.annotation_id == annotation_id,
                AnnotationVote.user_id == user_id,
            )
            .options(
                selectinload(AnnotationVote.user),
                selectinload(AnnotationVote.suggested_tag),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_annotation(self, annotation_id: UUID) -> list[AnnotationVote]:
        """Get all votes for an annotation, including user and suggested tag info.

        Args:
            annotation_id: Annotation's UUID

        Returns:
            List of AnnotationVote instances with relationships loaded
        """
        result = await self.db.execute(
            select(AnnotationVote)
            .where(AnnotationVote.annotation_id == annotation_id)
            .options(
                selectinload(AnnotationVote.user),
                selectinload(AnnotationVote.suggested_tag),
            )
            .order_by(AnnotationVote.created_at.asc())
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        annotation_id: UUID,
        user_id: UUID,
        vote: VoteType,
        suggested_tag_id: UUID | None = None,
        note: str | None = None,
    ) -> AnnotationVote:
        """Create or update (upsert) a vote for a user on an annotation.

        If the user has already voted on this annotation, the existing record
        is updated in-place. Otherwise a new vote is created.

        Args:
            annotation_id: Annotation's UUID
            user_id: User's UUID
            vote: Vote value (agree / disagree / unsure)
            suggested_tag_id: Optional alternative species tag suggestion
            note: Optional reason or comment

        Returns:
            Created or updated AnnotationVote instance
        """
        existing = await self.get_by_annotation_and_user(annotation_id, user_id)

        if existing is not None:
            existing.vote = vote
            existing.suggested_tag_id = suggested_tag_id
            existing.note = note
            await self.db.flush()
            await self.db.refresh(existing, ["user", "suggested_tag"])
            return existing

        new_vote = AnnotationVote(
            annotation_id=annotation_id,
            user_id=user_id,
            vote=vote,
            suggested_tag_id=suggested_tag_id,
            note=note,
        )
        self.db.add(new_vote)
        await self.db.flush()
        await self.db.refresh(new_vote, ["user", "suggested_tag"])
        return new_vote

    async def delete_by_annotation_and_user(
        self,
        annotation_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Delete a user's vote on an annotation.

        Args:
            annotation_id: Annotation's UUID
            user_id: User's UUID

        Returns:
            True if a vote was deleted, False if no vote existed
        """
        from sqlalchemy.engine import CursorResult

        cursor: CursorResult[tuple[()]] = await self.db.execute(  # type: ignore[assignment]
            delete(AnnotationVote).where(
                AnnotationVote.annotation_id == annotation_id,
                AnnotationVote.user_id == user_id,
            )
        )
        await self.db.flush()
        return cursor.rowcount > 0

    async def count_by_annotation(self, annotation_id: UUID) -> dict[str, int]:
        """Count votes by type for an annotation.

        Args:
            annotation_id: Annotation's UUID

        Returns:
            Dict with keys 'agree', 'disagree', 'unsure' and their counts
        """
        votes = await self.list_by_annotation(annotation_id)
        counts: dict[str, int] = {
            VoteType.AGREE: 0,
            VoteType.DISAGREE: 0,
            VoteType.UNSURE: 0,
        }
        for v in votes:
            counts[v.vote] += 1
        return counts
