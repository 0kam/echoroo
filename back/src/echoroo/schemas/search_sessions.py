"""Schemas for Search Sessions and Results with Active Learning support."""

import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.models.search_session import SampleType
from echoroo.schemas.base import BaseSchema
from echoroo.schemas.clips import Clip
from echoroo.schemas.tags import Tag

# Distance metric type for similarity search
DistanceMetricType = Literal["cosine", "euclidean"]

__all__ = [
    "DistanceMetricType",
    "SearchSessionTargetTag",
    "SearchSession",
    "SearchSessionCreate",
    "SearchResult",
    "SearchResultLabelData",
    "SearchProgress",
    "BulkLabelRequest",
    "BulkCurateRequest",
    "RunIterationRequest",
    "ExportToAnnotationProjectRequest",
    "ExportToAnnotationProjectResponse",
    "TagScoreDistribution",
    "ScoreDistributionResponse",
    "FinalizeRequest",
    "FinalizeResponse",
]


class SearchSessionTargetTag(BaseSchema):
    """Target tag within a search session with shortcut key assignment."""

    tag_id: int
    """The ID of the target tag."""

    tag: Tag
    """The hydrated tag information."""

    shortcut_key: int = Field(ge=1, le=9)
    """Keyboard shortcut key (1-9) for quick labeling."""


class SearchSessionCreate(BaseModel):
    """Schema for creating a search session with Active Learning parameters."""

    name: str | None = Field(default=None, max_length=255)
    """Optional name for the search session."""

    reference_sound_ids: list[UUID] = Field(
        ...,
        min_length=1,
        description="Reference sounds to use for the search (UUIDs). "
        "Target tags are auto-populated from reference sounds.",
    )
    """List of reference sound UUIDs to search with."""

    # Active Learning sampling parameters
    easy_positive_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of top-k similar clips per reference (easy positives)",
    )
    """Number of top-k most similar clips to select as easy positives."""

    boundary_n: int = Field(
        default=200,
        ge=50,
        le=1000,
        description="Number of boundary candidates to consider",
    )
    """Number of clips below easy positives to consider for boundary sampling."""

    boundary_m: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Number of boundary samples to select",
    )
    """Number of boundary samples to randomly select from candidates."""

    others_p: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Number of diverse 'others' samples",
    )
    """Number of diverse samples to select using farthest-first selection."""

    distance_metric: DistanceMetricType = Field(
        default="cosine",
        description="Distance metric for similarity search: 'cosine' or 'euclidean'",
    )
    """Distance metric to use for similarity search."""

    notes: str | None = Field(default=None, max_length=2000)
    """Optional notes about the search session."""


class SearchResultLabelData(BaseModel):
    """Data for labeling a search result in Active Learning.

    A result can be labeled in one of several ways:
    - assigned_tag_ids: Assign multiple tags (multi-label, preferred)
    - assigned_tag_id: Assign a single tag (deprecated, for backward compatibility)
    - is_negative: Mark as not containing any target sound
    - is_uncertain: Mark as uncertain/needs review
    - is_skipped: Skip without labeling
    """

    assigned_tag_ids: list[int] = Field(
        default_factory=list,
        description="Tag IDs to assign (multi-label support)",
    )
    """Tags to assign to this result (multi-label support)."""

    is_negative: bool = Field(
        default=False,
        description="Mark as negative (no target sound)",
    )
    """Whether this result is negative (does not contain target sound)."""

    is_uncertain: bool = Field(
        default=False,
        description="Mark as uncertain",
    )
    """Whether this result is uncertain and needs review."""

    is_skipped: bool = Field(
        default=False,
        description="Skip without labeling",
    )
    """Whether this result was skipped."""

    notes: str | None = Field(default=None, max_length=2000)
    """Optional notes about the labeling decision."""

    def get_tag_ids(self) -> list[int]:
        """Get all assigned tag IDs.

        Returns
        -------
        list[int]
            List of assigned tag IDs.
        """
        return list(self.assigned_tag_ids)


