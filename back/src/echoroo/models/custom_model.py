"""Custom Model model.

A Custom Model is a machine learning classifier trained within an ML
Project to distinguish target sounds from background noise or other
species. The model is trained on labeled examples collected during
search sessions.

Supported model types:
- Logistic Regression: Fast, interpretable baseline
- SVM Linear: Good for linearly separable embeddings
- MLP Small: Small neural network (1 hidden layer)
- MLP Medium: Medium neural network (2 hidden layers)
- Random Forest: Ensemble method, good for noisy labels

The training process uses embeddings from labeled search results as
features, with positive/negative labels as targets. Models are
evaluated using cross-validation to estimate generalization performance.
"""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import JSONB

from echoroo.models.base import Base
from echoroo.models.tag import Tag

if TYPE_CHECKING:
    from echoroo.models.inference_batch import InferenceBatch
    from echoroo.models.ml_project import MLProject
    from echoroo.models.user import User

__all__ = [
    "CustomModel",
    "CustomModelType",
    "CustomModelStatus",
]


class CustomModelType(str, enum.Enum):
    """Type of machine learning model."""

    LOGISTIC_REGRESSION = "logistic_regression"
    """Logistic regression classifier."""

    SVM_LINEAR = "svm_linear"
    """Support vector machine with linear kernel."""

    MLP_SMALL = "mlp_small"
    """Multi-layer perceptron with 1 hidden layer (256 units)."""

    MLP_MEDIUM = "mlp_medium"
    """Multi-layer perceptron with 2 hidden layers (256, 128 units)."""

    RANDOM_FOREST = "random_forest"
    """Random forest ensemble classifier."""


class CustomModelStatus(str, enum.Enum):
    """Status of the custom model."""

    DRAFT = "draft"
    """Model configuration saved but not trained."""

    TRAINING = "training"
    """Model is currently being trained."""

    TRAINED = "trained"
    """Model training completed successfully."""

    FAILED = "failed"
    """Model training failed with an error."""

    DEPLOYED = "deployed"
    """Model is deployed and ready for inference."""

    ARCHIVED = "archived"
    """Model is archived and no longer active."""


class CustomModel(Base):
    """Custom Model model.

    Represents a trained classifier for a specific species/sound
    within an ML project.
    """

    __tablename__ = "custom_model"

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the custom model."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the custom model."""

    # Required fields (no defaults) first
    name: orm.Mapped[str] = orm.mapped_column(nullable=False)
    """A descriptive name for this model."""

    ml_project_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("ml_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The ML project this model belongs to."""

    target_tag_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("tag.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The species/sound tag this model classifies."""

    model_type: orm.Mapped[CustomModelType] = orm.mapped_column(
        sa.Enum(
            CustomModelType,
            name="custom_model_type",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
    )
    """The type of machine learning model."""

    created_by_id: orm.Mapped[UUID] = orm.mapped_column(
        ForeignKey("user.id"),
        nullable=False,
    )
    """The user who created this model."""

    # Optional fields (with defaults) after
    description: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional description of the model and its purpose."""

    hyperparameters: orm.Mapped[dict | None] = orm.mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    """Model hyperparameters as JSON."""

    status: orm.Mapped[CustomModelStatus] = orm.mapped_column(
        sa.Enum(
            CustomModelStatus,
            name="custom_model_status",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
        default=CustomModelStatus.DRAFT,
        server_default=CustomModelStatus.DRAFT.value,
    )
    """Current status of the model."""

    training_session_ids: orm.Mapped[list | None] = orm.mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    """List of search session IDs used for training data."""

    # Training statistics
    training_samples: orm.Mapped[int | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Number of samples in the training set."""

    validation_samples: orm.Mapped[int | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Number of samples in the validation set."""

    # Evaluation metrics
    accuracy: orm.Mapped[float | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Model accuracy on validation set."""

    precision: orm.Mapped[float | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Model precision on validation set."""

    recall: orm.Mapped[float | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Model recall on validation set."""

    f1_score: orm.Mapped[float | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Model F1 score on validation set."""

    confusion_matrix: orm.Mapped[dict | None] = orm.mapped_column(
        JSONB,
        nullable=True,
        default=None,
    )
    """Confusion matrix as JSON (TP, TN, FP, FN counts)."""

    # Model artifact
    model_path: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Path to the serialized model file (relative to storage root)."""

    # Training timestamps
    training_started_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    """Timestamp when training started."""

    training_completed_on: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    """Timestamp when training completed."""

    # Error handling
    error_message: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Error message if training failed."""

    # Relationships
    ml_project: orm.Mapped["MLProject"] = orm.relationship(
        "MLProject",
        back_populates="custom_models",
        init=False,
        repr=False,
    )
    """The ML project this model belongs to."""

    target_tag: orm.Mapped[Tag] = orm.relationship(
        "Tag",
        lazy="joined",
        init=False,
        repr=False,
    )
    """The target species/sound tag."""

    created_by: orm.Mapped["User"] = orm.relationship(
        "User",
        foreign_keys=[created_by_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The user who created this model."""

    # Child relationships
    inference_batches: orm.Mapped[list["InferenceBatch"]] = orm.relationship(
        "InferenceBatch",
        back_populates="custom_model",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Inference batches using this model."""
