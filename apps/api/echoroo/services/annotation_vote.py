"""AnnotationVote service for team-based detection review voting business logic.

Implements an iNaturalist-inspired consensus algorithm:
  consensus_score = agree_count / (agree_count + disagree_count)
  - unsure votes are recorded but NOT counted in the score calculation
  - needs_votes: agree + disagree < min_votes
  - agreed:      score > threshold AND agree >= min_votes
  - rejected:    score <= (1 - threshold) AND disagree >= min_votes
  - disputed:    has enough votes but no clear consensus
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.annotation import Annotation
from echoroo.models.enums import (
    ConsensusStatus,
    DetectionSource,
    DetectionStatus,
    SignalQuality,
    VoteType,
)
from echoroo.repositories.annotation import AnnotationRepository
from echoroo.repositories.annotation_vote import AnnotationVoteRepository
from echoroo.schemas.annotation_vote import (
    VoteCastRequest,
    VoteResponse,
    VoteSummaryResponse,
    VoteUserInfo,
)


class AnnotationVoteService:
    """Service for annotation vote management and consensus computation."""

    def __init__(
        self,
        vote_repo: AnnotationVoteRepository,
        annotation_repo: AnnotationRepository,
    ) -> None:
        """Initialize service with repositories.

        Args:
            vote_repo: AnnotationVote repository instance
            annotation_repo: Annotation repository instance
        """
        self.vote_repo = vote_repo
        self.annotation_repo = annotation_repo

    async def cast_vote(
        self,
        annotation_id: UUID,
        user_id: UUID,
        request: VoteCastRequest,
        min_votes: int = 2,
        threshold: float = 0.667,
    ) -> VoteSummaryResponse:
        """Cast or update a vote on a detection annotation.

        After recording the vote, recomputes annotation.status from the
        consensus algorithm and persists the updated status.

        Args:
            annotation_id: Annotation's UUID
            user_id: ID of the voting user
            request: Vote cast request data
            min_votes: Minimum agree+disagree votes for consensus evaluation
            threshold: Fraction required to reach 'agreed' consensus

        Returns:
            Updated vote summary for the annotation

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(annotation_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        await self.vote_repo.upsert(
            annotation_id=annotation_id,
            user_id=user_id,
            vote=request.vote,
            signal_quality=request.signal_quality,
            suggested_tag_id=request.suggested_tag_id,
            note=request.note,
        )

        await self._update_annotation_status(annotation, min_votes, threshold)
        return await self.get_vote_summary(annotation_id, user_id)

    async def delete_vote(
        self,
        annotation_id: UUID,
        user_id: UUID,
        min_votes: int = 2,
        threshold: float = 0.667,
    ) -> VoteSummaryResponse:
        """Remove the current user's vote from an annotation.

        After removing the vote, recomputes annotation.status from the
        updated vote counts.

        Args:
            annotation_id: Annotation's UUID
            user_id: ID of the voting user
            min_votes: Minimum agree+disagree votes for consensus evaluation
            threshold: Fraction required to reach 'agreed' consensus

        Returns:
            Updated vote summary for the annotation

        Raises:
            HTTPException: If annotation not found or no vote to delete
        """
        annotation = await self.annotation_repo.get_by_id(annotation_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        deleted = await self.vote_repo.delete_by_annotation_and_user(
            annotation_id=annotation_id,
            user_id=user_id,
        )
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No vote found to delete",
            )

        await self._update_annotation_status(annotation, min_votes, threshold)
        return await self.get_vote_summary(annotation_id, user_id)

    async def get_vote_summary(
        self,
        annotation_id: UUID,
        current_user_id: UUID | None = None,
    ) -> VoteSummaryResponse:
        """Get the vote summary for an annotation.

        Args:
            annotation_id: Annotation's UUID
            current_user_id: Optional current user ID to include their vote

        Returns:
            VoteSummaryResponse with counts, consensus status, and individual votes

        Raises:
            HTTPException: If annotation not found
        """
        annotation = await self.annotation_repo.get_by_id(annotation_id)
        if not annotation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        votes = await self.vote_repo.list_by_annotation(annotation_id)

        agree_count = sum(1 for v in votes if v.vote == VoteType.AGREE)
        disagree_count = sum(1 for v in votes if v.vote == VoteType.DISAGREE)
        unsure_count = sum(1 for v in votes if v.vote == VoteType.UNSURE)

        # Count signal quality values among agree votes
        signal_quality_counts: dict[str, int] = {q.value: 0 for q in SignalQuality}
        for v in votes:
            if v.vote == VoteType.AGREE and v.signal_quality is not None:
                signal_quality_counts[v.signal_quality] += 1

        user_vote: VoteType | None = None
        user_signal_quality: SignalQuality | None = None
        if current_user_id is not None:
            for v in votes:
                if v.user_id == current_user_id:
                    user_vote = v.vote
                    user_signal_quality = v.signal_quality if v.vote == VoteType.AGREE else None
                    break

        vote_items = [
            VoteResponse(
                id=v.id,
                annotation_id=v.annotation_id,
                user_id=v.user_id,
                vote=v.vote,
                signal_quality=v.signal_quality,
                suggested_tag_id=v.suggested_tag_id,
                note=v.note,
                created_at=v.created_at,
                user=VoteUserInfo(
                    id=v.user.id,
                    email=v.user.email,
                    display_name=v.user.display_name,
                ),
            )
            for v in votes
        ]

        return VoteSummaryResponse(
            annotation_id=annotation_id,
            agree_count=agree_count,
            disagree_count=disagree_count,
            unsure_count=unsure_count,
            user_vote=user_vote,
            user_signal_quality=user_signal_quality,
            signal_quality_counts=signal_quality_counts,
            consensus_status=annotation.status,
            votes=vote_items,
        )

    @staticmethod
    def compute_consensus(
        agree_count: int,
        disagree_count: int,
        min_votes: int,
        threshold: float,
    ) -> DetectionStatus:
        """Compute annotation consensus status from vote counts.

        Algorithm:
          - needs_votes: agree + disagree < min_votes
          - agreed:      score > threshold AND agree >= min_votes
          - rejected:    score <= (1 - threshold) AND disagree >= min_votes
          - disputed:    none of the above

        Note: unsure votes are not passed here — they do not affect the score.

        Args:
            agree_count: Number of agree votes
            disagree_count: Number of disagree votes
            min_votes: Minimum decisive votes needed for consensus evaluation
            threshold: Score threshold to reach 'agreed' (e.g. 0.667)

        Returns:
            DetectionStatus computed from votes
        """
        total = agree_count + disagree_count

        if total < min_votes:
            return DetectionStatus.UNREVIEWED

        score = agree_count / total

        if score > threshold and agree_count >= min_votes:
            return DetectionStatus.CONFIRMED
        if score <= (1.0 - threshold) and disagree_count >= min_votes:
            return DetectionStatus.REJECTED

        # Has enough votes but no clear consensus — stay unreviewed
        return DetectionStatus.UNREVIEWED

    @staticmethod
    def compute_consensus_status(
        agree_count: int,
        disagree_count: int,
        min_votes: int,
        threshold: float,
    ) -> ConsensusStatus:
        """Compute human-readable consensus status string.

        Returns a richer status enum (needs_votes/agreed/rejected/disputed)
        that is separate from DetectionStatus and intended for API responses.

        Args:
            agree_count: Number of agree votes
            disagree_count: Number of disagree votes
            min_votes: Minimum decisive votes needed for consensus evaluation
            threshold: Score threshold to reach 'agreed'

        Returns:
            ConsensusStatus enum value
        """
        total = agree_count + disagree_count

        if total < min_votes:
            return ConsensusStatus.NEEDS_VOTES

        score = agree_count / total

        if score > threshold and agree_count >= min_votes:
            return ConsensusStatus.AGREED
        if score <= (1.0 - threshold) and disagree_count >= min_votes:
            return ConsensusStatus.REJECTED

        return ConsensusStatus.DISPUTED

    # Sources that bypass consensus requirements — a single decisive vote is sufficient.
    _SINGLE_VOTE_SOURCES = frozenset({DetectionSource.SAMPLING_ROUND})

    async def _update_annotation_status(
        self,
        annotation: Annotation,
        min_votes: int,
        threshold: float,
    ) -> None:
        """Recompute and persist annotation.status from current vote counts.

        For annotations sourced from the sampling pipeline (sampling_round),
        a single agree/disagree vote is enough to confirm or reject
        — the normal consensus thresholds are bypassed entirely.

        For all other sources the standard iNaturalist-inspired consensus
        algorithm applies (min_votes + threshold).

        Args:
            annotation: Annotation model instance to update
            min_votes: Minimum decisive votes needed for consensus evaluation
            threshold: Score threshold to reach 'agreed'
        """
        counts = await self.vote_repo.count_by_annotation(annotation.id)
        agree_count = counts.get(VoteType.AGREE, 0)
        disagree_count = counts.get(VoteType.DISAGREE, 0)

        if annotation.source in self._SINGLE_VOTE_SOURCES:
            # Bypass consensus: first decisive vote wins immediately.
            if agree_count >= 1:
                new_status = DetectionStatus.CONFIRMED
            elif disagree_count >= 1:
                new_status = DetectionStatus.REJECTED
            else:
                new_status = DetectionStatus.UNREVIEWED
        else:
            new_status = self.compute_consensus(
                agree_count=agree_count,
                disagree_count=disagree_count,
                min_votes=min_votes,
                threshold=threshold,
            )

        annotation.status = new_status
        await self.annotation_repo.db.flush()
