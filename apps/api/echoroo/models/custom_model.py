"""CustomModel for self-training SVM classifiers built from search session results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.project import Project
    from echoroo.models.tag import Tag
    from echoroo.models.user import User


class CustomModelStatus(StrEnum):
    """Lifecycle status of a custom ML classifier."""

    DRAFT = "draft"
    TRAINING = "training"
    TRAINED = "trained"
    DEPLOYED = "deployed"
    FAILED = "failed"
    ARCHIVED = "archived"


class CustomModel(UUIDMixin, TimestampMixin, Base):
    """User-trained SVM classifier built from confirmed/rejected search session results.

    Stores training configuration, hyperparameters discovered via cross-validation,
    evaluation metrics, and a reference to the serialized model artifact in S3.

    Attributes:
        id: Unique identifier (UUID)
        project_id: Foreign key to the owning project
        user_id: Optional foreign key to the user who created the model
        name: Human-readable model name
        description: Optional description of the model's purpose
        target_tag_id: Optional tag (species) this model classifies for
        model_type: Classifier architecture (default: self_training_svm)
        status: Lifecycle status (draft/training/trained/deployed/failed/archived)
        training_session_ids: List of SearchSession UUIDs used as training data
        hyperparameters: Best hyperparameters found by cross-validation (e.g. best_c)
        metrics: Evaluation metrics (accuracy, precision, recall, f1, auc_roc, etc.)
        training_stats: Counts of positive/negative/unlabeled samples and duration
        model_artifact_key: S3 object key for the serialized joblib model file
        embedding_model_name: Which embedding model's vectors to use (e.g. perch)
        error_message: Error details if status is FAILED
        started_at: Timestamp when training began
        completed_at: Timestamp when training completed or failed
    """

    __tablename__ = "custom_models"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning project ID",
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="User who created the model",
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="Human-readable model name",
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Optional description of the model's purpose",
    )
    target_tag_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="SET NULL"),
        nullable=True,
        doc="Target species/sound type tag this model classifies for",
    )
    model_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="self_training_svm",
        doc="Classifier architecture identifier",
    )
    status: Mapped[CustomModelStatus] = mapped_column(
        Enum(
            CustomModelStatus,
            name="custommodelstatus",
            create_type=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=CustomModelStatus.DRAFT,
        doc="Lifecycle status",
    )
    training_session_ids: Mapped[list[object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="List of SearchSession UUIDs used as training data",
    )
    hyperparameters: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Best hyperparameters found by cross-validation (e.g. best_c, cv_results)",
    )
    metrics: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Evaluation metrics (accuracy, precision, recall, f1, auc_roc, pr_auc, confusion_matrix)",
    )
    training_stats: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Training data statistics (positive_count, negative_count, unlabeled_count, training_duration)",
    )
    model_artifact_key: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="S3 object key for the serialized joblib model file",
    )
    embedding_model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="perch",
        doc="Which embedding model's vectors to use for training and inference",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc="Error details if status is FAILED",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when training began",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when training completed or failed",
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        lazy="raise",
    )
    user: Mapped[User | None] = relationship(
        "User",
        lazy="raise",
    )
    target_tag: Mapped[Tag | None] = relationship(
        "Tag",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_custom_models_project_id", "project_id"),
        Index("ix_custom_models_user_id", "user_id"),
        Index("ix_custom_models_status", "status"),
        Index("ix_custom_models_target_tag_id", "target_tag_id"),
        Index("ix_custom_models_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<CustomModel(id={self.id}, name={self.name!r}, status={self.status})>"
