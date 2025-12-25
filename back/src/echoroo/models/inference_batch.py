"""Inference Batch and Inference Prediction models.

An Inference Batch represents a batch inference operation where a
trained custom model is applied to a set of audio clips to generate
predictions. This enables scaling up the detection of target sounds
across large datasets.

The inference process:
1. Select clips to process (optionally filtered by criteria)
2. Load the trained model and clip embeddings
3. Generate predictions with confidence scores
4. Store results for review and potential annotation export

Inference Predictions are individual model outputs for each clip,
including the confidence score and a review status for quality control.
"""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.clip import Clip
    from echoroo.models.custom_model import CustomModel
    from echoroo.models.ml_project import MLProject
    from echoroo.models.user import User

__all__ = [
    "InferenceBatch",
    "InferenceBatchStatus",
    "InferencePrediction",
    "InferencePredictionReviewStatus",
]


class InferenceBatchStatus(str, enum.Enum):
    """Status of an inference batch."""

    PENDING = "pending"
    """Batch is queued and waiting to start."""

    RUNNING = "running"
    """Batch is currently processing."""

    COMPLETED = "completed"
    """Batch completed successfully."""

    FAILED = "failed"
    """Batch failed with an error."""

    CANCELLED = "cancelled"
    """Batch was cancelled by user."""


class InferencePredictionReviewStatus(str, enum.Enum):
    """Review status for inference predictions."""

    UNREVIEWED = "unreviewed"
    """Prediction has not been reviewed."""

    CONFIRMED = "confirmed"
    """Prediction confirmed as correct."""

    REJECTED = "rejected"
    """Prediction rejected as incorrect."""

    UNCERTAIN = "uncertain"
    """Prediction is ambiguous or uncertain."""


class InferenceBatch(Base):
    """Inference Batch model.

    Represents a batch inference operation applying a trained model
    to a set of audio clips.
    """

    __tablename__ = "inference_batch"

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the inference batch."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the inference batch."""

    # Required fields (no defaults) first
    name: orm.Mapped[str] = orm.mapped_column(nullable=False)
    """A descriptive name for this inference batch."""

    ml_project_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("ml_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The ML project this inference batch belongs to."""

    custom_model_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("custom_model.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The custom model used for inference."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        ForeignKey("user.id"),
        nullable=False,
    )
    """The user who created this inference batch."""

    # Optional fields (with defaults) after
    description: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional description of the inference batch."""

    filter_config: orm.Mapped[dict | None] = orm.mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    """Optional JSON filter configuration for selecting clips."""

    confidence_threshold: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
        default=0.5,
    )
    """Minimum confidence for positive predictions (0.0 to 1.0)."""

    batch_size: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=1000,
    )
    """Number of clips to process per batch iteration."""

    status: orm.Mapped[InferenceBatchStatus] = orm.mapped_column(
        sa.Enum(
            InferenceBatchStatus,
            name="inference_batch_status",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
        default=InferenceBatchStatus.PENDING,
        server_default=InferenceBatchStatus.PENDING.value,
    )
    """Current status of the inference batch."""

    progress: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
        default=0.0,
    )
    """Progress from 0.0 to 1.0."""

    # Processing statistics
    total_items: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Total number of clips to process."""

    processed_items: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Number of clips processed so far."""

    positive_predictions: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Number of clips predicted as positive."""

    # Timestamps
    started_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    """Timestamp when processing started."""

    completed_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    """Timestamp when processing completed."""

    # Error handling
    error_message: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Error message if processing failed."""

    # Relationships
    ml_project: orm.Mapped["MLProject"] = orm.relationship(
        "MLProject",
        back_populates="inference_batches",
        init=False,
        repr=False,
    )
    """The ML project this batch belongs to."""

    custom_model: orm.Mapped["CustomModel"] = orm.relationship(
        "CustomModel",
        back_populates="inference_batches",
        init=False,
        repr=False,
    )
    """The custom model used for inference."""

    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The user who created this batch."""

    # Child relationships
    predictions: orm.Mapped[list["InferencePrediction"]] = orm.relationship(
        "InferencePrediction",
        back_populates="inference_batch",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Predictions generated by this batch."""


class InferencePrediction(Base):
    """Inference Prediction model.

    Represents a single model prediction for an audio clip.
    """

    __tablename__ = "inference_prediction"
    __table_args__ = (
        UniqueConstraint(
            "inference_batch_id",
            "clip_id",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the inference prediction."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the inference prediction."""

    # Required fields (no defaults) first
    inference_batch_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("inference_batch.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The inference batch this prediction belongs to."""

    clip_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("clip.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The clip this prediction is for."""

    confidence: orm.Mapped[float] = orm.mapped_column(
        nullable=False,
    )
    """Model confidence score (0.0 to 1.0)."""

    predicted_positive: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
    )
    """Whether the model predicted positive for target sound."""

    # Optional fields (with defaults) after
    review_status: orm.Mapped[InferencePredictionReviewStatus] = orm.mapped_column(
        sa.Enum(
            InferencePredictionReviewStatus,
            name="inference_prediction_review_status",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
        default=InferencePredictionReviewStatus.UNREVIEWED,
        server_default=InferencePredictionReviewStatus.UNREVIEWED.value,
    )
    """Review status for quality control."""

    reviewed_by_id: orm.Mapped[UUID | None] = orm.mapped_column(
        ForeignKey("user.id"),
        nullable=True,
        default=None,
    )
    """The user who reviewed this prediction."""

    reviewed_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    """Timestamp when this prediction was reviewed."""

    notes: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional notes about this prediction."""

    # Relationships
    inference_batch: orm.Mapped[InferenceBatch] = orm.relationship(
        "InferenceBatch",
        back_populates="predictions",
        init=False,
        repr=False,
    )
    """The inference batch this prediction belongs to."""

    clip: orm.Mapped["Clip"] = orm.relationship(
        "Clip",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The clip this prediction is for."""

    reviewed_by: orm.Mapped["User | None"] = orm.relationship(
        "User",
        foreign_keys=[reviewed_by_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The user who reviewed this prediction."""
