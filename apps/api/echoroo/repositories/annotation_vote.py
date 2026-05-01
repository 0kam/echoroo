"""AnnotationVote repository for vote database operations.

Phase 13 P1.5 (T804): the model now mirrors the DB column shape exactly
(``voter_user_id`` instead of ``user_id``, required ``project_id``, and a
``smallint`` ``vote`` column). The repository accepts the legacy ``user_id``
and :class:`VoteType` keyword arguments for caller compatibility and
translates them at the persistence boundary.

Recording-level vote fields (``signal_quality`` / ``suggested_tag_id`` /
``note``) are accepted as keyword arguments for caller compatibility but
are NOT persisted — the columns no longer exist on the DB-truth schema.
They will return when Phase 14+ introduces the ``recording_annotations``
table. Callers receive a ``None`` echo via the response models.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select

from echoroo.models.annotation_vote import (
    AnnotationVote,
    vote_from_int,
    vote_to_int,
)
from echoroo.models.enums import (
    AnnotationVoteSource,
    ProjectMemberRole,
    SignalQuality,
    VoteType,
)
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
            user_id: Voter's UUID (mapped to ``voter_user_id`` column)

        Returns:
            AnnotationVote instance or None if not found
        """
        result = await self.db.execute(
            select(AnnotationVote).where(
                AnnotationVote.annotation_id == annotation_id,
                AnnotationVote.voter_user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_annotation(self, annotation_id: UUID) -> list[AnnotationVote]:
        """Get all votes for an annotation, ordered by ``created_at``.

        Phase 13 P1.5: relationships ``user`` / ``suggested_tag`` were
        previously eager-loaded; the recording-level ``suggested_tag``
        relationship has been removed (Phase 14+ deferred). The remaining
        ``user`` relationship is left as ``lazy="raise"`` and is loaded
        explicitly by callers when needed (FR-039 masking).

        Args:
            annotation_id: Annotation's UUID

        Returns:
            List of AnnotationVote instances
        """
        result = await self.db.execute(
            select(AnnotationVote)
            .where(AnnotationVote.annotation_id == annotation_id)
            .order_by(AnnotationVote.created_at.asc())
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        annotation_id: UUID,
        user_id: UUID,
        vote: VoteType,
        source: AnnotationVoteSource,
        project_role_at_vote: ProjectMemberRole | None,
        project_id: UUID,
        signal_quality: SignalQuality | None = None,  # noqa: ARG002 — Phase 14+ deferred
        suggested_tag_id: UUID | None = None,  # noqa: ARG002 — Phase 14+ deferred
        note: str | None = None,  # noqa: ARG002 — Phase 14+ deferred
    ) -> AnnotationVote:
        """Create or update (upsert) a vote for a user on an annotation.

        If the user has already voted on this annotation, the existing record
        ``vote`` is updated in-place. ``source``, ``project_role_at_vote``,
        and ``project_id`` are immutable per FR-037 — they are populated only
        on first creation and never recomputed on re-vote.

        Phase 13 P1.5: the recording-level fields ``signal_quality`` /
        ``suggested_tag_id`` / ``note`` are accepted as keyword arguments
        for caller compatibility but are NOT persisted. The DB-truth schema
        does not carry them; they return in Phase 14+ via
        ``recording_annotations``.

        Args:
            annotation_id: Annotation's UUID
            user_id: Voter's UUID (persisted as ``voter_user_id``)
            vote: Vote value (agree / disagree / unsure) — converted to
                ``smallint`` at the persistence boundary.
            source: Voter relationship classification (FR-037).
                Persisted only on first creation. Ignored on re-vote.
            project_role_at_vote: Member role snapshot when ``source ==
                'member'``. Must be ``None`` for other sources. Persisted only
                on first creation. Ignored on re-vote.
            project_id: Project that owns the annotation (FR-061a integrity
                gate). Persisted only on first creation.
            signal_quality: TODO(Phase 14+ recording_annotations) — currently
                ignored.
            suggested_tag_id: TODO(Phase 14+ recording_annotations) —
                currently ignored.
            note: TODO(Phase 14+ recording_annotations) — currently ignored.

        Returns:
            Created or updated AnnotationVote instance
        """
        existing = await self.get_by_annotation_and_user(annotation_id, user_id)

        if existing is not None:
            existing.vote = vote_to_int(vote)
            # FR-037 immutability: do NOT touch existing.source /
            # existing.project_role_at_vote / existing.project_id on re-vote.
            await self.db.flush()
            return existing

        new_vote = AnnotationVote(
            annotation_id=annotation_id,
            voter_user_id=user_id,
            project_id=project_id,
            vote=vote_to_int(vote),
            source=source,
            project_role_at_vote=project_role_at_vote,
        )
        self.db.add(new_vote)
        await self.db.flush()
        return new_vote

    async def delete_by_annotation_and_user(
        self,
        annotation_id: UUID,
        user_id: UUID,
    ) -> bool:
        """Delete a user's vote on an annotation.

        Args:
            annotation_id: Annotation's UUID
            user_id: Voter's UUID

        Returns:
            True if a vote was deleted, False if no vote existed
        """
        from sqlalchemy.engine import CursorResult

        cursor: CursorResult[tuple[()]] = await self.db.execute(  # type: ignore[assignment]
            delete(AnnotationVote).where(
                AnnotationVote.annotation_id == annotation_id,
                AnnotationVote.voter_user_id == user_id,
            )
        )
        await self.db.flush()
        return cursor.rowcount > 0

    async def count_by_annotation(self, annotation_id: UUID) -> dict[VoteType, int]:
        """Count votes by type for an annotation.

        Uses a GROUP BY query instead of loading full vote objects.

        Args:
            annotation_id: Annotation's UUID

        Returns:
            Dict keyed by :class:`VoteType` with the per-type counts.
        """
        result = await self.db.execute(
            select(AnnotationVote.vote, func.count())
            .where(AnnotationVote.annotation_id == annotation_id)
            .group_by(AnnotationVote.vote)
        )
        counts: dict[VoteType, int] = {
            VoteType.AGREE: 0,
            VoteType.DISAGREE: 0,
            VoteType.UNSURE: 0,
        }
        for vote_int, count in result.all():
            counts[vote_from_int(vote_int)] = count
        return counts
