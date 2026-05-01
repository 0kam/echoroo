"""RecordingAnnotation — Phase 14+ deferred recording-level annotation.

Phase 13 P1.5 R2 (Codex follow-up — Fatal): the legacy "rich-shape"
annotation row (``recording_id`` / ``tag_id`` / ``status`` / ``confidence``
/ ``start_time`` / ``end_time`` / ``freq_low`` / ``freq_high`` /
``reviewed_by_id`` / ``reviewed_at`` / ``search_session_id`` /
``detection_run_id``) lives here as a Phase 14+ deferred ORM model. The
table name ``recording_annotations_DEFERRED`` does **not** exist in the
database — the model is provided so that legacy callers (search session
results, evaluation, detection export, annotation projects, etc.) keep
compiling at the type layer while the recording-level review-state
lifecycle is rebuilt in Phase 14+.

Any runtime code path that hits this table (``SELECT`` / ``INSERT`` /
``UPDATE`` / ``DELETE``) will fail with a PostgreSQL ``relation does not
exist`` error — by design. Callers that need to operate on Phase 6 data
must use :class:`echoroo.models.annotation.Annotation` (the minimal
detection-based shape) plus :class:`echoroo.models.detection.Detection`
for recording-level fields.

The Phase 14+ migration that materialises ``recording_annotations`` will:

* Create the table with the rich-shape columns documented below
* Add unique constraint ``(recording_id, tag_id, start_time, end_time)``
  (or similar) for de-duplication
* Backfill from existing ``Detection`` rows + ``annotations`` rows
* Reactivate the contract / integration tests skipped in this phase
* Replace the ``__tablename__`` here from ``recording_annotations_DEFERRED``
  to ``recording_annotations`` and drop this docstring

Spec source of truth: ``/tmp/plan-merged-v5-final.md`` §0.1 "DB 真
(detection-based)、ORM 縮退" — the rich shape was confirmed as Phase 14+
deferred, not Phase 13 production.
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
    """Recording-level annotation — Phase 14+ deferred.

    See module docstring. The ``__tablename__`` intentionally points at a
    non-existent table so any production query fails loudly. Legacy services
    that depend on this shape are tagged Phase 14+ deferred.
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
