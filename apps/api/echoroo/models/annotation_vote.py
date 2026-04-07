"""AnnotationVote model for team-based detection review voting.

Implements an iNaturalist-inspired voting system where multiple team members
can vote agree/disagree/unsure on each detection annotation. Consensus is
computed from vote counts using a configurable threshold.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, UUIDMixin
from echoroo.models.enums import SignalQuality, VoteType

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
    )

    def __repr__(self) -> str:
        return f"<AnnotationVote(annotation_id={self.annotation_id}, user_id={self.user_id}, vote={self.vote})>"
