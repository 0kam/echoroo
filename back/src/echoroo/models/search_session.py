"""Search Session and Search Result models.

A Search Session represents a single similarity search operation within
an ML Project. Each session targets a specific species/sound tag and
uses a set of reference sounds to find similar clips in the dataset.

The search process involves:
1. Selecting active reference sounds for the target species
2. Computing similarity between reference embeddings and dataset clip embeddings
3. Ranking results by similarity score
4. Allowing users to label results as positive/negative training examples

Search Results are individual matches found during a search session.
Each result links a dataset clip to the search session with its
similarity score and user-assigned label.
"""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from echoroo.models.base import Base
from echoroo.models.tag import Tag

if TYPE_CHECKING:
    from echoroo.models.clip import Clip
    from echoroo.models.ml_project import MLProject
    from echoroo.models.reference_sound import ReferenceSound
    from echoroo.models.user import User

__all__ = [
    "SearchSession",
    "SearchSessionReferenceSound",
    "SearchResult",
    "SearchResultLabel",
]


class SearchResultLabel(str, enum.Enum):
    """Label for search result classification."""

    UNLABELED = "unlabeled"
    """Result has not been reviewed yet."""

    POSITIVE = "positive"
    """Result confirmed as positive example of target sound."""

    NEGATIVE = "negative"
    """Result confirmed as negative (not the target sound)."""

    UNCERTAIN = "uncertain"
    """Result is ambiguous or difficult to classify."""

    SKIPPED = "skipped"
    """Result was skipped during labeling."""


class SearchSession(Base):
    """Search Session model.

    Represents a similarity search operation targeting a specific
    species/sound within an ML project.
    """

    __tablename__ = "search_session"

    # Fields without defaults (required fields) - must come first
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the search session."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the search session."""

    name: orm.Mapped[str] = orm.mapped_column(nullable=False)
    """A descriptive name for this search session."""

    ml_project_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("ml_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The ML project this search session belongs to."""

    target_tag_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The species/sound tag being searched for."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        ForeignKey("user.id"),
        nullable=False,
    )
    """The user who created this search session."""

    # Fields with defaults (optional fields) - must come after required fields
    description: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional description of the search session goals."""

    similarity_threshold: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
        default=0.7,
    )
    """Minimum similarity score for results (0.0 to 1.0)."""

    max_results: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=1000,
    )
    """Maximum number of results to return."""

    filter_config: orm.Mapped[dict | None] = orm.mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    """Optional JSON filter configuration for narrowing search scope."""

    is_search_complete: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=False,
    )
    """Whether the similarity search has completed."""

    is_labeling_complete: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=False,
    )
    """Whether labeling of results has been completed."""

    # Relationships
    ml_project: orm.Mapped["MLProject"] = orm.relationship(
        "MLProject",
        back_populates="search_sessions",
        init=False,
        repr=False,
    )
    """The ML project this search session belongs to."""

    target_tag: orm.Mapped[Tag] = orm.relationship(
        "Tag",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The target species/sound tag."""

    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The user who created this search session."""

    # Reference sounds used in this search (via junction table)
    reference_sounds: orm.Mapped[list["ReferenceSound"]] = orm.relationship(
        "ReferenceSound",
        secondary="search_session_reference_sound",
        viewonly=True,
        default_factory=list,
        repr=False,
    )
    """Reference sounds used for this search."""

    search_session_reference_sounds: orm.Mapped[
        list["SearchSessionReferenceSound"]
    ] = orm.relationship(
        "SearchSessionReferenceSound",
        back_populates="search_session",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Junction table entries for reference sounds."""

    # Search results
    search_results: orm.Mapped[list["SearchResult"]] = orm.relationship(
        "SearchResult",
        back_populates="search_session",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Results from this search session."""


class SearchSessionReferenceSound(Base):
    """Search Session Reference Sound junction model.

    Links reference sounds to the search sessions that use them.
    """

    __tablename__ = "search_session_reference_sound"
    __table_args__ = (
        UniqueConstraint(
            "search_session_id",
            "reference_sound_id",
        ),
    )

    search_session_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("search_session.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    """The search session ID."""

    reference_sound_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("reference_sound.id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )
    """The reference sound ID."""

    # Relationships
    search_session: orm.Mapped[SearchSession] = orm.relationship(
        "SearchSession",
        back_populates="search_session_reference_sounds",
        init=False,
        repr=False,
    )
    """The search session."""

    reference_sound: orm.Mapped["ReferenceSound"] = orm.relationship(
        "ReferenceSound",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The reference sound."""


class SearchResult(Base):
    """Search Result model.

    Represents a single match found during a similarity search,
    linking a dataset clip to a search session with its similarity
    score and user-assigned label.
    """

    __tablename__ = "search_result"
    __table_args__ = (
        UniqueConstraint(
            "search_session_id",
            "clip_id",
        ),
    )

    # Fields without defaults (required fields) - must come first
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the search result."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the search result."""

    search_session_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("search_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The search session this result belongs to."""

    clip_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("clip.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The matched clip."""

    similarity: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
    )
    """Similarity score (0.0 to 1.0)."""

    rank: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
    )
    """Rank of this result (1 = most similar)."""

    # Fields with defaults (optional fields) - must come after required fields
    label: orm.Mapped[SearchResultLabel] = orm.mapped_column(
        sa.Enum(
            SearchResultLabel,
            name="search_result_label",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
        default=SearchResultLabel.UNLABELED,
        server_default=SearchResultLabel.UNLABELED.value,
    )
    """User-assigned label for this result."""

    labeled_by_id: orm.Mapped[UUID | None] = orm.mapped_column(
        ForeignKey("user.id"),
        nullable=True,
        default=None,
    )
    """The user who labeled this result."""

    labeled_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    """Timestamp when this result was labeled."""

    notes: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional notes about this result."""

    # Relationships
    search_session: orm.Mapped[SearchSession] = orm.relationship(
        "SearchSession",
        back_populates="search_results",
        init=False,
        repr=False,
    )
    """The search session this result belongs to."""

    clip: orm.Mapped["Clip"] = orm.relationship(
        "Clip",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The matched clip."""

    labeled_by: orm.Mapped["User | None"] = orm.relationship(
        "User",
        foreign_keys=[labeled_by_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The user who labeled this result."""
