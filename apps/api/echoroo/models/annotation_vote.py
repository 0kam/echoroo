"""AnnotationVote model for team-based detection review voting.

Implements an iNaturalist-inspired voting system where multiple team members
can vote agree/disagree/unsure on each detection annotation. Consensus is
computed from vote counts using a configurable threshold.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, UUIDMixin
from echoroo.models.enums import (
    AnnotationVoteSource,
    ProjectMemberRole,
    SignalQuality,
    VoteType,
)

if TYPE_CHECKING:
    from echoroo.models.annotation import Annotation
    from echoroo.models.tag import Tag
    from echoroo.models.user import User


class AnnotationVote(UUIDMixin, Base):
    """Voting record for a single user's opinion on a detection annotation.

    Each user can cast at most one vote per annotation (enforced by unique
    constraint). When a user re-votes, the existing record is updated
    (upsert pattern) rather than creating a duplicate.

    Attributes:
        id: Unique identifier (UUID)
        annotation_id: FK to the annotation being voted on
        user_id: FK to the user who cast this vote
        vote: The vote value (agree / disagree / unsure)
        suggested_tag_id: Optional FK to a tag suggested when disagreeing with wrong species
        note: Optional free-text reason for the vote (especially useful for disagreements)
        created_at: Timestamp when this vote was first cast
        source: Voter's relationship to the project at vote-creation time
            (FR-037, immutable). One of ``member`` / ``guest_authenticated`` /
            ``trusted_user``. Set on first cast and **never recomputed** on
            re-vote (FR-037 immutability).
        project_role_at_vote: Snapshot of the voter's role within the project
            at vote-creation time when ``source == 'member'``. ``None`` for
            non-member sources. Enforced via CHECK constraint.
    """

    __tablename__ = "annotation_votes"

    annotation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Annotation being voted on",
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="User who cast this vote",
    )
    vote: Mapped[VoteType] = mapped_column(
        Enum(
            VoteType,
            name="votetype",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc="Vote value: agree, disagree, or unsure",
    )
    suggested_tag_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="SET NULL"),
        nullable=True,
        doc="Suggested correct species tag when disagreeing",
    )
    signal_quality: Mapped[SignalQuality | None] = mapped_column(
        Enum(
            SignalQuality,
            name="signalquality",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
        doc="Signal quality assessment (only applicable when vote is 'agree')",
    )
    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Optional reason or comment for this vote",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Timestamp when this vote was cast",
    )
    # FR-037: voter source classification — set on first cast, immutable
    # afterwards (re-votes preserve the original ``source`` and
    # ``project_role_at_vote`` snapshot).
    source: Mapped[AnnotationVoteSource] = mapped_column(
        Enum(
            AnnotationVoteSource,
            name="annotationvotesource",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc=(
            "Voter source at vote-creation time (member / guest_authenticated /"
            " trusted_user). FR-037: immutable after first cast."
        ),
    )
    project_role_at_vote: Mapped[ProjectMemberRole | None] = mapped_column(
        Enum(
            ProjectMemberRole,
            name="projectmemberrole",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
        doc=(
            "Snapshot of the voter's project role when source='member'."
            " NULL for guest_authenticated / trusted_user sources."
        ),
    )

    # Relationships
    annotation: Mapped[Annotation] = relationship(
        "Annotation",
        lazy="raise",
    )
    user: Mapped[User] = relationship(
        "User",
        lazy="raise",
    )
    suggested_tag: Mapped[Tag | None] = relationship(
        "Tag",
        lazy="raise",
    )

    __table_args__ = (
        # One vote per user per annotation
        UniqueConstraint("annotation_id", "user_id", name="uq_annotation_vote_user"),
        Index("ix_annotation_votes_annotation_id", "annotation_id"),
        Index("ix_annotation_votes_user_id", "user_id"),
        # FR-037: ``source`` and ``project_role_at_vote`` must be consistent —
        # ``member`` votes capture the role, non-member sources never do.
        CheckConstraint(
            "(source = 'member' AND project_role_at_vote IS NOT NULL) "
            "OR (source IN ('guest_authenticated', 'trusted_user') "
            "AND project_role_at_vote IS NULL)",
            name="ck_annotation_votes_source_role_consistency",
        ),
    )

    def __repr__(self) -> str:
        return f"<AnnotationVote(annotation_id={self.annotation_id}, user_id={self.user_id}, vote={self.vote})>"
