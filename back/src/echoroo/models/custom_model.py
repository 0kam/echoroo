"""Custom Model model.

A Custom Model is a machine learning classifier trained to distinguish
target sounds from background noise or other species. The model can be
trained on labeled examples from multiple sources:

1. Search Sessions (ML Project workflow) - traditional labeling flow
2. Sound Search results - saved as annotations
3. Annotation Projects - existing labeled data

Supported model types:
- Logistic Regression: Fast, interpretable baseline
- SVM Linear: Good for linearly separable embeddings
- MLP Small: Small neural network (1 hidden layer)
- MLP Medium: Medium neural network (2 hidden layers)
- Random Forest: Ensemble method, good for noisy labels

The training process uses embeddings from labeled data as features,
with positive/negative labels as targets. Models are evaluated using
cross-validation to estimate generalization performance.
"""

from __future__ import annotations

import datetime
import enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from echoroo.models.base import Base
from echoroo.models.tag import Tag

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset
    from echoroo.models.foundation_model import FoundationModelRun
    from echoroo.models.inference_batch import InferenceBatch
    from echoroo.models.ml_project import MLProject
    from echoroo.models.project import Project
    from echoroo.models.search_session import SearchSession
    from echoroo.models.user import User

__all__ = [
    "CustomModel",
    "CustomModelDatasetScope",
    "CustomModelTrainingSource",
    "CustomModelType",
    "CustomModelStatus",
    "TrainingDataSource",
]


class CustomModelType(str, enum.Enum):
    """Type of machine learning model."""

    SELF_TRAINING_SVM = "self_training_svm"
    """Self-training classifier with linear SVM base estimator."""


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


class TrainingDataSource(str, enum.Enum):
    """Source type for training data."""

    SEARCH_SESSION = "search_session"
    """Training data from ML Project search session labeled results."""

    SOUND_SEARCH = "sound_search"
    """Training data from Sound Search results saved as annotations."""

    ANNOTATION_PROJECT = "annotation_project"
    """Training data from existing annotation project."""