class SearchResult(BaseSchema):
    """Search result with Active Learning label fields."""

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

    similarity: float = Field(ge=0.0, le=1.0)
    """Similarity score between the reference and this clip."""

    rank: int = Field(ge=1)
    """Rank of this result within the session (1 = most similar)."""

    # Multi-label support
    assigned_tag_ids: list[int] = Field(default_factory=list)
    """Tag IDs assigned to this result (multi-label support)."""

    assigned_tags: list[Tag] = Field(default_factory=list)
    """Hydrated tags assigned to this result (multi-label support)."""

    is_negative: bool = False
    """Whether this result is marked as negative."""

    is_uncertain: bool = False
    """Whether this result is marked as uncertain."""

    is_skipped: bool = False
    """Whether this result was skipped during labeling."""

    # Sampling metadata
    sample_type: SampleType | None = None
    """Type of sample: easy_positive, boundary, others, or active_learning."""

    iteration_added: int | None = None
    """The active learning iteration when this sample was added (0 = initial)."""

    model_score: float | None = None
    """Model prediction score for active learning samples."""

    source_tag_id: int | None = None
    """The source tag from which this sample was derived."""

    source_tag: Tag | None = None
    """Hydrated source tag information."""

    # User tracking
    labeled_at: datetime.datetime | None = None
    """Timestamp when the result was labeled."""

    labeled_by_id: UUID | None = None
    """User who labeled the result."""

    notes: str | None = None
    """Optional notes about this result."""

    # Score display fields (for percentile and raw value display)
    raw_score: float | None = None
    """Raw score value (cosine: similarity 0-1, euclidean: distance 0-inf)."""

    score_percentile: float | None = None
    """Percentile rank within session (0-100). Higher = more similar."""

    result_distance_metric: DistanceMetricType | None = None
    """The distance metric used for this result: 'cosine' or 'euclidean'."""


class SearchSession(BaseSchema):
    """Schema for a search session with Active Learning support."""

    uuid: UUID
    """UUID of the search session."""

    id: int = Field(..., exclude=True)
    """Database ID of the search session."""

    name: str | None = None
    """Optional name for the search session."""

    description: str | None = None
    """Optional description of the search session."""

    ml_project_id: int = Field(..., exclude=True)
    """ML project that owns this session."""

    ml_project_uuid: UUID
    """UUID of the owning ML project."""

    # Multi-tag support
    target_tags: list[SearchSessionTargetTag] = Field(default_factory=list)
    """Target tags for this search session with shortcut keys."""

    # Active Learning parameters
    easy_positive_k: int = 5
    """Number of easy positive samples per reference."""

    boundary_n: int = 200
    """Number of boundary candidates to consider."""

    boundary_m: int = 10
    """Number of boundary samples to select."""

    others_p: int = 20
    """Number of diverse 'others' samples."""

    distance_metric: str = "cosine"
    """Distance metric used for this search session."""

    current_iteration: int = 0
    """Current active learning iteration number (0 = initial sampling)."""

    # Status flags
    is_search_complete: bool = False
    """Whether the initial sampling has completed."""

    # Progress counts
    total_results: int = 0
    """Total number of results in this session."""

    labeled_count: int = 0
    """Number of results that have been labeled (any label)."""

    unlabeled_count: int = 0
    """Number of results that have not been labeled."""

    negative_count: int = 0
    """Number of results labeled as negative."""

    uncertain_count: int = 0
    """Number of results labeled as uncertain."""

    skipped_count: int = 0
    """Number of results that were skipped."""

    # Per-tag counts
    tag_counts: dict[int, int] = Field(default_factory=dict)
    """Count of results assigned to each tag (tag_id -> count)."""

    notes: str | None = None
    """Optional notes about the search session."""

    reference_sounds: list = Field(default_factory=list)
    """Reference sounds used for this search."""

    created_by_id: UUID | None = None
    """User who created the search session."""

    created_on: datetime.datetime | None = None
    """Timestamp when the session was created."""


class SearchProgress(BaseModel):
    """Schema for search session progress tracking."""

    total: int = 0
    """Total number of results in the session."""

    labeled: int = 0
    """Number of results that have been labeled."""

    unlabeled: int = 0
    """Number of unlabeled results remaining."""

    negative: int = 0
    """Number of negative labels."""

    uncertain: int = 0
    """Number of uncertain labels."""

    skipped: int = 0
    """Number of skipped results."""

    tag_counts: dict[int, int] = Field(default_factory=dict)
    """Count of results per assigned tag (tag_id -> count)."""

    progress_percent: float = 0.0
    """Percentage of results that have been labeled."""


class BulkLabelRequest(BaseModel):
    """Schema for bulk labeling search results with Active Learning labels."""

    result_uuids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="UUIDs of results to label",
    )
    """List of search result UUIDs to update."""

    label_data: SearchResultLabelData = Field(
        ...,
        description="Label data to apply to all results",
    )
    """Label to apply to all specified results."""


