"""Search Session and Search Result models for Active Learning.

A Search Session represents an active learning search operation within
an ML Project. Each session can target multiple species/sound tags and
uses a set of reference sounds to find similar clips in the dataset.

The active learning process involves:
1. Initial sampling from reference sounds (easy positives, boundary, others)
2. User labeling of samples with target tags or negative/uncertain flags
3. Iterative model training and sample selection based on labels
4. Progressive refinement of the search model

Search Results are individual samples found during a search session.
Each result links a dataset clip to the search session with its
sampling metadata and user-assigned labels.
"""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from echoroo.models.base import Base
from echoroo.models.tag import Tag

if TYPE_CHECKING:
    from echoroo.models.annotation_project import AnnotationProject
    from echoroo.models.cached_model import CachedModel
    from echoroo.models.clip import Clip
    from echoroo.models.ml_project import MLProject, MLProjectDatasetScope
    from echoroo.models.reference_sound import ReferenceSound
    from echoroo.models.user import User

__all__ = [
    "SampleType",
    "SearchSession",
    "SearchSessionDatasetScope",
    "SearchSessionReferenceSound",
    "SearchSessionTargetTag",
    "SearchResult",
    "SearchResultTag",
    "IterationScoreDistribution",
]


class SampleType(str, enum.Enum):
    """Sample type for search results.

    Represents how a search result was selected for labeling:
    - EASY_POSITIVE: Top-k most similar clips to reference sounds
    - BOUNDARY: Random samples from medium similarity range
    - OTHERS: Diverse samples using farthest-first selection
    - ACTIVE_LEARNING: Samples selected by active learning iteration
    """

    EASY_POSITIVE = "easy_positive"
    BOUNDARY = "boundary"
    OTHERS = "others"
    ACTIVE_LEARNING = "active_learning"