class CustomModel(Base):
    """Custom Model model.

    Represents a trained classifier for a specific species/sound.
    Can be associated with an ML Project (legacy) or operate independently.
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

    # Project association - required for standalone models
    project_id: orm.Mapped[str | None] = orm.mapped_column(
        ForeignKey("project.project_id", ondelete="CASCADE"),
        nullable=True,
        default=None,
        index=True,
    )
    """The project this model belongs to (for access control). Required for standalone models."""

    # ML Project association - optional (for backward compatibility)
    ml_project_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("ml_project.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    """The ML project this model belongs to (legacy, optional)."""

    source_search_session_id: orm.Mapped[int | None] = orm.mapped_column(
        ForeignKey("search_session.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    """The search session from which this model was trained (if any)."""

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
    """List of search session IDs used for training data (legacy)."""

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
    project: orm.Mapped["Project | None"] = orm.relationship(
        "Project",
        foreign_keys=[project_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The project this model belongs to."""

    ml_project: orm.Mapped["MLProject | None"] = orm.relationship(
        "MLProject",
        back_populates="custom_models",
        init=False,
        repr=False,
    )
    """The ML project this model belongs to (legacy)."""

    source_search_session: orm.Mapped["SearchSession | None"] = orm.relationship(
        "SearchSession",
        foreign_keys=[source_search_session_id],
        viewonly=True,
        init=False,
        repr=False,
    )
    """The search session from which this model was trained."""

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

    dataset_scopes: orm.Mapped[list["CustomModelDatasetScope"]] = orm.relationship(
        "CustomModelDatasetScope",
        back_populates="custom_model",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Dataset scopes for training data."""

    training_sources: orm.Mapped[list["CustomModelTrainingSource"]] = orm.relationship(
        "CustomModelTrainingSource",
        back_populates="custom_model",
        default_factory=list,
        cascade="all, delete-orphan",
        repr=False,
        init=False,
    )
    """Training data sources."""


class CustomModelDatasetScope(Base):
    """Custom Model Dataset Scope model.

    Defines which datasets to include for training and which foundation
    model run provides the embeddings for feature extraction.
    """

    __tablename__ = "custom_model_dataset_scope"
    __table_args__ = (
        UniqueConstraint(
            "custom_model_id",
            "dataset_id",
            name="uq_custom_model_dataset_scope_model_dataset",
        ),
        Index(
            "ix_custom_model_dataset_scope_model_id",
            "custom_model_id",
        ),
    )

    # Primary key
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the dataset scope."""

    # Required fields
    custom_model_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("custom_model.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The custom model this scope belongs to."""

    dataset_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("dataset.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The dataset to include for training."""

    foundation_model_run_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("foundation_model_run.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """The foundation model run that provides embeddings for this dataset."""

    # Relationships
    custom_model: orm.Mapped["CustomModel"] = orm.relationship(
        "CustomModel",
        back_populates="dataset_scopes",
        init=False,
        repr=False,
    )
    """The custom model this scope belongs to."""

    dataset: orm.Mapped["Dataset"] = orm.relationship(
        "Dataset",
        foreign_keys=[dataset_id],
        viewonly=True,
        init=False,
        repr=False,
        lazy="joined",
    )
    """The dataset to include."""

    foundation_model_run: orm.Mapped["FoundationModelRun"] = orm.relationship(
        "FoundationModelRun",
        foreign_keys=[foundation_model_run_id],
        viewonly=True,
        init=False,
        repr=False,
        lazy="joined",
    )
    """The foundation model run providing embeddings."""


class CustomModelTrainingSource(Base):
    """Custom Model Training Source model.

    Defines the sources of training data for a custom model. Each source
    can be a search session (legacy), sound search results, or an
    annotation project. Sources can provide either positive or negative
    examples, and can optionally filter by specific tags.
    """

    __tablename__ = "custom_model_training_source"
    __table_args__ = (
        UniqueConstraint(
            "custom_model_id",
            "source_type",
            "source_uuid",
            name="uq_custom_model_training_source_model_type_uuid",
        ),
        Index(
            "ix_custom_model_training_source_model_id",
            "custom_model_id",
        ),
    )

    # Primary key
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """The database id of the training source."""

    uuid: orm.Mapped[UUID] = orm.mapped_column(
        default_factory=uuid4,
        kw_only=True,
        unique=True,
    )
    """The UUID of the training source."""

    # Required fields
    custom_model_id: orm.Mapped[int] = orm.mapped_column(
        ForeignKey("custom_model.id", ondelete="CASCADE"),
        nullable=False,
    )
    """The custom model this source belongs to."""

    source_type: orm.Mapped[TrainingDataSource] = orm.mapped_column(
        sa.Enum(
            TrainingDataSource,
            name="training_data_source",
            values_callable=lambda x: [e.value for e in x],
            create_type=False,
        ),
        nullable=False,
    )
    """The type of data source."""

    source_uuid: orm.Mapped[UUID] = orm.mapped_column(
        nullable=False,
    )
    """The UUID of the source (SearchSession, SoundSearch, or AnnotationProject)."""

    is_positive: orm.Mapped[bool] = orm.mapped_column(
        nullable=False,
        default=True,
    )
    """Whether this source provides positive (True) or negative (False) examples."""

    # Optional fields
    tag_uuid: orm.Mapped[UUID | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional tag UUID to filter data by a specific tag."""

    description: orm.Mapped[str | None] = orm.mapped_column(
        nullable=True,
        default=None,
    )
    """Optional description of this training source."""

    # Statistics (populated during training)
    sample_count: orm.Mapped[int] = orm.mapped_column(
        nullable=False,
        default=0,
    )
    """Number of samples from this source used in training."""

    # Relationships
    custom_model: orm.Mapped["CustomModel"] = orm.relationship(
        "CustomModel",
        back_populates="training_sources",
        init=False,
        repr=False,
    )
    """The custom model this source belongs to."""
