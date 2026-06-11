"""Cross-model evaluation models (spec 003-annotation, Phase A3).

This module persists the results of applying detection models (BirdNET 3s,
Perch 5s, custom SVM classifiers) to the ground-truth segments of an
``AnnotationSet`` and scoring them with the symmetric-overlap rule defined
in ``specs/003-annotation/research.md`` §4.

Entities:
    - ``EvaluationRun``: one request to evaluate a set against one or more
      detection models. Tracks lifecycle state (pending/running/completed/
      failed) and the list of requested model references so the worker can
      iterate through them.
    - ``EvaluationResult``: one row of aggregated metrics for a given
      ``(run, model_ref, taxon_id)`` triple. ``taxon_id = NULL`` is the
      "overall" bucket combining every species together.

The detection annotations produced by BirdNET / Perch / Custom models are
stored in the canonical ``recording_annotations`` table
(``echoroo.models.recording_annotation.RecordingAnnotation``) with ``source``
discriminating the pipeline and ``tag_id -> Tag.taxon_id`` linking to the
canonical ``taxa`` row. For custom models the ``detection_run_id`` column
reaches ``detection_runs``, whose metadata identifies the source
``custom_model`` (see worker for matching logic).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.annotation_set import AnnotationSet
    from echoroo.models.taxon import Taxon
    from echoroo.models.user import User


class EvaluationRunStatus(StrEnum):
    """Lifecycle status of an :class:`EvaluationRun`.

    Values:
        PENDING: Row created, Celery task enqueued but not yet started.
        RUNNING: Worker is currently iterating over requested model refs.
        COMPLETED: All model refs evaluated successfully and results
            persisted.
        FAILED: Worker raised; ``error_message`` carries a human-readable
            explanation.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvaluationRun(UUIDMixin, TimestampMixin, Base):
    """One evaluation request over an annotation set.

    Attributes:
        id: Unique identifier (UUID).
        annotation_set_id: FK to the evaluated :class:`AnnotationSet`.
        created_by_id: FK to the user who requested the run.
        status: Lifecycle status (see :class:`EvaluationRunStatus`).
        requested_model_refs: JSONB list describing which detection models
            to evaluate. Each element is an object of the form
            ``{"kind": "birdnet"}``, ``{"kind": "perch"}`` or
            ``{"kind": "custom", "model_id": "<uuid>"}``.
        started_at: Timestamp of the first worker invocation (nullable).
        completed_at: Timestamp when the run reached a terminal state.
        error_message: Populated when ``status = failed``.
    """

    __tablename__ = "evaluation_runs"

    annotation_set_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotation_sets.id", ondelete="CASCADE"),
        nullable=False,
        doc="Evaluated AnnotationSet ID",
    )
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        doc="User who requested the evaluation",
    )
    status: Mapped[EvaluationRunStatus] = mapped_column(
        Enum(
            EvaluationRunStatus,
            name="evaluation_run_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=EvaluationRunStatus.PENDING,
        server_default=EvaluationRunStatus.PENDING.value,
        nullable=False,
        doc="Lifecycle status",
    )
    requested_model_refs: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        doc='List of {"kind": ..., ["model_id": ...]} model references',
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Worker start timestamp",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Worker completion timestamp (terminal status)",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error details when status = failed",
    )

    # Relationships
    annotation_set: Mapped[AnnotationSet] = relationship(
        "AnnotationSet",
        lazy="raise",
    )
    created_by: Mapped[User] = relationship(
        "User",
        lazy="raise",
    )
    results: Mapped[list[EvaluationResult]] = relationship(
        "EvaluationResult",
        back_populates="evaluation_run",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    # Note: ``created_at`` already has ``index=True`` via ``TimestampMixin``,
    # which auto-generates ``ix_evaluation_runs_created_at``. Declaring it here
    # again would collide with the auto-generated index name.
    __table_args__ = (
        Index("ix_evaluation_runs_annotation_set_id", "annotation_set_id"),
        Index("ix_evaluation_runs_status", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<EvaluationRun(id={self.id}, set_id={self.annotation_set_id}, "
            f"status={self.status!r})>"
        )


class EvaluationResult(UUIDMixin, TimestampMixin, Base):
    """Aggregated metrics for one ``(run, model_ref, taxon)`` bucket.

    A row with ``taxon_id IS NULL`` is the overall (all-species) aggregate
    for the run + model_ref. Per-species rows carry the concrete
    ``taxon_id``.

    Metric definitions (see research.md §4):
        - ``tp_precision``: detections that overlap at least one same-species
          GT row.
        - ``fp``: detections that do not overlap any same-species GT row.
        - ``tp_recall``: GT rows that are overlapped by at least one
          same-species detection.
        - ``fn``: GT rows not overlapped by any same-species detection.
        - ``precision = tp_precision / (tp_precision + fp)`` (0 when denom 0)
        - ``recall = tp_recall / (tp_recall + fn)`` (0 when denom 0)
        - ``f1 = 2 p r / (p + r)`` (0 when denom 0)

    The derived ``precision``, ``recall`` and ``f1`` fields are persisted to
    avoid recomputing them on every read (see research.md §7).
    """

    __tablename__ = "evaluation_results"

    evaluation_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"),
        nullable=False,
        doc="Parent EvaluationRun ID",
    )
    model_ref: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        doc='Model reference for this result bucket (same schema as '
        'EvaluationRun.requested_model_refs items)',
    )
    taxon_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taxa.id", ondelete="RESTRICT"),
        nullable=True,
        doc="Species (taxon) bucket; NULL = overall aggregate",
    )
    tp_precision: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Detections overlapping at least one same-species GT row",
    )
    fp: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Detections that overlap no same-species GT row",
    )
    tp_recall: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="GT rows overlapped by at least one same-species detection",
    )
    fn: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="GT rows not overlapped by any same-species detection",
    )
    precision: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Derived precision metric (persisted for query speed)",
    )
    recall: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Derived recall metric (persisted for query speed)",
    )
    f1: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        doc="Derived F1 metric (persisted for query speed)",
    )

    # Relationships
    evaluation_run: Mapped[EvaluationRun] = relationship(
        "EvaluationRun",
        back_populates="results",
        lazy="raise",
    )
    taxon: Mapped[Taxon | None] = relationship(
        "Taxon",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_evaluation_results_run_id", "evaluation_run_id"),
        Index(
            "ix_evaluation_results_run_taxon",
            "evaluation_run_id",
            "taxon_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<EvaluationResult(run={self.evaluation_run_id}, "
            f"taxon_id={self.taxon_id}, p={self.precision:.3f}, "
            f"r={self.recall:.3f}, f1={self.f1:.3f})>"
        )


__all__ = [
    "EvaluationRun",
    "EvaluationResult",
    "EvaluationRunStatus",
]