class BulkCurateRequest(BaseModel):
    """Schema for bulk curation of search results as references."""

    result_uuids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="UUIDs of results to curate",
    )
    """List of search result UUIDs to curate."""

    assigned_tag_id: int = Field(
        ...,
        description="Tag ID to assign as positive reference",
    )
    """Tag to assign to all specified results."""


class RunIterationRequest(BaseModel):
    """Schema for running an active learning iteration with custom parameters."""

    uncertainty_low: float = Field(
        default=0.25,
        ge=0.0,
        le=0.5,
        description="Lower bound of uncertainty region (0.0-0.5)",
    )
    """Lower threshold for uncertainty region."""

    uncertainty_high: float = Field(
        default=0.75,
        ge=0.5,
        le=1.0,
        description="Upper bound of uncertainty region (0.5-1.0)",
    )
    """Upper threshold for uncertainty region."""

    samples_per_iteration: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Number of samples to add in this iteration",
    )
    """Number of samples to select from the uncertainty region."""

    selected_tag_ids: list[int] | None = Field(
        default=None,
        description="Tag IDs to include in this iteration. If None, all tags are included.",
    )
    """Optional list of tag IDs to train classifiers for and select samples from."""

    classifier_type: str = Field(
        default="logistic_regression",
        description="Classifier type: logistic_regression, svm_linear, mlp_small, mlp_medium, random_forest",
    )
    """Type of classifier to use for this iteration."""


class ExportToAnnotationProjectRequest(BaseModel):
    """Schema for exporting search results to an annotation project."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name for the new annotation project",
    )
    """Name for the annotation project."""

    description: str = Field(
        default="",
        max_length=2000,
        description="Description for the annotation project",
    )
    """Description for the annotation project."""

    include_labeled: bool = Field(
        default=True,
        description="Include results with assigned tags",
    )
    """Whether to include results that have been labeled with tags."""

    include_tag_ids: list[int] | None = Field(
        default=None,
        description="Specific tag IDs to include (None = all labeled)",
    )
    """Optional list of specific tag IDs to include."""


class ExportToAnnotationProjectResponse(BaseModel):
    """Schema for export operation response."""

    annotation_project_uuid: UUID
    """UUID of the created annotation project."""

    annotation_project_name: str
    """Name of the created annotation project."""

    exported_count: int
    """Number of search results exported."""

    message: str
    """Success message."""


class TagScoreDistribution(BaseModel):
    """Score distribution for a specific tag at a specific iteration."""

    tag_id: int
    """ID of the tag."""

    tag_name: str
    """Name of the tag."""

    iteration: int
    """Active learning iteration number."""

    bin_counts: list[int]
    """Count of scores in each bin (20 bins total)."""

    bin_edges: list[float]
    """Edges of the histogram bins (21 edges: [0.0, 0.05, ..., 1.0])."""

    positive_count: int
    """Number of positive samples for this tag."""

    negative_count: int
    """Number of negative samples for this tag."""

    mean_score: float
    """Mean prediction score across all unlabeled samples."""


class ScoreDistributionResponse(BaseModel):
    """Response for score distribution endpoint."""

    distributions: list[TagScoreDistribution]
    """Score distributions for each tag."""


class FinalizeRequest(BaseModel):
    """Schema for finalizing a search session and saving the trained model."""

    model_config = {"protected_namespaces": ()}

    model_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name for the saved model",
    )
    """Name for the custom model to be created."""

    model_type: str = Field(
        default="logistic_regression",
        description="Classifier type: logistic_regression, svm_linear, mlp_small, mlp_medium, random_forest",
    )
    """Type of classifier to train and save."""

    create_annotation_project: bool = Field(
        default=True,
        description="Whether to create an annotation project from labeled results",
    )
    """Whether to also create an annotation project with labeled clips."""

    annotation_project_name: str | None = Field(
        default=None,
        max_length=255,
        description="Name for annotation project (defaults to model_name if not provided)",
    )
    """Optional name for the annotation project. Uses model_name if not specified."""

    description: str = Field(
        default="",
        max_length=2000,
        description="Description for the model and annotation project",
    )
    """Optional description."""


class FinalizeResponse(BaseModel):
    """Response from finalizing a search session."""

    custom_model_uuid: UUID
    """UUID of the created custom model."""

    custom_model_name: str
    """Name of the created custom model."""

    annotation_project_uuid: UUID | None = None
    """UUID of the created annotation project (if created)."""

    annotation_project_name: str | None = None
    """Name of the created annotation project (if created)."""

    positive_count: int
    """Number of positive samples used for training."""

    negative_count: int
    """Number of negative samples used for training."""

    message: str
    """Success message with details."""
