"""Annotation model for detection review workflow.

This is a NEW annotation model for the detection review feature (003-detection-review).
It is separate from the existing clip_annotations and sound_event_annotations tables
which belong to the annotation project workflow.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import DetectionSource, DetectionStatus

if TYPE_CHECKING:
    from echoroo.models.detection_run import DetectionRun
    from echoroo.models.recording import Recording
    from echoroo.models.search_session import SearchSession
    from echoroo.models.tag import Tag
    from echoroo.models.user import User


class Annotation(UUIDMixin, TimestampMixin, Base):
    """Detection annotation for a specific time region in a recording.

    Created by ML models (BirdNET, Perch) or human reviewers. Can be confirmed,
    rejected, or left unreviewed. Supports frequency range for spectrogram display.

    Attributes:
        id: Unique identifier (UUID)
        recording_id: Foreign key to the source recording
        tag_id: Optional foreign key to species/sound tag
        detection_run_id: Optional foreign key to the ML run that created this
        source: Source of the detection (birdnet, perch_search, human)
        status: Review status (unreviewed, confirmed, rejected)
        confidence: Model confidence score (0.0-1.0), None for human annotations
        start_time: Start time in seconds within the recording
        end_time: End time in seconds within the recording
        freq_low: Optional lower frequency bound in Hz
        freq_high: Optional upper frequency bound in Hz
        reviewed_by_id: Optional FK to user who reviewed this annotation
        reviewed_at: Optional timestamp of review action
    """

    __tablename__ = "annotations"

    recording_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        doc="Source recording ID",
    )
    tag_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="SET NULL"),
        nullable=True,
        doc="Species or sound type tag ID",
    )
    detection_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("detection_runs.id", ondelete="SET NULL"),
        nullable=True,
        doc="ML detection run that created this annotation",
    )
    source: Mapped[DetectionSource] = mapped_column(
        Enum(
            DetectionSource,
            name="detectionsource",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        doc="Source of the detection",
    )
    status: Mapped[DetectionStatus] = mapped_column(
        Enum(
            DetectionStatus,
            name="detectionstatus",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        default=DetectionStatus.UNREVIEWED,
        nullable=False,
        doc="Review status",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Model confidence score (0.0-1.0)",
    )
    start_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Start time in seconds within the recording",
    )
    end_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="End time in seconds within the recording",
    )
    freq_low: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Lower frequency bound in Hz",
    )
    freq_high: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Upper frequency bound in Hz",
    )
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who reviewed this annotation",
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp of review action",
    )
    search_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("search_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Search session that created this annotation",
    )

    # Relationships
    recording: Mapped[Recording] = relationship(
        "Recording",
        lazy="raise",
    )
    tag: Mapped[Tag | None] = relationship(
        "Tag",
        lazy="raise",
    )
    detection_run: Mapped[DetectionRun | None] = relationship(
        "DetectionRun",
        back_populates="annotations",
        lazy="raise",
    )
    reviewed_by: Mapped[User | None] = relationship(
        "User",
        lazy="raise",
    )
    search_session: Mapped[SearchSession | None] = relationship(
        "SearchSession",
        back_populates="annotations",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_annotations_recording_id", "recording_id"),
        Index("ix_annotations_tag_id", "tag_id"),
        Index("ix_annotations_detection_run_id", "detection_run_id"),
        Index("ix_annotations_status", "status"),
        Index("ix_annotations_source", "source"),
        Index("ix_annotations_confidence", "confidence"),
    )

    def __repr__(self) -> str:
        return f"<Annotation(id={self.id}, source={self.source}, status={self.status})>"