class SearchSession(Base):
    """Search Session model for Active Learning.

    Represents an active learning search operation targeting multiple
    species/sounds within an ML project.
    """

    __tablename__ = "search_session"

    # Primary key
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the search session."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the search session."""

    # Required fields
    name: orm.Mapped[str] = orm.mapped_column(nullable=False)
    """A descriptive name for this search session."""

    ml_project_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("ml_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The ML project this search session belongs to."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        ForeignKey("user.id"),
        nullable=False,
    )
    """The user who created this search session."""

    # Optional fields with defaults
    description: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional description of the search session goals."""

    # Active Learning sampling parameters
    easy_positive_k: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=5,
    )
    """Number of top-k similar clips to select per reference sound (easy positives)."""

    boundary_n: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=200,
    )
    """Number of boundary samples (medium similarity) to consider."""

    boundary_m: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=10,
    )
    """Number of boundary samples to actually select from boundary_n candidates."""

    others_p: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=20,
    )
    """Number of 'other' samples (low similarity) to include."""

    distance_metric: orm.Mapped[str] = orm.mapped_column(
        nullable=False,
        default="cosine",
    )
    """Distance metric for similarity search: 'cosine' or 'euclidean'."""

    # Iteration tracking
    current_iteration: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Current active learning iteration number (0 = initial sampling)."""

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

    search_all_scopes: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=True,
    )
    """Whether to search all dataset scopes or only selected ones."""

    distance_metric: orm.Mapped[str] = orm.mapped_column(
        nullable=False,
        default="cosine",
    )
    """Distance metric to use: 'cosine' or 'euclidean'."""

    # Relationships
    ml_project: orm.Mapped["MLProject"] = orm.relationship(
        "MLProject",
        back_populates="search_sessions",
        init=False,
        repr=False,
    )
    """The ML project this search session belongs to."""

    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The user who created this search session."""

    # Target tags for this search session (multi-tag support)
    target_tags: orm.Mapped[list["SearchSessionTargetTag"]] = orm.relationship(
        "SearchSessionTargetTag",
        back_populates="search_session",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Target tags for this search session with shortcut keys."""

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

    # Dataset scopes for multi-dataset search
    dataset_scopes: orm.Mapped[list["SearchSessionDatasetScope"]] = orm.relationship(
        "SearchSessionDatasetScope",
        back_populates="search_session",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Dataset scopes for this search session (if not search_all_scopes)."""

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

    # Cached models for active learning
    cached_models: orm.Mapped[list["CachedModel"]] = orm.relationship(
        "CachedModel",
        back_populates="search_session",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Cached models for active learning iterations."""


class SearchSessionTargetTag(Base):
    """Search Session Target Tag model.

    Links target tags to search sessions with keyboard shortcut assignments.
    Multiple tags can be targeted per session, each with a unique shortcut key.
    """

    __tablename__ = "search_session_target_tag"
    __table_args__ = (
        UniqueConstraint(
            "search_session_id",
            "tag_id",
            name="uq_search_session_target_tag_session_tag",
        ),
        UniqueConstraint(
            "search_session_id",
            "shortcut_key",
            name="uq_search_session_target_tag_session_shortcut",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the target tag entry."""

    search_session_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("search_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The search session ID."""

    tag_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The target tag ID."""

    shortcut_key: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
    )
    """Keyboard shortcut key (1-9) for quick labeling."""

    # Relationships
    search_session: orm.Mapped[SearchSession] = orm.relationship(
        "SearchSession",
        back_populates="target_tags",
        init=False,
        repr=False,
    )
    """The search session."""

    tag: orm.Mapped[Tag] = orm.relationship(
        "Tag",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The target tag."""


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
    """Search Result model for Active Learning.

    Represents a single sample found during an active learning search,
    linking a dataset clip to a search session with its sampling metadata
    and user-assigned labels.
    """

    __tablename__ = "search_result"
    __table_args__ = (
        UniqueConstraint(
            "search_session_id",
            "clip_id",
        ),
    )

    # Primary key
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the search result."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the search result."""

    # Required fields
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

    # Labeling fields (multi-label support via search_result_tag table)
    is_negative: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=False,
    )
    """Whether this result is marked as negative (not containing target sound)."""

    is_uncertain: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=False,
    )
    """Whether this result is marked as uncertain."""

    is_skipped: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=False,
    )
    """Whether this result was skipped during labeling."""

    # Sampling metadata
    sample_type: orm.Mapped[SampleType | None] = orm.mapped_column(
        Enum(SampleType, name="sample_type", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
        default=None,
    )
    """Type of sample: easy_positive, boundary, others, or active_learning."""

    iteration_added: orm.Mapped[int | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """The active learning iteration when this sample was added."""

    model_score: orm.Mapped[float | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Model prediction score for active learning samples."""

    source_tag_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The source tag from which this sample was derived (for easy_positive samples)."""

    # User tracking
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

    raw_score: orm.Mapped[float | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Raw score value (cosine: similarity 0-1, euclidean: distance 0-inf)."""

    saved_to_annotation_project_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("annotation_project.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The annotation project this result was exported to (if any)."""

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

    source_tag: orm.Mapped[Tag | None] = orm.relationship(
        "Tag",
        foreign_keys=[source_tag_id],
        lazy="joined",
        init=False,
        repr=False,
    )
    """The source tag for easy_positive samples."""

    labeled_by: orm.Mapped["User | None"] = orm.relationship(
        "User",
        foreign_keys=[labeled_by_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The user who labeled this result."""

    saved_to_annotation_project: orm.Mapped["AnnotationProject | None"] = (
        orm.relationship(
            "AnnotationProject",
            foreign_keys=[saved_to_annotation_project_id],
            viewonly=True,
            init=False,
            repr=False,
        )
    )
    """The annotation project this result was exported to."""

    # Multi-label support: relationship to assigned tags via junction table
    assigned_tags_rel: orm.Mapped[list["SearchResultTag"]] = orm.relationship(
        "SearchResultTag",
        back_populates="search_result",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Tags assigned to this result (multi-label support)."""


class SearchResultTag(Base):
    """Junction table for many-to-many relationship between SearchResult and Tag.

    This enables multi-label classification where a single search result
    can be assigned multiple tags (e.g., when a segment contains multiple
    species vocalizations).
    """

    __tablename__ = "search_result_tag"
    __table_args__ = (
        UniqueConstraint(
            "search_result_id",
            "tag_id",
            name="uq_search_result_tag",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the search result tag entry."""

    search_result_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("search_result.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The search result ID."""

    tag_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The assigned tag ID."""

    created_on: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=datetime.datetime.now,
        init=False,
    )
    """Timestamp when this tag was assigned."""

    # Relationships
    search_result: orm.Mapped["SearchResult"] = orm.relationship(
        "SearchResult",
        back_populates="assigned_tags_rel",
        init=False,
        repr=False,
    )
    """The search result this tag is assigned to."""

    tag: orm.Mapped[Tag] = orm.relationship(
        "Tag",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The assigned tag."""


class SearchSessionDatasetScope(Base):
    """Search Session Dataset Scope model.

    Tracks which datasets have been searched within a search session
    and their progress statistics.
    """

    __tablename__ = "search_session_dataset_scope"
    __table_args__ = (
        UniqueConstraint(
            "search_session_id",
            "ml_project_dataset_scope_id",
            name="uq_search_session_dataset_scope",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the search session dataset scope."""

    search_session_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("search_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The search session this scope belongs to."""

    ml_project_dataset_scope_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("ml_project_dataset_scope.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The ML project dataset scope to search within."""

    clips_searched: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Number of clips searched in this dataset scope."""

    results_found: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Number of results found in this dataset scope."""

    # Relationships
    search_session: orm.Mapped[SearchSession] = orm.relationship(
        "SearchSession",
        back_populates="dataset_scopes",
        init=False,
        repr=False,
    )
    """The search session this scope belongs to."""

    ml_project_dataset_scope: orm.Mapped["MLProjectDatasetScope"] = orm.relationship(
        "MLProjectDatasetScope",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The ML project dataset scope."""


class IterationScoreDistribution(Base):
    """Stores score distribution computed during each iteration.

    During active learning iterations, we compute score distributions
    for each target tag to visualize model confidence and guide sampling.
    This model tracks histogram bin counts and statistics for each iteration.
    """

    __tablename__ = "iteration_score_distribution"

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the score distribution entry."""

    search_session_id: orm.Mapped[int] = orm.mapped_column(
        sa.ForeignKey("search_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The search session this distribution belongs to."""

    tag_id: orm.Mapped[int] = orm.mapped_column(
        sa.ForeignKey("tag.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The target tag for which this distribution was computed."""

    iteration: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
    )
    """Which iteration this was computed at (0 = initial, 1+ = active learning iterations)."""

    bin_counts: orm.Mapped[list[int]] = orm.mapped_column(
        ARRAY(sa.Integer),
        nullable=False,
    )
    """Histogram bin counts (20 bins representing score distribution)."""

    bin_edges: orm.Mapped[list[float]] = orm.mapped_column(
        ARRAY(sa.Float),
        nullable=False,
    )
    """Histogram bin edges (21 edges for 20 bins, typically [0.0, 0.05, ..., 1.0])."""

    positive_count: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
    )
    """Number of samples labeled positive at this iteration."""

    negative_count: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
    )
    """Number of samples labeled negative at this iteration."""

    mean_score: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
    )
    """Mean score across all samples at this iteration."""

    training_positive_scores: orm.Mapped[list[float]] = orm.mapped_column(
        ARRAY(sa.Float),
        nullable=False,
        default_factory=list,
    )
    """Prediction scores for positive training samples (for histogram overlay)."""

    training_negative_scores: orm.Mapped[list[float]] = orm.mapped_column(
        ARRAY(sa.Float),
        nullable=False,
        default_factory=list,
    )
    """Prediction scores for negative training samples (for histogram overlay)."""

    created_on: orm.Mapped[datetime.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=datetime.datetime.now,
        init=False,
    )
    """Timestamp when this distribution was computed."""

    # Relationships
    search_session: orm.Mapped[SearchSession] = orm.relationship(
        "SearchSession",
        init=False,
        repr=False,
    )
    """The search session this distribution belongs to."""

    tag: orm.Mapped[Tag] = orm.relationship(
        "Tag",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The target tag for this distribution."""
