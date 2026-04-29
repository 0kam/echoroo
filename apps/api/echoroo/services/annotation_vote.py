"""AnnotationVote service for team-based detection review voting business logic.

Implements an iNaturalist-inspired consensus algorithm:
  consensus_score = agree_count / (agree_count + disagree_count)
  - unsure votes are recorded but NOT counted in the score calculation
  - needs_votes: agree + disagree < min_votes
  - agreed:      score > threshold AND agree >= min_votes
  - rejected:    score <= (1 - threshold) AND disagree >= min_votes
  - disputed:    has enough votes but no clear consensus

Phase 6 (US2 / FR-037 / FR-038 / FR-039) additions:
  - ``cast_vote`` now requires ``source`` (AnnotationVoteSource) and
    ``project_role_at_vote`` (ProjectMemberRole | None) — these are
    persisted on first creation and **immutable** on re-vote.
  - ``get_vote_summary`` now accepts ``viewer_role`` and applies FR-039
    voter-id masking: non-Owner / non-Admin viewers see ``user_id=None``
    (and ``user=None``) for guest_authenticated / trusted_user votes.
    Member votes are visible to all viewer roles.
  - VoteSummaryResponse exposes per-source aggregate counts
    (``member_agree`` / ``member_disagree`` / ``guest_authenticated_*`` /
    ``trusted_user_*``) per FR-038.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from echoroo.models.annotation import Annotation
from echoroo.models.annotation_vote import AnnotationVote
from echoroo.models.enums import (
    AnnotationVoteSource,
    ConsensusStatus,
    DetectionSource,
    DetectionStatus,
    ProjectMemberRole,
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

# FR-039: roles allowed to see the raw ``user_id`` of non-member / Trusted
# votes. Owner / Admin only — Member, Viewer, and guest_authenticated viewers
# all see the masked (``null``) form. The vote itself, ``source``, and
# ``project_role_at_vote`` remain visible regardless.
_VOTER_ID_VISIBLE_VIEWER_ROLES: frozenset[str] = frozenset({"Owner", "Admin"})

# FR-039: vote sources whose ``user_id`` is masked from non-Owner / non-Admin
# viewers. Member votes are always visible.
_VOTER_ID_MASKED_SOURCES: frozenset[AnnotationVoteSource] = frozenset(
    {AnnotationVoteSource.GUEST_AUTHENTICATED, AnnotationVoteSource.TRUSTED_USER}
)


async def classify_voter_source(
    *,
    project_id: UUID,
    project: Any,
    user_id: UUID,
    db: Any,
) -> tuple[AnnotationVoteSource, ProjectMemberRole | None]:
    """Compute FR-037 ``(source, project_role_at_vote)`` for a freshly-cast vote.

    Resolution order (per spec.md US2 #2 / US5 #9 / FR-037):

    1. If the user is the project owner → ``(member, OWNER-equivalent)``.
       Owners are not in the ``project_members`` table; the snapshot uses
       :data:`ProjectMemberRole.ADMIN` as the closest persisted enum value
       so the CHECK constraint is satisfied. Tests / response filters can
       still distinguish Owner from Admin via the project's ``owner_id``.
    2. If a row exists in ``project_members`` for ``(project_id, user_id)``
       → ``(member, member.role)``.
    3. Otherwise (Phase 5/6 scope) → ``(guest_authenticated, None)``.

    TODO(T501 / US5 — FR-041〜046): once :class:`ProjectTrustedUser` model +
    repository land, an active overlay row for ``(project_id, user_id, now)``
    must take precedence over guest_authenticated and produce
    ``(trusted_user, None)``. The hook is intentionally a no-op here so
    Phase 6 ships without the Phase 10 dependency.
    """
    # Local import to avoid the heavy permissions import cycle at module load.
    from echoroo.repositories.project import ProjectRepository

    project_repo = ProjectRepository(db)

    owner_id = getattr(project, "owner_id", None)
    if owner_id is not None and owner_id == user_id:
        # Owners aren't in project_members. The CHECK constraint requires
        # a non-NULL role for member votes — capture ADMIN as the closest
        # persisted enum (Owner is derived elsewhere from project.owner_id).
        return AnnotationVoteSource.MEMBER, ProjectMemberRole.ADMIN

    member = await project_repo.get_member(project_id, user_id)
    if member is not None:
        return AnnotationVoteSource.MEMBER, member.role

    # TODO(T501): if a ProjectTrustedUser overlay is active for this user,
    # return (TRUSTED_USER, None). Until Phase 10 ships the model, fall
    # through to guest_authenticated.
    return AnnotationVoteSource.GUEST_AUTHENTICATED, None


async def resolve_viewer_role(
    *,
    project_id: UUID,
    project: Any,
    user_id: UUID | None,
    db: Any,
) -> str:
    """Compute the viewer's normalised role for FR-039 masking decisions.

    Returns one of ``"Guest"`` / ``"Authenticated"`` / ``"Viewer"`` /
    ``"Member"`` / ``"Admin"`` / ``"Owner"``. Owner is derived from
    ``project.owner_id`` — the ``project_members`` table never carries the
    owner row.
    """
    if user_id is None:
        return "Guest"

    owner_id = getattr(project, "owner_id", None)
    if owner_id is not None and owner_id == user_id:
        return "Owner"

    from echoroo.repositories.project import ProjectRepository

    project_repo = ProjectRepository(db)
    member = await project_repo.get_member(project_id, user_id)
    if member is None:
        return "Authenticated"

    role = member.role
    if role == ProjectMemberRole.ADMIN:
        return "Admin"
    if role == ProjectMemberRole.MEMBER:
        return "Member"
    if role == ProjectMemberRole.VIEWER:
        return "Viewer"
    return "Authenticated"


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
        source: AnnotationVoteSource,
        project_role_at_vote: ProjectMemberRole | None,
        project_id: UUID,
        viewer_role: str = "Authenticated",
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
            source: Voter source classification (FR-037). Persisted only on
                first creation; ignored on re-vote.
            project_role_at_vote: Member role snapshot when ``source ==
                'member'``. Must be ``None`` for other sources. Persisted only
                on first creation; ignored on re-vote.
            viewer_role: Normalised role of the viewer reading the response
                (Owner / Admin / Member / Viewer / Authenticated / Guest).
                Used by ``get_vote_summary`` to apply FR-039 masking.
            min_votes: Minimum agree+disagree votes for consensus evaluation
            threshold: Fraction required to reach 'agreed' consensus

        Returns:
            Updated vote summary for the annotation

        Raises:
            HTTPException: If annotation not found
        """
        # Phase 13 P1.5 R2 (Codex follow-up — Fatal): existence-only probe
        # on the DB-truth minimal ``annotations`` table. The legacy
        # ``get_by_id`` rich-shape load is replaced because the rich-shape
        # ORM (``RecordingAnnotation``) lives on a Phase 14+ deferred table
        # that does not exist in the production DB.
        if not await self.annotation_repo.exists(annotation_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        # Phase 13 P1.5 (T804): the recording-level fields
        # (signal_quality / suggested_tag_id / note) are accepted by
        # ``VoteCastRequest`` but no longer persisted. Phase 14+ will
        # reinstate them via the ``recording_annotations`` table.
        await self.vote_repo.upsert(
            annotation_id=annotation_id,
            user_id=user_id,
            vote=request.vote,
            source=source,
            project_role_at_vote=project_role_at_vote,
            project_id=project_id,
            signal_quality=request.signal_quality,
            suggested_tag_id=request.suggested_tag_id,
            note=request.note,
        )

        # Phase 13 P1.5 R2 (Codex follow-up — Fatal):
        # ``Annotation.status`` no longer exists on the DB-truth minimal
        # shape. The consensus status is computed on the fly from votes in
        # :meth:`get_vote_summary` and ``Detection`` carries the persisted
        # status — re-using it for the persistent recompute is Phase 14+.
        # See ``apps/api/echoroo/models/annotation.py`` module docstring.
        return await self.get_vote_summary(
            annotation_id,
            user_id,
            viewer_role=viewer_role,
            min_votes=min_votes,
            threshold=threshold,
        )

    async def delete_vote(
        self,
        annotation_id: UUID,
        user_id: UUID,
        viewer_role: str = "Authenticated",
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
        # Phase 13 P1.5 R2: existence-only probe on the DB-truth minimal
        # shape (see ``cast_vote`` for the rationale).
        if not await self.annotation_repo.exists(annotation_id):
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

        # Phase 13 P1.5 R2: see ``cast_vote`` — consensus is computed on the
        # fly in ``get_vote_summary`` from votes alone now that
        # ``Annotation.status`` is Phase 14+ deferred.
        return await self.get_vote_summary(
            annotation_id,
            user_id,
            viewer_role=viewer_role,
            min_votes=min_votes,
            threshold=threshold,
        )

    async def get_vote_summary(
        self,
        annotation_id: UUID,
        current_user_id: UUID | None = None,
        viewer_role: str = "Authenticated",
        min_votes: int = 2,
        threshold: float = 0.667,
    ) -> VoteSummaryResponse:
        """Get the vote summary for an annotation.

        Args:
            annotation_id: Annotation's UUID
            current_user_id: Optional current user ID to include their vote
            viewer_role: Normalised role of the viewer ("Owner" / "Admin" /
                "Member" / "Viewer" / "Authenticated" / "Guest"). Used to
                apply FR-039 voter-id masking — Owner / Admin see raw UUIDs,
                everyone else sees ``user_id=null`` for non-member / Trusted
                votes.

        Returns:
            VoteSummaryResponse with counts, consensus status, and individual
            votes (with FR-039 masking applied per viewer role).

        Raises:
            HTTPException: If annotation not found
        """
        # Phase 13 P1.5 R2: existence-only probe on the DB-truth minimal
        # ``annotations`` shape (see ``cast_vote`` for rationale).
        if not await self.annotation_repo.exists(annotation_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Detection not found",
            )

        votes = await self.vote_repo.list_by_annotation(annotation_id)

        # Phase 13 P1.5: ``vote`` is now a smallint at the DB layer; use the
        # ``vote_enum`` ergonomic property for VoteType comparisons.
        agree_count = sum(1 for v in votes if v.vote_enum == VoteType.AGREE)
        disagree_count = sum(1 for v in votes if v.vote_enum == VoteType.DISAGREE)
        unsure_count = sum(1 for v in votes if v.vote_enum == VoteType.UNSURE)

        # Per-source counts computed in Python because we already load all
        # votes for the voters[] response (FR-038/039 require both). Switching
        # to SQL GROUP BY would not avoid the load and would require a second
        # round-trip — the linear pass below is cheaper end-to-end.
        # FR-038: per-source aggregate counts
        member_agree = sum(
            1 for v in votes
            if v.vote_enum == VoteType.AGREE
            and v.source == AnnotationVoteSource.MEMBER
        )
        member_disagree = sum(
            1 for v in votes
            if v.vote_enum == VoteType.DISAGREE
            and v.source == AnnotationVoteSource.MEMBER
        )
        guest_authenticated_agree = sum(
            1 for v in votes
            if v.vote_enum == VoteType.AGREE
            and v.source == AnnotationVoteSource.GUEST_AUTHENTICATED
        )
        guest_authenticated_disagree = sum(
            1 for v in votes
            if v.vote_enum == VoteType.DISAGREE
            and v.source == AnnotationVoteSource.GUEST_AUTHENTICATED
        )
        trusted_user_agree = sum(
            1 for v in votes
            if v.vote_enum == VoteType.AGREE
            and v.source == AnnotationVoteSource.TRUSTED_USER
        )
        trusted_user_disagree = sum(
            1 for v in votes
            if v.vote_enum == VoteType.DISAGREE
            and v.source == AnnotationVoteSource.TRUSTED_USER
        )

        # Phase 13 P1.5: ``signal_quality`` was dropped from the AnnotationVote
        # row (Phase 14+ recording_annotations defer). The aggregate dict is
        # emitted with zero counts so the API contract is unchanged.
        signal_quality_counts: dict[str, int] = {q.value: 0 for q in SignalQuality}

        user_vote: VoteType | None = None
        user_signal_quality: SignalQuality | None = None
        if current_user_id is not None:
            for v in votes:
                if v.voter_user_id == current_user_id:
                    user_vote = v.vote_enum
                    # Phase 13 P1.5: signal_quality column dropped from
                    # AnnotationVote — always emit None until Phase 14+.
                    user_signal_quality = None
                    break

        vote_items = [self._serialize_vote(v, viewer_role=viewer_role) for v in votes]

        # Phase 13 P1.5 R2 (Codex follow-up — Fatal): compute consensus on
        # the fly. The legacy persisted ``annotation.status`` column lives
        # on the Phase 14+ ``recording_annotations`` table now and is not
        # available on the DB-truth minimal ``Annotation`` shape.
        consensus_status = self.compute_consensus(
            agree_count=agree_count,
            disagree_count=disagree_count,
            min_votes=min_votes,
            threshold=threshold,
        )

        return VoteSummaryResponse(
            annotation_id=annotation_id,
            agree_count=agree_count,
            disagree_count=disagree_count,
            unsure_count=unsure_count,
            user_vote=user_vote,
            user_signal_quality=user_signal_quality,
            signal_quality_counts=signal_quality_counts,
            consensus_status=consensus_status,
            voters=vote_items,
            member_agree=member_agree,
            member_disagree=member_disagree,
            guest_authenticated_agree=guest_authenticated_agree,
            guest_authenticated_disagree=guest_authenticated_disagree,
            trusted_user_agree=trusted_user_agree,
            trusted_user_disagree=trusted_user_disagree,
        )

    @staticmethod
    def _serialize_vote(vote: AnnotationVote, *, viewer_role: str) -> VoteResponse:
        """Serialise a single AnnotationVote row applying FR-039 masking.

        FR-039: when the viewer is not Owner / Admin and the vote was cast by
        a non-member or Trusted user, the ``user_id`` (and embedded ``user``
        info) are masked to ``None``. The vote itself, ``vote`` value,
        ``source``, and ``project_role_at_vote`` remain visible — vote
        visibility is preserved by design.

        Member votes are visible to all viewer roles regardless.
        """
        v_user_id: UUID = vote.voter_user_id
        v_source: AnnotationVoteSource = vote.source

        # Phase 13 P1.5 (T804): the ``user`` relationship is now
        # ``lazy="raise"`` and not eager-loaded by the repository. Use
        # SQLAlchemy attribute inspection so that touching the attribute on
        # an unloaded instance does not trigger an implicit load (FR-039
        # masking has to run on every list response — masked votes must
        # never trigger a DB round-trip).
        try:
            from sqlalchemy import inspect as sa_inspect

            state = sa_inspect(vote)
            v_user = vote.user if "user" not in state.unloaded else None
        except Exception:  # pragma: no cover — defensive fallback
            v_user = None

        should_mask = (
            v_source in _VOTER_ID_MASKED_SOURCES
            and viewer_role not in _VOTER_ID_VISIBLE_VIEWER_ROLES
        )

        if should_mask:
            visible_user_id: UUID | None = None
            visible_user: VoteUserInfo | None = None
        else:
            visible_user_id = v_user_id
            if v_user is not None:
                visible_user = VoteUserInfo(
                    id=v_user.id,
                    email=v_user.email,
                    display_name=v_user.display_name,
                )
            else:
                visible_user = None

        return VoteResponse(
            id=vote.id,
            annotation_id=vote.annotation_id,
            user_id=visible_user_id,
            vote=vote.vote_enum,
            # Phase 13 P1.5: dropped columns echoed as None until Phase 14+
            # reinstates them via ``recording_annotations``.
            signal_quality=None,
            suggested_tag_id=None,
            note=None,
            created_at=vote.created_at,
            user=visible_user,
            source=v_source,
            project_role_at_vote=vote.project_role_at_vote,
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
        """Phase 14+ deferred — was: persist annotation.status from votes.

        Phase 13 P1.5 R2 (Codex follow-up — Fatal): the DB-truth minimal
        ``Annotation`` shape no longer carries a ``status`` column. The
        consensus state is now computed on the fly in
        :meth:`get_vote_summary` from the vote tally, and persistence will
        return when Phase 14+ introduces the ``recording_annotations`` table
        with its own review-state lifecycle.

        SAMPLING_ROUND single-vote bypass behaviour is also deferred —
        :class:`echoroo.workers.classifier_tasks` lives on the Phase 14+
        ``RecordingAnnotation`` shape and will reinstate it.

        Args:
            annotation: Annotation model (kept for signature compatibility).
            min_votes: Unused, kept for signature compatibility.
            threshold: Unused, kept for signature compatibility.
        """
        # No-op — Phase 14+ recording_annotations will reinstate persistence.
        # Kept as a thin shim so any legacy in-tree caller (e.g. background
        # tasks not exercised by Phase 13) stays compilable; the live API
        # path no longer calls this method.
        del annotation, min_votes, threshold
        return None
