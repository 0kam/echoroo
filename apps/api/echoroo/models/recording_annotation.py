"""RecordingAnnotation — recording-level annotation (transitional name).

This "rich-shape" annotation row carries ``recording_id`` / ``tag_id`` /
``status`` / ``confidence`` / ``start_time`` / ``end_time`` / ``freq_low`` /
``freq_high`` / ``reviewed_by_id`` / ``reviewed_at`` / ``search_session_id`` /
``detection_run_id``.

The table ``recording_annotations_DEFERRED`` **exists** in the database: it
is created by migration ``0011_recording_annotations_placeholder.py`` and is
actively written and read at runtime. Real callers that depend on it include
the ML classifier (custom-SVM inference + seed/AL sampling), search-session
review annotations (queried/deleted by ``search_session_id`` in
:mod:`echoroo.services.search_session`), the detection review grid /
service, cross-model evaluation, and detection export. The ``_DEFERRED``
suffix is a *transitional placeholder name*: it is pending a future rename to
``recording_annotations``, NOT a marker that the table is absent. The
identifier is double-quoted everywhere so PostgreSQL preserves the mixed-case
suffix.

A future migration that finalises the schema is expected to rename
``__tablename__`` here from ``recording_annotations_DEFERRED`` to
``recording_annotations`` and update this docstring.

Note: :class:`echoroo.models.annotation.Annotation` is the separate, minimal
detection-based shape (``id`` / ``detection_id`` / ``user_id`` / ``source`` /
``taxon_id`` / ``label``) and carries no ``search_session_id`` column;
callers needing the rich recording-level fields use this model instead.
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

    See the module docstring. ``__tablename__`` points at the existing
    ``recording_annotations_DEFERRED`` table (created by migration 0011 and
    actively written/read at runtime). The ``_DEFERRED`` suffix is a
    transitional placeholder name pending the Phase 14+ rename to
    ``recording_annotations``; it does not imply the table is absent.
    """

    __tablename__ = "recording_annotations_DEFERRED"

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
            f" status={self.status}) DEFERRED Phase14+>"
        )
