"""RecordingAnnotation — recording-level annotation (canonical table).

This "rich-shape" annotation row carries ``recording_id`` / ``tag_id`` /
``status`` / ``confidence`` / ``start_time`` / ``end_time`` / ``freq_low`` /
``freq_high`` / ``reviewed_by_id`` / ``reviewed_at`` / ``search_session_id`` /
``detection_run_id``.

The table is named ``recording_annotations``. It was originally materialised
by migration ``0011_recording_annotations_placeholder.py`` under the
transitional placeholder name ``recording_annotations_DEFERRED`` and renamed to
its final canonical name by migration
``0029_rename_recording_annotations_final.py`` (P3 of the
annotation-consolidation effort). The transitional ``_DEFERRED`` suffix is
gone. The table is actively written and read at runtime. Real callers that
depend on it include the ML classifier (custom-SVM inference + seed/AL
sampling), search-session review annotations (queried/deleted by
``search_session_id`` in :mod:`echoroo.services.search_session`), the
detection review grid / service, cross-model evaluation, and detection export.

Note: an older, minimal detection-based ``Annotation`` model (``id`` /
``detection_id`` / ``user_id`` / ``source`` / ``taxon_id`` / ``label``) and its
backing ``annotations`` table were removed in P4 of the annotation-consolidation
effort (migration ``0030``). ``RecordingAnnotation`` is now the single canonical
annotation model; all callers use it directly.
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


class RecordingAnnotation(UUIDMixin, TimestampMixin, Base):
    """Recording-level annotation (rich shape).

    See the module docstring. ``__tablename__`` is the canonical
    ``recording_annotations`` table (materialised by migration 0011, renamed
    from the transitional ``recording_annotations_DEFERRED`` placeholder to its
    final name by migration 0029, and actively written/read at runtime).
    """

    __tablename__ = "recording_annotations"

    recording_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
    )
    tag_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="SET NULL"),
        nullable=True,
    )
    detection_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("detection_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[DetectionSource] = mapped_column(
        Enum(
            DetectionSource,
            name="detectionsource",
            create_type=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
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
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    freq_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    freq_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    search_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("search_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships ------------------------------------------------------ #
    recording: Mapped[Recording] = relationship("Recording", lazy="raise")
    tag: Mapped[Tag | None] = relationship("Tag", lazy="raise")
    detection_run: Mapped[DetectionRun | None] = relationship(
        "DetectionRun",
        back_populates="annotations",
        lazy="raise",
    )
    reviewed_by: Mapped[User | None] = relationship("User", lazy="raise")
    search_session: Mapped[SearchSession | None] = relationship(
        "SearchSession",
        back_populates="annotations",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_recording_annotations_recording", "recording_id"),
        Index("ix_recording_annotations_tag", "tag_id"),
        Index("ix_recording_annotations_run", "detection_run_id"),
        Index("ix_recording_annotations_status", "status"),
        Index("ix_recording_annotations_source", "source"),
        Index("ix_recording_annotations_confidence", "confidence"),
    )

    def __repr__(self) -> str:
        return (
            f"<RecordingAnnotation(id={self.id}, source={self.source},"
            f" status={self.status})>"
        )
