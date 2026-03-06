"""Similarity search request and response schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


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
