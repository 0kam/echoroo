"""Detection model — ML or human-emitted candidate bounding box on a recording.

Phase 13 P0a (T801): the existing ``detections`` table predates the 006
permissions redesign and is the only ``DB only`` table that the rebuilt ORM
must adopt as canonical. The schema below mirrors the live ``\\d detections``
output captured in the Phase 13 inventory (T800):

- ``id`` UUID PK with ``gen_random_uuid()`` server default
- ``recording_id`` UUID NOT NULL, FK ``recordings.id`` ON DELETE CASCADE
- ``project_id`` UUID NOT NULL, FK ``projects.id`` ON DELETE CASCADE
- ``taxon_id`` VARCHAR(64) NULL — legacy GBIF taxon key (string-formatted
  integer); a future migration (Phase 14+) will rebind it to ``taxa.id``
- ``source`` ENUM ``detectionsource`` NOT NULL
- ``status`` ENUM ``detectionstatus`` NOT NULL DEFAULT ``'unreviewed'``
- ``start_time`` / ``end_time`` DOUBLE PRECISION NOT NULL (seconds)
- ``confidence`` DOUBLE PRECISION NULL
- ``created_at`` / ``updated_at`` TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT
  ``now()``

Indexes (existing, recreated idempotently by the static migration):

- ``ix_detections_project_taxon`` on ``(project_id, taxon_id)``
- ``ix_detections_recording`` on ``(recording_id)``
- ``ix_detections_created_at`` from :class:`TimestampMixin`

The migration emits ``CREATE TABLE IF NOT EXISTS`` so live rows survive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, Float, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import DetectionSource, DetectionStatus

if TYPE_CHECKING:
    pass


class Detection(UUIDMixin, TimestampMixin, Base):
    """Detection candidate on a recording (ML- or human-emitted).

    A ``Detection`` is the fundamental unit of evidence used by the
    annotation/voting workflow (FR-070..FR-079). It is project-scoped (FR-005)
    and is created either by a model run (``detection_runs``), a similarity
    search session, a custom SVM, or by a human reviewer.
    """

    __tablename__ = "detections"

    recording_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        doc="Recording this detection belongs to",
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Project scope (FR-005)",
    )
    taxon_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc=(
            "Legacy taxon identifier — currently a stringified GBIF taxon "
            "key. Phase 14+ migration will swap to a UUID FK to taxa.id."
        ),
    )
    source: Mapped[DetectionSource] = mapped_column(
        Enum(
            DetectionSource,
            name="detectionsource",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            create_type=False,
        ),
        nullable=False,
        doc="How this detection was produced (FR-070)",
    )
    status: Mapped[DetectionStatus] = mapped_column(
        Enum(
            DetectionStatus,
            name="detectionstatus",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
            create_type=False,
        ),
        nullable=False,
        server_default=text("'unreviewed'::detectionstatus"),
        doc="Review status (FR-071)",
    )
    start_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="Start time of the detection in seconds (relative to recording)",
    )
    end_time: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc="End time of the detection in seconds (relative to recording)",
    )
    confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Model confidence score (NULL for human-created detections)",
    )

    __table_args__ = (
        Index("ix_detections_project_taxon", "project_id", "taxon_id"),
        Index("ix_detections_recording", "recording_id"),
    )
