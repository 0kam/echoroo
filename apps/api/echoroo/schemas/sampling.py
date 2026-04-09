"""Request and response schemas for sampling rounds in the model training overhaul."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SamplingRoundItemResponse(BaseModel):
    """Response schema for a single item within a sampling round."""

    id: UUID
    embedding_id: UUID
    sample_type: str  # 'easy_positive' | 'boundary' | 'others' | 'active_learning'
    similarity: float | None
    decision_distance: float | None
    annotation_id: UUID
    # Annotation status included for convenience
    review_status: str | None = None  # 'unreviewed' | 'confirmed' | 'rejected'
    # Embedding metadata for display
    recording_id: UUID | None = None
    start_time: float | None = None
    end_time: float | None = None

    model_config = ConfigDict(from_attributes=True)


class SamplingRoundResponse(BaseModel):
    """Full response schema for a sampling round, including its items."""

    id: UUID
    custom_model_id: UUID
    round_number: int
    round_type: str  # 'seed' | 'active_learning'
    sampling_config: dict[str, object] | None
    sample_count: int
    status: str  # 'pending' | 'running' | 'completed' | 'failed'
    job_id: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    items: list[SamplingRoundItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class SamplingRoundListResponse(BaseModel):
    """Paginated list of sampling rounds for a custom model."""

    rounds: list[SamplingRoundResponse]
    total: int


class AuditSetItemResponse(BaseModel):
    """Response schema for a single audit set item."""

    id: UUID
    embedding_id: UUID
    recording_id: UUID
    predicted_proba: float | None
    annotation_id: UUID
    # Annotation status included for convenience
    review_status: str | None = None  # 'unreviewed' | 'confirmed' | 'rejected'
    # Embedding metadata for display
    start_time: float | None = None
    end_time: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditSetListResponse(BaseModel):
    """List of audit set items for a custom model."""

    items: list[AuditSetItemResponse]
    total: int


class AuditSetGenerateResponse(BaseModel):
    """Response returned immediately after dispatching audit set generation."""

    model_id: UUID
    status: str = "dispatched"


class AuditSetEvaluateResponse(BaseModel):
    """Response schema for the audit set evaluation endpoint."""

    model_id: UUID
    audit_metrics: dict[str, object]


class SeedSamplingRequest(BaseModel):
    """Optional overrides for seed sampling configuration.

    Controls how many samples of each type are selected during the
    initial seed sampling round before active learning begins.
    """

    easy_positive_k: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Top-K nearest neighbours to the prototype to include as easy positives",
    )
    boundary_n: int = Field(
        default=200,
        ge=10,
        le=1000,
        description="Candidate pool size for boundary sampling",
    )
    boundary_m: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of boundary samples to select from the candidate pool",
    )
    others_p: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Number of random 'other' (negative) samples to include",
    )
