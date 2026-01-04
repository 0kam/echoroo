"""Schemas for foundation model metadata and runs."""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.datasets import Dataset
from echoroo.schemas.tags import Tag
from echoroo.schemas.users import SimpleUser

__all__ = [
    "DatasetFoundationModelSummary",
    "FoundationModel",
    "FoundationModelRun",
    "FoundationModelRunCreate",
    "FoundationModelRunProgress",
    "FoundationModelRunSpecies",
    "FoundationModelRunStatus",
]


class FoundationModel(BaseSchema):
    """Available foundation model metadata."""

    id: int = Field(..., exclude=True)
    uuid: UUID
    slug: str
    display_name: str
    provider: str
    version: str
    description: str | None = None
    default_confidence_threshold: float = 0.1
    is_active: bool = True


class FoundationModelRunStatus(str, Enum):
    """Run status enumeration."""

    QUEUED = "queued"
    RUNNING = "running"
    POST_PROCESSING = "post_processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FoundationModelRunSpecies(BaseSchema):
    """Aggregated species summary for a run."""

    id: int = Field(..., exclude=True)
    foundation_model_run_id: int = Field(..., exclude=True)
    gbif_taxon_id: str | None = None
    annotation_tag_id: int | None = Field(default=None, exclude=True)
    tag: Tag | None = None
    scientific_name: str
    common_name_ja: str | None = None
    detection_count: int = 0
    avg_confidence: float = 0.0


class FoundationModelRun(BaseSchema):
    """Run record schema."""

    id: int = Field(..., exclude=True)
    uuid: UUID
    foundation_model_id: int = Field(..., exclude=True)
    dataset_id: int = Field(..., exclude=True)
    requested_by_id: UUID | None = Field(default=None, exclude=True)
    foundation_model: FoundationModel | None = None
    dataset: Dataset | None = None
    requested_by: SimpleUser | None = None
    status: FoundationModelRunStatus = FoundationModelRunStatus.QUEUED
    confidence_threshold: float = 0.1
    scope: dict[str, Any] | None = None
    progress: float = 0.0
    total_recordings: int = 0
    processed_recordings: int = 0
    total_clips: int = 0
    total_detections: int = 0
    classification_csv_path: str | None = None
    embedding_store_key: str | None = None
    summary: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_on: datetime.datetime | None = None
    completed_on: datetime.datetime | None = None
    species: list[FoundationModelRunSpecies] | None = None


class DatasetFoundationModelSummary(BaseModel):
    """Summary of latest runs per model for a dataset."""

    foundation_model: FoundationModel
    latest_run: FoundationModelRun | None = None
    last_completed_run: FoundationModelRun | None = None


class FoundationModelRunCreate(BaseModel):
    """Payload to create a new run."""

    dataset_uuid: UUID
    foundation_model_slug: str
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    scope: dict[str, Any] | None = None
    locale: str = Field(
        default="ja",
        max_length=16,
        description="Locale for species common names (e.g., 'en_us', 'ja')",
    )
    """Locale for species common names. Defaults to Japanese ('ja')."""


class FoundationModelRunProgress(BaseModel):
    """Schema for tracking foundation model run progress."""

    status: FoundationModelRunStatus
    """Current run status."""

    progress: float = 0.0
    """Progress percentage (0.0 to 1.0)."""

    total_recordings: int = 0
    """Total recordings to process."""

    processed_recordings: int = 0
    """Recordings processed so far."""

    total_clips: int = 0
    """Total clips analyzed."""

    total_detections: int = 0
    """Detections found so far."""

    recordings_per_second: float | None = None
    """Processing speed."""

    estimated_time_remaining_seconds: float | None = None
    """Estimated time remaining."""

    message: str | None = None
    """Human-readable status message."""
