"""Schemas for Search Sessions and Results."""

import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.clips import Clip
from echoroo.schemas.tags import Tag

__all__ = [
    "SearchResultLabel",
    "SearchSession",
    "SearchSessionCreate",
    "SearchResult",
    "SearchResultLabelUpdate",
    "SearchProgress",
    "BulkLabelRequest",
]


class SearchResultLabel(str, Enum):
    """Label assigned to a search result."""

    UNLABELED = "unlabeled"
    """Result has not been labeled yet."""

    POSITIVE = "positive"
    """Result contains the target sound (true positive)."""

    NEGATIVE = "negative"
    """Result does not contain the target sound (false positive)."""

    UNCERTAIN = "uncertain"
    """Reviewer is uncertain about the classification."""

    SKIPPED = "skipped"
    """Result was skipped without labeling."""


class SearchSessionCreate(BaseModel):
    """Schema for creating a search session."""

    name: str | None = Field(default=None, max_length=255)
    """Optional name for the search session."""

    reference_sound_ids: list[int] = Field(
        ...,
        min_length=1,
        description="Reference sounds to use for the search",
    )
    """List of reference sound IDs to search with."""

    similarity_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for results",
    )
    """Minimum similarity threshold for including results."""

    max_results: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum number of results to return",
    )
    """Maximum number of results to retrieve."""

    tag_id: int | None = Field(
        default=None,
        description="Optional tag to filter target species",
    )
    """Optional tag to restrict search to a specific species."""

    notes: str | None = Field(default=None, max_length=2000)
    """Optional notes about the search session."""


class SearchResult(BaseSchema):
    """Schema for a search result returned to the user."""

    uuid: UUID
    """UUID of the search result."""

    id: int = Field(..., exclude=True)
    """Database ID of the search result."""

    search_session_id: int = Field(..., exclude=True)
    """Search session that produced this result."""

    search_session_uuid: UUID
    """UUID of the owning search session."""

    clip_id: int = Field(..., exclude=True)
    """Clip identifier for this result."""

    clip: Clip
    """Hydrated clip information."""

    reference_sound_id: int = Field(..., exclude=True)
    """Reference sound that matched this clip."""

    reference_sound_uuid: UUID
    """UUID of the matched reference sound."""

    similarity_score: float = Field(ge=0.0, le=1.0)
    """Similarity score between the reference and this clip."""

    rank: int = Field(ge=1)
    """Rank of this result within the session (1 = most similar)."""

    label: SearchResultLabel = SearchResultLabel.UNLABELED
    """Label assigned by the reviewer."""

    labeled_at: datetime.datetime | None = None
    """Timestamp when the result was labeled."""

    labeled_by_id: UUID | None = None
    """User who labeled the result."""

    notes: str | None = None
    """Optional notes about this result."""


class SearchSession(BaseSchema):
    """Schema for a search session returned to the user."""

    uuid: UUID
    """UUID of the search session."""

    id: int = Field(..., exclude=True)
    """Database ID of the search session."""

    name: str | None = None
    """Optional name for the search session."""

    ml_project_id: int = Field(..., exclude=True)
    """ML project that owns this session."""

    ml_project_uuid: UUID
    """UUID of the owning ML project."""

    similarity_threshold: float
    """Similarity threshold used for this search."""

    max_results: int
    """Maximum results requested."""

    tag_id: int | None = Field(default=None, exclude=True)
    """Target tag identifier if specified."""

    tag: Tag | None = None
    """Hydrated tag information if specified."""

    total_results: int = 0
    """Total number of results in this session."""

    labeled_count: int = 0
    """Number of results that have been labeled."""

    positive_count: int = 0
    """Number of results labeled as positive."""

    negative_count: int = 0
    """Number of results labeled as negative."""

    uncertain_count: int = 0
    """Number of results labeled as uncertain."""

    skipped_count: int = 0
    """Number of results that were skipped."""

    notes: str | None = None
    """Optional notes about the search session."""

    created_by_id: UUID
    """User who created the search session."""

    completed_at: datetime.datetime | None = None
    """Timestamp when review was completed."""


class SearchResultLabelUpdate(BaseModel):
    """Schema for updating a search result label."""

    label: SearchResultLabel = Field(
        ...,
        description="New label for the result",
    )
    """New label to assign."""

    notes: str | None = Field(default=None, max_length=2000)
    """Optional notes about the labeling decision."""


class SearchProgress(BaseModel):
    """Schema for search session progress tracking."""

    total: int = 0
    """Total number of results in the session."""

    labeled: int = 0
    """Number of results that have been labeled."""

    positive: int = 0
    """Number of positive labels."""

    negative: int = 0
    """Number of negative labels."""

    uncertain: int = 0
    """Number of uncertain labels."""

    skipped: int = 0
    """Number of skipped results."""

    unlabeled: int = 0
    """Number of unlabeled results remaining."""

    progress_percent: float = 0.0
    """Percentage of results that have been labeled."""


class BulkLabelRequest(BaseModel):
    """Schema for bulk labeling search results."""

    result_uuids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="UUIDs of results to label",
    )
    """List of search result UUIDs to update."""

    label: SearchResultLabel = Field(
        ...,
        description="Label to apply to all results",
    )
    """Label to apply to all specified results."""

    notes: str | None = Field(default=None, max_length=2000)
    """Optional notes to apply to all results."""
