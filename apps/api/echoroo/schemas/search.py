"""Similarity search request and response schemas."""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SimilaritySearchRequest(BaseModel):
    """Search for similar sounds using an existing embedding."""

    embedding_id: UUID = Field(..., description="Embedding ID to use as query vector")
    model_name: str = Field(default="perch", description="Which model's embeddings to search")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of results")
    min_similarity: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Minimum cosine similarity threshold"
    )
    dataset_id: UUID | None = Field(default=None, description="Optional dataset filter")


class SimilaritySearchByAudioRequest(BaseModel):
    """Search params for audio-based similarity search (used as form data companion)."""

    model_name: str = Field(default="perch", description="Model to use for embedding generation")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum number of results")
    min_similarity: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Minimum cosine similarity threshold"
    )
    dataset_id: UUID | None = Field(default=None, description="Optional dataset filter")


class SimilarityResult(BaseModel):
    """A single similarity search result."""

    embedding_id: UUID = Field(..., description="Embedding ID")
    recording_id: UUID = Field(..., description="Recording ID containing this embedding")
    recording_filename: str = Field(..., description="Original filename of the recording")
    dataset_id: UUID = Field(..., description="Dataset ID containing the recording")
    start_time: float = Field(..., description="Start time in seconds within the recording")
    end_time: float = Field(..., description="End time in seconds within the recording")
    similarity: float = Field(..., ge=0.0, le=1.0, description="Cosine similarity score (0.0-1.0)")


class SimilaritySearchResponse(BaseModel):
    """Response for similarity search."""

    results: list[SimilarityResult] = Field(..., description="Ordered list of similar segments")
    query_model: str = Field(..., description="Model name used for the search")
    total_results: int = Field(..., description="Total number of results returned")


class EmbeddingStatsResponse(BaseModel):
    """Statistics about stored embeddings."""

    total_count: int = Field(..., description="Total number of embeddings")
    by_model: dict[str, int] = Field(
        ..., description="Count per model name, e.g. {'birdnet': 1000, 'perch': 500}"
    )
    by_dataset: dict[str, int] = Field(
        ..., description="Count per dataset UUID string, e.g. {'uuid': 1500}"
    )


# ---------------------------------------------------------------------------
# Batch search schemas
# ---------------------------------------------------------------------------


class SourceConfig(BaseModel):
    """Configuration for a single reference sound source."""

    type: Literal["upload", "url"]
    file_key: str | None = Field(
        default=None,
        description="References multipart form field name (e.g. 'source_0') for upload type",
    )
    source_url: str | None = Field(
        default=None,
        description="URL of the reference sound for url type (Phase 2)",
    )
    start_time: float | None = Field(
        default=None,
        description="Clip start time in seconds (None = beginning of file)",
    )
    end_time: float | None = Field(
        default=None,
        description="Clip end time in seconds (None = end of file)",
    )
    s3_key: str | None = Field(
        default=None,
        description="Server-internal: S3 object key for persisted reference audio",
    )


class SpeciesSearchConfig(BaseModel):
    """Configuration for searching one species."""

    tag_id: str | None = Field(
        default=None,
        description="Existing tag UUID; None for a custom (ad-hoc) species",
    )
    scientific_name: str = Field(..., description="Scientific name of the species to search for")
    sources: list[SourceConfig] = Field(
        ...,
        description="Reference sound sources for this species (max 10)",
    )

    @field_validator("tag_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        """Convert empty string to None so callers don't need to distinguish."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class BatchSearchRequest(BaseModel):
    """Metadata for a batch search request sent as the 'metadata' form field."""

    species: list[SpeciesSearchConfig] = Field(
        ...,
        description="Species configurations to search (max 20)",
    )
    model_name: str = Field(default="perch", description="Model to use for embedding generation")
    min_similarity: float = Field(
        default=0.1, ge=0.0, le=1.0, description="Minimum cosine similarity threshold"
    )
    limit_per_species: int = Field(
        default=100, ge=1, le=500, description="Maximum results returned per species"
    )
    dataset_id: str | None = Field(default=None, description="Optional dataset UUID filter")
    source_session_id: str | None = Field(
        default=None,
        description="Re-run: copy reference audio sources from this session ID",
    )

    @field_validator("dataset_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        """Convert empty string to None so callers don't need to distinguish."""
        if isinstance(v, str) and v.strip() == "":
            return None
        return v


class SpeciesMatchResult(BaseModel):
    """Aggregated search results for a single species."""

    tag_id: str | None = Field(default=None, description="Tag UUID for this species")
    scientific_name: str = Field(..., description="Scientific name of the species")
    common_name: str | None = Field(default=None, description="Common name of the species")
    matches: list[SimilarityResult] = Field(
        ..., description="Matching audio segments ordered by descending similarity"
    )


class BatchSearchResponse(BaseModel):
    """Response for a batch species search."""

    results: dict[str, SpeciesMatchResult] = Field(
        ...,
        description=(
            "Search results keyed by tag_id (or auto-generated key for custom species)"
        ),
    )
    total_matches: int = Field(..., description="Total number of matches across all species")
    search_duration_ms: int = Field(
        ..., description="Wall-clock search duration in milliseconds"
    )


# ---------------------------------------------------------------------------
# Search session persistence schemas
# ---------------------------------------------------------------------------


class SearchSessionResponse(BaseModel):
    """Full search session detail including results."""

    model_config = ConfigDict(from_attributes=True)

    id: _uuid.UUID
    project_id: _uuid.UUID
    user_id: _uuid.UUID | None
    name: str | None
    status: str
    model_name: str
    parameters: dict[str, object] | None
    species_config: list[object] | None
    results: dict[str, object] | None  # BatchSearchResponse format
    result_count: int
    confirmed_count: int
    rejected_count: int
    celery_job_id: str | None
    reference_audio_keys: list[str] | None
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class SearchSessionListItem(BaseModel):
    """Session list item (no results, just counts)."""

    model_config = ConfigDict(from_attributes=True)

    id: _uuid.UUID
    name: str | None
    status: str
    model_name: str
    result_count: int
    confirmed_count: int
    rejected_count: int
    species_config: list[object] | None  # for showing species names in list
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class SearchSessionListResponse(BaseModel):
    """Paginated list of search sessions."""

    sessions: list[SearchSessionListItem]
    total: int


# ---------------------------------------------------------------------------
# Job response schemas (updated to include session_id)
# ---------------------------------------------------------------------------


class SearchJobAcceptedResponse(BaseModel):
    """Response returned immediately when a batch search job is queued."""

    job_id: str
    status: str
    session_id: _uuid.UUID | None = None


class SearchJobStatusResponse(BaseModel):
    """Response for async batch search job status."""

    job_id: str
    status: str  # "pending" | "processing" | "completed" | "failed"
    progress: dict[str, int] | None = None
    results: BatchSearchResponse | None = None
    error: str | None = None
    session_id: _uuid.UUID | None = None
