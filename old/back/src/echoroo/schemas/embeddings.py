"""Schemas for embedding storage and similarity search."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.clips import Clip
from echoroo.schemas.model_runs import ModelRun
from echoroo.schemas.recordings import Recording
from echoroo.schemas.sound_events import SoundEvent

__all__ = [
    "AdvancedSearchRequest",
    "AdvancedSearchResponse",
    "ClipEmbedding",
    "EmbeddingSearchRequest",
    "EmbeddingSearchResponse",
    "EmbeddingSearchResult",
    "RandomClipsRequest",
    "RandomClipsResponse",
    "SearchResultItem",
    "SoundEventEmbedding",
]


class ClipEmbedding(BaseSchema):
    """Clip embedding response."""

    model_config = ConfigDict(protected_namespaces=())

    uuid: UUID
    """The unique identifier of the clip embedding."""

    id: int = Field(..., exclude=True)
    """The database id of the clip embedding."""

    embedding: list[float]
    """The embedding vector."""

    clip: Clip
    """The clip this embedding belongs to."""

    model_run: ModelRun
    """The model run that generated this embedding."""


class SoundEventEmbedding(BaseSchema):
    """Sound event embedding response."""

    model_config = ConfigDict(protected_namespaces=())

    uuid: UUID
    """The unique identifier of the sound event embedding."""

    id: int = Field(..., exclude=True)
    """The database id of the sound event embedding."""

    embedding: list[float]
    """The embedding vector."""

    sound_event: SoundEvent
    """The sound event this embedding belongs to."""

    model_run: ModelRun
    """The model run that generated this embedding."""


class EmbeddingSearchRequest(BaseModel):
    """Request for similarity search."""

    model_config = ConfigDict(protected_namespaces=())

    embedding: list[float] | None = None
    """Raw embedding vector to search with (one of embedding, clip_uuid, or sound_event_uuid required)."""

    clip_uuid: UUID | None = None
    """UUID of a clip to use as the query (uses its embedding)."""

    sound_event_uuid: UUID | None = None
    """UUID of a sound event to use as the query (uses its embedding)."""

    model_name: str
    """Name of the model whose embeddings to search."""

    limit: int = Field(default=20, ge=1, le=100)
    """Maximum number of results to return."""

    min_similarity: float = Field(default=0.7, ge=0.0, le=1.0)
    """Minimum cosine similarity threshold for results."""


class EmbeddingSearchResult(BaseModel):
    """Single search result from similarity search."""

    model_config = ConfigDict(protected_namespaces=())

    clip: Clip | None = None
    """Matching clip (if searching clip embeddings)."""

    sound_event: SoundEvent | None = None
    """Matching sound event (if searching sound event embeddings)."""

    similarity: float = Field(ge=0.0, le=1.0)
    """Cosine similarity score between query and result."""

    model_run: ModelRun
    """The model run that generated the matched embedding."""


class EmbeddingSearchResponse(BaseModel):
    """Search response with multiple results."""

    results: list[EmbeddingSearchResult]
    """List of search results sorted by similarity (descending)."""

    query_embedding: list[float] | None = None
    """The embedding vector used for the query (if computed from clip/sound_event)."""


class AdvancedSearchRequest(BaseModel):
    """Advanced embedding search with filters."""

    model_config = ConfigDict(protected_namespaces=())

    embedding: list[float] | None = None
    """Raw embedding vector to search with."""

    clip_uuid: UUID | None = None
    """UUID of a clip to use as the query (uses its embedding)."""

    dataset_uuids: list[UUID] | None = None
    """Filter results to only include clips from these datasets."""

    recording_uuids: list[UUID] | None = None
    """Filter results to only include clips from these recordings."""

    model_name: str
    """Name of the model whose embeddings to search."""

    limit: int = Field(default=20, ge=1, le=100)
    """Maximum number of results to return."""

    min_similarity: float = Field(default=0.7, ge=0.0, le=1.0)
    """Minimum cosine similarity threshold for results."""


class SearchResultItem(BaseModel):
    """Single search result with full clip and recording info."""

    model_config = ConfigDict(protected_namespaces=())

    clip: Clip
    """The matching clip."""

    recording: Recording
    """The recording containing the clip."""

    similarity: float = Field(ge=0.0, le=1.0)
    """Cosine similarity score between query and result."""

    model_run: ModelRun
    """The model run that generated the matched embedding."""


class AdvancedSearchResponse(BaseModel):
    """Response from advanced search."""

    results: list[SearchResultItem]
    """List of search results sorted by similarity (descending)."""

    total_searched: int
    """Total number of embeddings that were searched."""

    query_time_ms: float
    """Time taken to execute the query in milliseconds."""


class RandomClipsRequest(BaseModel):
    """Request for random clips with embeddings."""

    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    """Name of the model whose embeddings to sample from."""

    dataset_uuids: list[UUID] | None = None
    """Filter to only include clips from these datasets."""

    limit: int = Field(default=10, ge=1, le=50)
    """Number of random clips to return."""


class RandomClipsResponse(BaseModel):
    """Response containing random clips with embeddings."""

    clips: list[SearchResultItem]
    """List of randomly selected clips."""

    total_available: int
    """Total number of clips with embeddings available (matching filters)."""
