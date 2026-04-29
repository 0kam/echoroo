"""Ground-truth annotation models for cross-model evaluation (spec 003-annotation).

This module introduces the *new* annotation subsystem used to produce a
reference ground-truth dataset that can fairly evaluate detection models
(BirdNET 3s, Perch 5s, Custom classifiers) regardless of their internal window
size. The existing detection-review ``Annotation`` and ``AnnotationVote``
models under ``echoroo.models.annotation`` are deliberately untouched; the new
entity is named ``TimeRangeAnnotation`` to avoid a name collision.

Entities:
    - ``AnnotationSet``: top-level container scoped to a project + dataset with
      sampling parameters and a per-set species palette.
    - ``AnnotationSegment``: one materialized fixed-length segment of a
      recording, independently annotatable, with an explicit ``is_empty``
      marker required for recall-denominator integrity.
    - ``TimeRangeAnnotation``: a ``[start, end]`` interval inside a segment
      tagged with a single taxon (species).
    - ``AnnotationSetSpeciesPalette``: M2M link from a set to ``Taxon`` rows
      (palette membership; does NOT constrain which taxa may be annotated).
    - ``AnnotationSegmentNote`` / ``TimeRangeAnnotationNote``: association
      tables linking to the existing ``Note`` entity so that comments can be
      attached to either a segment or an individual time-range annotation.

Species identity is captured via a FK to the existing ``taxa`` table. The
spec text refers to "Species" generically; in this codebase the canonical
taxonomic entity is ``Taxon``, so ``taxon_id`` is used throughout while
docstrings preserve the domain term "species" where helpful.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import AnnotationSegmentStatus, AnnotationSetStatus

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.note import Note
    from echoroo.models.project import Project
    from echoroo.models.recording import Recording
    from echoroo.models.taxon import Taxon
    from echoroo.models.user import User


# ---------------------------------------------------------------------------
# Association tables
# ---------------------------------------------------------------------------

# Per-set species palette. Removing a row does NOT cascade to existing
# TimeRangeAnnotations — the palette is a UI filter, not an integrity
# boundary on which taxa may be annotated.
annotation_set_species_palette = Table(
    "annotation_set_species_palette",
    Base.metadata,
    Column(
        "annotation_set_id",
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_sets.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "taxon_id",
        PG_UUID(as_uuid=True),
        ForeignKey("taxa.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "position",
        Integer,
        nullable=False,
        server_default="0",
        doc="Ordering hint for palette display / keyboard shortcut slots",
    ),
)


# Note <-> AnnotationSegment association.
annotation_segment_notes = Table(
    "annotation_segment_notes",
    Base.metadata,
    Column(
        "segment_id",
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_segments.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "note_id",
        PG_UUID(as_uuid=True),
        ForeignKey("notes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# Note <-> TimeRangeAnnotation association.
time_range_annotation_notes = Table(
    "time_range_annotation_notes",
    Base.metadata,
    Column(
        "annotation_id",
        PG_UUID(as_uuid=True),
        ForeignKey("time_range_annotations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "note_id",
        PG_UUID(as_uuid=True),
        ForeignKey("notes.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


# ---------------------------------------------------------------------------
# AnnotationSet
# ---------------------------------------------------------------------------


class AnnotationSet(UUIDMixin, TimestampMixin, Base):
    """A named reference collection of ground-truth segments.

    One set defines *what the ground truth covers*: a dataset, optional date
    and time-of-day filters, a fixed segment length (>= 10 s) and a target
    segment count. A background sampling job materializes ``AnnotationSegment``
    rows that satisfy the filter. Evaluation runs are later scoped to a set.

    Attributes:
        id: Unique identifier (UUID).
        project_id: Owning project (FK, CASCADE).
        dataset_id: Source dataset (FK, CASCADE).
        created_by_id: Creator user (FK, RESTRICT via ``ON DELETE`` default).
        name: Display name; unique within a project.
        filter_date_range: Optional ``{"start": "YYYY-MM-DD", "end": ...}``
            JSONB restricting candidate recordings by ``datetime``.
        filter_time_of_day_range: Optional ``{"start": "HH:MM", "end": ...}``
            JSONB restricting by local time of day (may wrap midnight).
        segment_length_sec: Integer length of every sampled segment, >= 10.
        num_segments: Target number of segments, >= 1. Actual count may be
            smaller if the filtered pool is insufficient; see
            ``sampling_warning``.
        status: ``sampling | ready | in_progress | completed`` (see
            ``AnnotationSetStatus``).
        sampling_warning: Optional human-readable warning, e.g. "only 42 of
            100 segments available after filters".
    """

    __tablename__ = "annotation_sets"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning project ID",
    )
    dataset_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="CASCADE"),
        nullable=False,
        doc="Source dataset ID",
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="Creator user ID",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Display name (unique within project)",
    )
    filter_date_range: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc='Optional {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} date filter',
    )
    filter_time_of_day_range: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc='Optional {"start": "HH:MM", "end": "HH:MM"} local time-of-day filter',
    )
    segment_length_sec: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Length in seconds of every sampled segment (>= 10)",
    )
    num_segments: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        doc="Target segment count (>= 1)",
    )
    status: Mapped[AnnotationSetStatus] = mapped_column(
        Enum(
            AnnotationSetStatus,
            name="annotation_set_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AnnotationSetStatus.SAMPLING,
        server_default=AnnotationSetStatus.SAMPLING.value,
        nullable=False,
        doc="Lifecycle status",
    )
    sampling_warning: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Human-readable sampling warning (e.g. underfill notice)",
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        lazy="raise",
    )
    dataset: Mapped[Dataset] = relationship(
        "Dataset",
        lazy="raise",
    )
    created_by: Mapped[User] = relationship(
        "User",
        lazy="raise",
    )
    segments: Mapped[list[AnnotationSegment]] = relationship(
        "AnnotationSegment",
        back_populates="annotation_set",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    species_palette: Mapped[list[Taxon]] = relationship(
        "Taxon",
        secondary=annotation_set_species_palette,
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_annotation_sets_project_name"),
        CheckConstraint(
            "segment_length_sec >= 10",
            name="ck_annotation_sets_segment_length_min",
        ),
        CheckConstraint(
            "num_segments >= 1",
            name="ck_annotation_sets_num_segments_min",
        ),
        Index("ix_annotation_sets_project_id", "project_id"),
        Index("ix_annotation_sets_dataset_id", "dataset_id"),
        Index("ix_annotation_sets_status", "status"),
        Index(
            "ix_annotation_sets_project_status", "project_id", "status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AnnotationSet(id={self.id}, name={self.name!r}, "
            f"status={self.status!r}, num_segments={self.num_segments})>"
        )


# ---------------------------------------------------------------------------
# AnnotationSegment
# ---------------------------------------------------------------------------


class AnnotationSegment(UUIDMixin, TimestampMixin, Base):
    """One fixed-length segment of a recording, independently annotatable.

    Segments are materialized by the sampling job so that evaluation bookkeeping
    (cropping detections to ground-truth windows) is trivial. Each segment
    either carries one or more ``TimeRangeAnnotation`` rows or is explicitly
    marked empty via ``is_empty``. The explicit empty marker is essential for
    recall's denominator: it distinguishes "annotator confirmed silence" from
    "annotator never looked at this segment".

    Invariants (enforced by the service layer, not the DB):
        - If ``status = annotated`` and no ``TimeRangeAnnotation`` rows exist,
          ``is_empty`` MUST be True.
        - Creating a ``TimeRangeAnnotation`` on this segment MUST flip
          ``is_empty`` to False.
        - Setting ``is_empty = True`` MUST reject the change when at least one
          ``TimeRangeAnnotation`` exists.

    Attributes:
        id: Unique identifier (UUID).
        annotation_set_id: Owning set (FK, CASCADE).
        recording_id: Source recording (FK, CASCADE).
        start_time_sec: Offset inside the recording (>= 0).
        end_time_sec: End offset inside the recording (> start_time_sec,
            and <= recording.duration_sec — enforced at sampling time).
        is_empty: Explicit "no target calls" flag; required for recall.
        status: ``unannotated | annotated | skipped``.
        annotated_by_id: User who finalized the segment (nullable).
        annotated_at: Timestamp of finalization (nullable).
    """

    __tablename__ = "annotation_segments"

    annotation_set_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_sets.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning AnnotationSet ID",
    )
    recording_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        doc="Source Recording ID",
    )
    start_time_sec: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Segment start offset in seconds inside the recording",
    )
    end_time_sec: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Segment end offset in seconds inside the recording",
    )
    is_empty: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc="True when the annotator confirmed no target vocalizations",
    )
    status: Mapped[AnnotationSegmentStatus] = mapped_column(
        Enum(
            AnnotationSegmentStatus,
            name="annotation_segment_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=AnnotationSegmentStatus.UNANNOTATED,
        server_default=AnnotationSegmentStatus.UNANNOTATED.value,
        nullable=False,
        doc="Lifecycle status",
    )
    annotated_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who finalized the segment (set when status transitions to annotated)",
    )
    annotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of finalization",
    )

    # Relationships
    annotation_set: Mapped[AnnotationSet] = relationship(
        "AnnotationSet",
        back_populates="segments",
        lazy="raise",
    )
    recording: Mapped[Recording] = relationship(
        "Recording",
        lazy="raise",
    )
    annotated_by: Mapped[User | None] = relationship(
        "User",
        lazy="raise",
    )
    annotations: Mapped[list[TimeRangeAnnotation]] = relationship(
        "TimeRangeAnnotation",
        back_populates="segment",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    notes: Mapped[list[Note]] = relationship(
        "Note",
        secondary=annotation_segment_notes,
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint(
            "start_time_sec >= 0",
            name="ck_annotation_segments_start_nonneg",
        ),
        CheckConstraint(
            "end_time_sec > start_time_sec",
            name="ck_annotation_segments_end_after_start",
        ),
        Index("ix_annotation_segments_set_id", "annotation_set_id"),
        Index("ix_annotation_segments_recording_id", "recording_id"),
        Index("ix_annotation_segments_status", "status"),
        Index(
            "ix_annotation_segments_set_status",
            "annotation_set_id",
            "status",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AnnotationSegment(id={self.id}, set_id={self.annotation_set_id}, "
            f"status={self.status!r}, is_empty={self.is_empty})>"
        )


# ---------------------------------------------------------------------------
# TimeRangeAnnotation
# ---------------------------------------------------------------------------


class TimeRangeAnnotation(UUIDMixin, TimestampMixin, Base):
    """A ``[start, end]`` time interval inside a segment tagged with one taxon.

    Ground-truth annotation unit. Frequency range and multi-tag membership are
    intentionally excluded (see ``specs/003-annotation/research.md``); matching
    during evaluation is performed on time overlap + species identity only.

    Overlapping rows on the same segment — with the same or different
    ``taxon_id`` — are allowed.

    Attributes:
        id: Unique identifier (UUID).
        segment_id: Owning segment (FK, CASCADE).
        start_time_sec: Offset inside the segment (>= 0).
        end_time_sec: End offset inside the segment (> start_time_sec and
            <= segment.end_time_sec - segment.start_time_sec; enforced at the
            service layer).
        taxon_id: FK to the existing ``taxa`` table. Delete-restricted to
            protect ground-truth integrity.
        confidence: Optional annotator-declared confidence in [0, 1].
        created_by_id: Author user (FK).
    """

    __tablename__ = "time_range_annotations"

    segment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_segments.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning AnnotationSegment ID",
    )
    start_time_sec: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Start offset in seconds inside the segment",
    )
    end_time_sec: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="End offset in seconds inside the segment",
    )
    taxon_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taxa.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Species (taxon) label; delete-restricted to preserve ground truth",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Annotator-declared confidence in [0, 1]",
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="Author user ID",
    )

    # Relationships
    segment: Mapped[AnnotationSegment] = relationship(
        "AnnotationSegment",
        back_populates="annotations",
        lazy="raise",
    )
    taxon: Mapped[Taxon] = relationship(
        "Taxon",
        lazy="raise",
    )
    created_by: Mapped[User] = relationship(
        "User",
        lazy="raise",
    )
    notes: Mapped[list[Note]] = relationship(
        "Note",
        secondary=time_range_annotation_notes,
        lazy="raise",
    )

    __table_args__ = (
        CheckConstraint(
            "start_time_sec >= 0",
            name="ck_time_range_annotations_start_nonneg",
        ),
        CheckConstraint(
            "end_time_sec > start_time_sec",
            name="ck_time_range_annotations_end_after_start",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_time_range_annotations_confidence_unit",
        ),
        Index("ix_time_range_annotations_segment_id", "segment_id"),
        Index("ix_time_range_annotations_taxon_id", "taxon_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<TimeRangeAnnotation(id={self.id}, segment_id={self.segment_id}, "
            f"taxon_id={self.taxon_id}, start={self.start_time_sec}, "
            f"end={self.end_time_sec})>"
        )
