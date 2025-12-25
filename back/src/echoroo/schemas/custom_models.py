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
    "CustomModelTrainingConfig",
    "TrainingProgress",
    "CustomModelMetrics",
]


class CustomModelType(str, Enum):
    """Type of custom model architecture."""

    LINEAR_CLASSIFIER = "linear_classifier"
    """Simple linear classifier on top of embeddings."""

    MLP = "mlp"
    """Multi-layer perceptron classifier."""

    RANDOM_FOREST = "random_forest"
    """Random forest classifier on embeddings."""

    SVM = "svm"
    """Support vector machine classifier."""

    GRADIENT_BOOSTING = "gradient_boosting"
    """Gradient boosting classifier (XGBoost/LightGBM)."""


class CustomModelStatus(str, Enum):
    """Status of a custom model."""

    PENDING = "pending"
    """Model training has been queued."""

    PREPARING = "preparing"
    """Preparing training data."""

    TRAINING = "training"
    """Model is currently being trained."""

    VALIDATING = "validating"
    """Model is being validated on held-out data."""

    COMPLETED = "completed"
    """Training completed successfully."""

    FAILED = "failed"
    """Training failed due to an error."""

    CANCELLED = "cancelled"
    """Training was cancelled by the user."""


class CustomModelTrainingConfig(BaseModel):
    """Configuration for model training."""

    model_config = {"protected_namespaces": ()}

    model_type: CustomModelType = CustomModelType.MLP
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
        ...,
        min_length=1,
        description="Search sessions to use for training data",
    )
    """Search sessions whose labeled results will be used for training."""

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

    ml_project_id: int = Field(..., exclude=True)
    """ML project that owns this model."""

    ml_project_uuid: UUID
    """UUID of the owning ML project."""

    tag_id: int = Field(..., exclude=True)
    """Target tag identifier."""

    tag: Tag
    """Tag that this model is trained to detect."""

    model_type: CustomModelType
    """Type of model architecture."""

    status: CustomModelStatus = CustomModelStatus.PENDING
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
