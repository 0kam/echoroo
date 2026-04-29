"""Annotation model — minimal DB-truth shape (Phase 13 P1.5 R2).

Phase 13 P1.5 R2 (Codex follow-up — Fatal): the ORM is now reduced to the
minimal column shape that actually exists in the database (per the baseline
``0001_baseline_permissions_redesign.py`` migration, table ``annotations``):

* ``id`` UUID PK with ``gen_random_uuid()`` server default (UUIDMixin)
* ``detection_id`` UUID NOT NULL FK ``detections.id`` ON DELETE CASCADE
* ``user_id`` UUID NULL FK ``users.id``
* ``source`` ENUM ``annotationsource`` NOT NULL
* ``taxon_id`` VARCHAR(64) NULL — legacy GBIF taxon key (string-formatted
  integer); rebinds to ``taxa.id`` in Phase 14+ alongside ``Detection``.
* ``label`` VARCHAR(200) NULL — free-text label
* ``created_at`` / ``updated_at`` TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT
  ``now()`` (TimestampMixin)

The previous rich-shape (``recording_id`` / ``tag_id`` / ``status`` /
``confidence`` / ``start_time`` / ``end_time`` / ``freq_low`` / ``freq_high``
/ ``reviewed_by_id`` / ``reviewed_at`` / ``search_session_id`` /
``detection_run_id``) was an in-memory test artefact: those columns never
existed on the production DB, so every API path that hit ``annotations``
with the rich-shape ORM was silently broken in production. The columns are
**deferred to Phase 14+** when a separate ``recording_annotations`` table
will reinstate them with their own review-state lifecycle (status /
confidence / voting / review history). Until that lands, recording-level
review state is sourced from :class:`echoroo.models.detection.Detection`
(which already carries ``recording_id`` / ``project_id`` / ``status`` /
``confidence`` / ``start_time`` / ``end_time``) and from
:class:`echoroo.models.annotation_vote.AnnotationVote` for the consensus
state (Phase 6 vote system).

Spec source of truth: ``/tmp/plan-merged-v5-final.md`` §0.1 "DB 真
(detection-based)、ORM 縮退".
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin
from echoroo.models.enums import AnnotationSource

if TYPE_CHECKING:
    from echoroo.models.detection import Detection
    from echoroo.models.user import User


class Annotation(UUIDMixin, TimestampMixin, Base):
    """Detection-based annotation row — DB-truth minimal shape.

    Each annotation references a parent :class:`Detection` (the recording-
    region candidate). Recording-level metadata (``recording_id`` /
    ``project_id`` / ``start_time`` / ``end_time`` / ``confidence``) is
    accessed via the ``detection`` relationship — this avoids duplicating
    the spatial / temporal columns and keeps the DB normalised.

    Phase 14+ deferred: a sibling ``recording_annotations`` table will carry
    the review-state lifecycle (status / suggested tag / freq band / freq
    band / reviewer info). Existing services that need those columns are
    moved to :class:`echoroo.models.recording_annotation.RecordingAnnotation`
    and skipped at runtime (the deferred table does not yet exist).
    """

    __tablename__ = "annotations"

    detection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("detections.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent detection (FR-070..FR-079 candidate region).",
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        doc=(
            "Annotator user — NULL for ML-emitted annotations. The Phase 6"
            " voting system tracks voter identity separately on"
            " ``annotation_votes.voter_user_id``."
        ),
    )
    source: Mapped[AnnotationSource] = mapped_column(
        Enum(
            AnnotationSource,
            name="annotationsource",
            create_type=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        doc="How this annotation was produced (ML model / human / etc).",
    )
    taxon_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc=(
            "Legacy taxon identifier — currently a stringified GBIF taxon"
            " key. Phase 14+ migration will swap to a UUID FK to taxa.id"
            " alongside the Detection table."
        ),
    )
    label: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        doc="Free-text label (used by human annotators when no taxon match).",
    )

    # Relationships ------------------------------------------------------ #
    detection: Mapped[Detection] = relationship(
        "Detection",
        lazy="raise",
        doc="Parent Detection — carries recording_id, project_id, time range.",
    )
    user: Mapped[User | None] = relationship(
        "User",
        lazy="raise",
        doc="Annotator user (NULL for ML-emitted rows).",
    )

    __table_args__ = (
        Index("ix_annotations_detection", "detection_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<Annotation(id={self.id}, detection_id={self.detection_id},"
            f" source={self.source})>"
        )
