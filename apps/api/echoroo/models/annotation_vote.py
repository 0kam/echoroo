"""AnnotationVote model for team-based detection review voting.

Implements an iNaturalist-inspired voting system where multiple team members
can vote agree/disagree/unsure on each detection annotation. Consensus is
computed from vote counts using a configurable threshold.

Phase 13 P1.5 (T804) — Same-name drift reconcile (DB is truth):
The DB schema is the source of truth for ``annotation_votes``. This module
mirrors the DB column shape exactly:

* ``voter_user_id`` (was ``user_id`` before P1.5) — the voter UUID. Renamed
  to align with the spec / DB column name.
* ``project_id`` — required FK to ``projects`` (FR-061a integrity gate). The
  DB-level CASCADE ensures vote rows die with the project.
* ``vote`` — ``smallint`` (was a Python ``Enum`` mapped to ``votetype``
  before P1.5). The Python boundary maps :class:`VoteType` to / from this
  integer with the canonical mapping ``AGREE=1``, ``DISAGREE=-1``,
  ``UNSURE=0``. See :data:`VOTE_TYPE_TO_INT` / :data:`VOTE_INT_TO_TYPE`.

Columns dropped from the ORM in P1.5 (DB never had them; they belonged to
the recording-level annotation feature deferred to Phase 14+ via the
``recording_annotations`` table): ``signal_quality``, ``suggested_tag_id``,
``note``. The vote endpoints / schemas keep their request shapes for now
but the dropped fields are not persisted (logged as TODO in the service
layer). Full reinstatement lands with Phase 14+.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, UUIDMixin
from echoroo.models.enums import (
    AnnotationVoteSource,
    ProjectMemberRole,
    VoteType,
)

if TYPE_CHECKING:
    from echoroo.models.annotation import Annotation
    from echoroo.models.project import Project
    from echoroo.models.user import User


# ----------------------------------------------------------------------- #
# Phase 13 P1.5: VoteType <-> smallint canonical mapping.
# The DB column is ``smallint`` (per the baseline 0001 schema) so callers
# must convert the Python :class:`VoteType` enum at the persistence boundary.
# ----------------------------------------------------------------------- #
VOTE_TYPE_TO_INT: Final[dict[VoteType, int]] = {
    VoteType.AGREE: 1,
    VoteType.DISAGREE: -1,
    VoteType.UNSURE: 0,
}

VOTE_INT_TO_TYPE: Final[dict[int, VoteType]] = {
    v: k for k, v in VOTE_TYPE_TO_INT.items()
}


def vote_to_int(vote: VoteType) -> int:
    """Convert a :class:`VoteType` enum value to its DB ``smallint`` form."""
    return VOTE_TYPE_TO_INT[vote]


def vote_from_int(value: int) -> VoteType:
    """Convert a DB ``smallint`` vote value back to :class:`VoteType`."""
    return VOTE_INT_TO_TYPE[value]


class AnnotationVote(UUIDMixin, Base):
    """Voting record for a single user's opinion on a detection annotation.

    Each user can cast at most one vote per annotation (enforced by unique
    constraint). When a user re-votes, the existing record is updated
    (upsert pattern) rather than creating a duplicate.

    Phase 13 P1.5 (T804): column shape now matches the DB exactly —
    ``voter_user_id`` (renamed from ``user_id``), ``project_id`` added,
    ``vote`` is a smallint integer, and the recording-level fields
    (``signal_quality`` / ``suggested_tag_id`` / ``note``) are dropped.
    """

    __tablename__ = "annotation_votes"

    annotation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Annotation being voted on",
    )
    voter_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc=(
            "User who cast this vote (Phase 13 P1.5: renamed from"
            " ``user_id`` to align with DB column name)."
        ),
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc=(
            "Project the vote belongs to. Phase 13 P1.5: required FK"
            " (FR-061a integrity gate). DB CASCADE drops votes with the project."
        ),
    )
    vote: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        doc=(
            "Vote value as ``smallint``: 1=agree, -1=disagree, 0=unsure"
            " (Phase 13 P1.5; see VOTE_TYPE_TO_INT / VOTE_INT_TO_TYPE)."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        doc="Timestamp when this vote was cast",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
        doc="Timestamp of the most recent vote update (upsert).",
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

    # Relationships ------------------------------------------------------ #
    annotation: Mapped[Annotation] = relationship(
        "Annotation",
        lazy="raise",
    )
    user: Mapped[User] = relationship(
        "User",
        foreign_keys=[voter_user_id],
        lazy="raise",
        doc="Voter user — relationship name retained for FR-039 masking helpers.",
    )
    project: Mapped[Project] = relationship(
        "Project",
        foreign_keys=[project_id],
        lazy="raise",
    )

    __table_args__ = (
        # One vote per user per annotation — Phase 13 P1.5 keeps the unique
        # constraint on the renamed ``voter_user_id`` column.
        UniqueConstraint(
            "annotation_id",
            "voter_user_id",
            name="uq_annotation_vote_user",
        ),
        Index("ix_annotation_votes_annotation", "annotation_id"),
        Index(
            "ix_annotation_votes_project_source",
            "project_id",
            "source",
        ),
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
        return (
            f"<AnnotationVote(annotation_id={self.annotation_id},"
            f" voter_user_id={self.voter_user_id}, vote={self.vote})>"
        )

    @property
    def vote_enum(self) -> VoteType:
        """Return :attr:`vote` as a :class:`VoteType` enum value.

        Phase 13 P1.5 ergonomic helper — service code reads this to compare
        against ``VoteType.AGREE`` etc. without manually invoking
        :func:`vote_from_int`.
        """
        return VOTE_INT_TO_TYPE[self.vote]
