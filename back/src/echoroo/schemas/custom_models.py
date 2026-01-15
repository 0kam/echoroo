"""Schemas for Custom Models."""

import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.tags import Tag

__all__ = [
    "CustomModelType",
    "CustomModelStatus",
    "CustomModel",
    "CustomModelCreate",
    "CustomModelCreateStandalone",
    "CustomModelTrainingConfig",
    "TrainingProgress",
    "CustomModelMetrics",
    "DatasetScopeCreate",
    "DatasetScope",
    "TrainingSourceCreate",
    "TrainingSource",
    "TrainingDataSource",
]


class CustomModelType(str, Enum):
    """Type of custom model architecture."""

    SVM = "svm"
    """Support vector machine classifier."""


class CustomModelStatus(str, Enum):
    """Status of a custom model."""

    DRAFT = "draft"
    """Model configuration saved but not trained."""

    TRAINING = "training"
    """Model is currently being trained."""

    TRAINED = "trained"
    """Model training completed successfully."""

    FAILED = "failed"
    """Training failed due to an error."""

    DEPLOYED = "deployed"
    """Model is deployed and ready for inference."""

    ARCHIVED = "archived"
    """Model is archived and no longer active."""


class CustomModelTrainingConfig(BaseModel):
    """Configuration for model training."""

    model_config = {"protected_namespaces": ()}

    model_type: CustomModelType = CustomModelType.SVM
    """Type of model architecture to use."""

    train_split: float = Field(
        default=0.8,
        ge=0.5,
        le=0.95,
        description="Fraction of data for training",
    )
    """Fraction of labeled data to use for training."""

    validation_split: float = Field(
        default=0.1,
        ge=0.05,
        le=0.3,
        description="Fraction of data for validation",
    )
    """Fraction of labeled data to use for validation."""

    learning_rate: float = Field(
        default=0.001,
        ge=0.00001,
        le=0.1,
        description="Learning rate for optimization",
    )
    """Learning rate for gradient-based optimization."""

    batch_size: int = Field(
        default=32,
        ge=8,
        le=512,
        description="Batch size for training",
    )
    """Batch size for training iterations."""

    max_epochs: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum training epochs",
    )
    """Maximum number of training epochs."""

    early_stopping_patience: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Early stopping patience",
    )
    """Number of epochs without improvement before stopping."""

    hidden_layers: list[int] = Field(
        default_factory=lambda: [256, 128],
        description="Hidden layer sizes for MLP",
    )
    """Hidden layer dimensions for MLP architecture."""

    dropout_rate: float = Field(
        default=0.3,
        ge=0.0,
        le=0.8,
        description="Dropout rate for regularization",
    )
    """Dropout rate for regularization."""

    class_weight_balanced: bool = True
    """Whether to use balanced class weights."""

    random_seed: int | None = Field(
        default=42,
        description="Random seed for reproducibility",
    )
    """Random seed for reproducible training."""


class CustomModelCreate(BaseModel):
    """Schema for creating a custom model."""

    name: str = Field(..., min_length=1, max_length=255)
    """Human-readable name for the model."""

    description: str | None = Field(default=None, max_length=2000)
    """Description of the model purpose and training data."""

    tag_id: int = Field(..., description="Target tag for classification")
    """Tag that this model is trained to detect."""

    search_session_ids: list[int] = Field(
        default_factory=list,
        description="Search sessions to use for training data",
    )
    """Search sessions whose labeled results will be used for training."""

    annotation_project_uuids: list[UUID] = Field(
        default_factory=list,
        description="Annotation projects to use for training data",
    )
    """Annotation projects whose labeled annotations will be used for training."""

    training_config: CustomModelTrainingConfig = Field(
        default_factory=CustomModelTrainingConfig,
    )
    """Training configuration and hyperparameters."""


class CustomModelMetrics(BaseModel):
    """Performance metrics for a custom model."""

    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    """Overall accuracy on validation set."""

    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    """Precision score on validation set."""

    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    """Recall score on validation set."""

    f1_score: float | None = Field(default=None, ge=0.0, le=1.0)
    """F1 score on validation set."""

    roc_auc: float | None = Field(default=None, ge=0.0, le=1.0)
    """Area under ROC curve."""

    pr_auc: float | None = Field(default=None, ge=0.0, le=1.0)
    """Area under precision-recall curve."""

    confusion_matrix: list[list[int]] | None = None
    """Confusion matrix [[TN, FP], [FN, TP]]."""

    training_samples: int = 0
    """Number of samples used for training."""

    validation_samples: int = 0
    """Number of samples used for validation."""

    positive_samples: int = 0
    """Number of positive samples in training data."""

    negative_samples: int = 0
    """Number of negative samples in training data."""


class CustomModel(BaseSchema):
    """Schema for a custom model returned to the user."""

    model_config = {"protected_namespaces": ()}

    uuid: UUID
    """UUID of the custom model."""

    id: int = Field(..., exclude=True)
    """Database ID of the custom model."""

    name: str
    """Human-readable name for the model."""

    description: str | None = None
    """Description of the model purpose and training data."""

    ml_project_id: int | None = Field(None, exclude=True)
    """ML project that owns this model."""

    ml_project_uuid: UUID | None = None
    """UUID of the owning ML project."""

    tag_id: int | None = None
    """Target tag identifier."""

    tag: Tag | None = None
    """Tag that this model is trained to detect."""

    model_type: CustomModelType
    """Type of model architecture."""

    status: CustomModelStatus = CustomModelStatus.DRAFT
    """Current training status."""

    training_config: CustomModelTrainingConfig
    """Training configuration used."""

    metrics: CustomModelMetrics | None = None
    """Performance metrics after training."""

    model_path: str | None = None
    """Path to the saved model file."""

    training_started_at: datetime.datetime | None = None
    """Timestamp when training started."""

    training_completed_at: datetime.datetime | None = None
    """Timestamp when training completed."""

    training_duration_seconds: float | None = None
    """Total training duration in seconds."""

    error_message: str | None = None
    """Error message if training failed."""

    version: int = 1
    """Model version number."""

    is_active: bool = True
    """Whether the model is currently active for inference."""

    created_by_id: UUID
    """User who created the model."""

    # Source information
    source_search_session_uuid: UUID | None = None
    """UUID of the search session from which this model was trained."""

    source_search_session_name: str | None = None
    """Name of the source search session."""

    annotation_project_uuid: UUID | None = None
    """UUID of the annotation project created from the search session."""

    annotation_project_name: str | None = None
    """Name of the annotation project."""


