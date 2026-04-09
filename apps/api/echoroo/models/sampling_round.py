"""SamplingRound and SamplingRoundItem models for model training overhaul."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.annotation import Annotation
    from echoroo.models.custom_model import CustomModel
    from echoroo.models.embedding import Embedding
    from echoroo.models.recording import Recording


class SamplingRound(UUIDMixin, TimestampMixin, Base):
    """A round of sampling that selects training examples for a CustomModel.

    Supports both initial seed sampling (round_type='seed') and subsequent
    active learning rounds (round_type='active_learning').

    Attributes:
        id: Unique identifier (UUID)
        custom_model_id: Foreign key to the owning CustomModel
        round_number: Sequential round number (0 for seed round)
        round_type: Type of sampling ('seed' or 'active_learning')
        sampling_config: Optional JSONB configuration for the sampling strategy
        sample_count: Number of samples selected in this round
        status: Lifecycle status (pending/running/completed/failed)
        job_id: Optional Celery task/job ID
        error_message: Error details if status is failed
        completed_at: Timestamp when the round completed or failed
    """

    __tablename__ = "sampling_rounds"

    custom_model_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("custom_models.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning CustomModel ID",
    )
    round_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Sequential round number (0 for seed round)",
    )
    round_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Type of sampling: seed or active_learning",
    )
    sampling_config: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Optional JSONB configuration for the sampling strategy",
    )
    sample_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        doc="Number of samples selected in this round",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        doc="Lifecycle status: pending/running/completed/failed",
    )
    job_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Optional Celery task/job ID",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error details if status is failed",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when the round completed or failed",
    )

    # Relationships
    custom_model: Mapped[CustomModel] = relationship(
        "CustomModel",
        back_populates="sampling_rounds",
        lazy="raise",
    )
    items: Mapped[list[SamplingRoundItem]] = relationship(
        "SamplingRoundItem",
        back_populates="sampling_round",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_sampling_rounds_custom_model_id", "custom_model_id"),
        Index("ix_sampling_rounds_status", "status"),
        Index("ix_sampling_rounds_round_type", "round_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<SamplingRound(id={self.id}, custom_model_id={self.custom_model_id}, "
            f"round_number={self.round_number}, round_type={self.round_type!r}, status={self.status!r})>"
        )


class SamplingRoundItem(UUIDMixin, TimestampMixin, Base):
    """A single sample selected as part of a SamplingRound.

    Links a specific embedding to an annotation and records metadata
    about why it was selected (sample type, similarity, decision distance).

    Attributes:
        id: Unique identifier (UUID)
        sampling_round_id: Foreign key to the owning SamplingRound
        embedding_id: Foreign key to the selected Embedding
        sample_type: Category of sample (easy_positive/boundary/others/active_learning)
        similarity: Optional cosine or dot-product similarity score
        decision_distance: Optional distance to SVM decision boundary
        annotation_id: Foreign key to the associated Annotation
    """

    __tablename__ = "sampling_round_items"

    sampling_round_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sampling_rounds.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning SamplingRound ID",
    )
    embedding_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("embeddings.id", ondelete="CASCADE"),
        nullable=False,
        doc="Selected Embedding ID",
    )
    sample_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc="Category: easy_positive/boundary/others/active_learning",
    )
    similarity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Cosine or dot-product similarity score",
    )
    decision_distance: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Distance to SVM decision boundary",
    )
    annotation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Associated Annotation ID",
    )

    # Relationships
    sampling_round: Mapped[SamplingRound] = relationship(
        "SamplingRound",
        back_populates="items",
        lazy="raise",
    )
    annotation: Mapped[Annotation] = relationship(
        "Annotation",
        lazy="raise",
    )
    embedding: Mapped[Embedding] = relationship(
        "Embedding",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_sampling_round_items_sampling_round_id", "sampling_round_id"),
        Index("ix_sampling_round_items_embedding_id", "embedding_id"),
        Index("ix_sampling_round_items_annotation_id", "annotation_id"),
        Index("ix_sampling_round_items_sample_type", "sample_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<SamplingRoundItem(id={self.id}, sampling_round_id={self.sampling_round_id}, "
            f"sample_type={self.sample_type!r})>"
        )


class AuditSetItem(UUIDMixin, Base):
    """A single embedding selected for human audit of a trained CustomModel.

    Created by the ``generate_audit_set`` Celery task. Each item links a
    specific embedding to the associated Annotation (source='audit_set') and
    records the classifier's predicted probability so that auditors can
    prioritise uncertain or high-confidence examples.

    Attributes:
        id: Unique identifier (UUID)
        custom_model_id: Foreign key to the owning CustomModel
        embedding_id: Foreign key to the selected Embedding (unique per model)
        recording_id: Denormalized recording FK for efficient filtering
        predicted_proba: Classifier probability for the positive class (0.0–1.0)
        annotation_id: Foreign key to the Annotation created for this audit item
        created_at: Timestamp when the item was created
    """

    __tablename__ = "audit_set_items"

    custom_model_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("custom_models.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning CustomModel ID",
    )
    embedding_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("embeddings.id", ondelete="CASCADE"),
        nullable=False,
        doc="Selected Embedding ID (unique per model)",
    )
    recording_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
        doc="Denormalized source Recording ID",
    )
    predicted_proba: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        doc="Classifier probability for the positive class (0.0–1.0)",
    )
    annotation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("annotations.id", ondelete="CASCADE"),
        nullable=False,
        doc="Associated Annotation created for this audit item",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Timestamp when the item was created",
    )

    # Relationships
    custom_model: Mapped[CustomModel] = relationship(
        "CustomModel",
        back_populates="audit_set_items",
        lazy="raise",
    )
    embedding: Mapped[Embedding] = relationship(
        "Embedding",
        lazy="raise",
    )
    annotation: Mapped[Annotation] = relationship(
        "Annotation",
        lazy="raise",
    )
    recording: Mapped[Recording] = relationship(
        "Recording",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_audit_set_items_custom_model_id", "custom_model_id"),
        Index("ix_audit_set_items_embedding_id", "embedding_id"),
        Index("ix_audit_set_items_annotation_id", "annotation_id"),
        UniqueConstraint("custom_model_id", "embedding_id", name="uq_audit_set_model_embedding"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditSetItem(id={self.id}, custom_model_id={self.custom_model_id}, "
            f"embedding_id={self.embedding_id}, predicted_proba={self.predicted_proba})>"
        )