class TrainingProgress(BaseModel):
    """Schema for tracking training progress."""

    status: CustomModelStatus
    """Current training status."""

    current_epoch: int = 0
    """Current training epoch."""

    total_epochs: int = 0
    """Total planned epochs."""

    current_step: int = 0
    """Current training step within the epoch."""

    total_steps: int = 0
    """Total steps per epoch."""

    train_loss: float | None = None
    """Current training loss."""

    val_loss: float | None = None
    """Current validation loss."""

    train_accuracy: float | None = None
    """Current training accuracy."""

    val_accuracy: float | None = None
    """Current validation accuracy."""

    best_val_loss: float | None = None
    """Best validation loss achieved."""

    epochs_without_improvement: int = 0
    """Number of epochs without improvement."""

    estimated_time_remaining_seconds: float | None = None
    """Estimated time remaining for training."""

    message: str | None = None
    """Human-readable status message."""


class TrainingDataSource(str, Enum):
    """Source type for training data."""

    SOUND_SEARCH = "sound_search"
    """Training data from Sound Search results saved as annotations."""

    ANNOTATION_PROJECT = "annotation_project"
    """Training data from existing annotation project."""


class DatasetScopeCreate(BaseModel):
    """Schema for creating a dataset scope for custom model training."""

    dataset_uuid: UUID = Field(
        ...,
        description="UUID of the dataset to include for training",
    )
    """The dataset to include for training."""

    foundation_model_run_uuid: UUID = Field(
        ...,
        description="UUID of the foundation model run providing embeddings",
    )
    """The foundation model run providing embeddings for this dataset."""


class DatasetScope(BaseModel):
    """Schema for a dataset scope returned to the user."""

    id: int = Field(..., exclude=True)
    """Database ID of the dataset scope."""

    dataset_id: int = Field(..., exclude=True)
    """Dataset identifier."""

    dataset_uuid: UUID
    """UUID of the dataset."""

    dataset_name: str
    """Name of the dataset."""

    foundation_model_run_id: int = Field(..., exclude=True)
    """Foundation model run identifier."""

    foundation_model_run_uuid: UUID
    """UUID of the foundation model run."""

    foundation_model_slug: str
    """Slug of the foundation model."""


class TrainingSourceCreate(BaseModel):
    """Schema for creating a training source for custom model training."""

    source_type: TrainingDataSource = Field(
        ...,
        description="Type of data source (sound_search or annotation_project)",
    )
    """The type of data source."""

    source_uuid: UUID = Field(
        ...,
        description="UUID of the source (SoundSearch or AnnotationProject)",
    )
    """The UUID of the source."""

    is_positive: bool = Field(
        default=True,
        description="Whether this source provides positive (True) or negative (False) examples",
    )
    """Whether this source provides positive or negative examples."""

    tag_uuid: UUID | None = Field(
        default=None,
        description="Optional tag UUID to filter data by a specific tag",
    )
    """Optional tag UUID to filter data."""


class TrainingSource(BaseModel):
    """Schema for a training source returned to the user."""

    uuid: UUID
    """UUID of the training source."""

    source_type: TrainingDataSource
    """Type of the data source."""

    source_uuid: UUID
    """UUID of the source."""

    source_name: str | None = None
    """Name of the source (if available)."""

    is_positive: bool
    """Whether this source provides positive examples."""

    tag_uuid: UUID | None = None
    """Optional tag UUID filter."""

    tag_key: str | None = None
    """Optional tag key filter."""

    tag_value: str | None = None
    """Optional tag value filter."""

    sample_count: int = 0
    """Number of samples from this source used in training."""


class CustomModelCreateStandalone(BaseModel):
    """Schema for creating a standalone custom model (not via ML Project)."""

    name: str = Field(..., min_length=1, max_length=255)
    """Human-readable name for the model."""

    description: str | None = Field(default=None, max_length=2000)
    """Description of the model purpose and training data."""

    project_uuid: str = Field(
        ...,
        description="Project UUID for access control",
    )
    """The project this model belongs to (for access control)."""

    target_tag_uuid: UUID = Field(
        ...,
        description="UUID of the target tag for classification",
    )
    """Tag that this model is trained to detect."""

    model_type: CustomModelType = Field(
        default=CustomModelType.SVM,
        description="Type of model architecture to use",
    )
    """Type of model architecture."""

    dataset_scopes: list[DatasetScopeCreate] = Field(
        ...,
        min_length=1,
        description="Dataset scopes defining which datasets to use",
    )
    """Dataset scopes for training data."""

    training_sources: list[TrainingSourceCreate] = Field(
        ...,
        min_length=1,
        description="Training data sources (at least one positive required)",
    )
    """Training data sources."""

    training_config: CustomModelTrainingConfig = Field(
        default_factory=CustomModelTrainingConfig,
    )
    """Training configuration and hyperparameters."""
