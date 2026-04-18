"""Pydantic schemas for the ground-truth annotation feature (spec 003-annotation).

Covers ``AnnotationSet``, ``AnnotationSegment`` and ``TimeRangeAnnotation``
plus the species-palette and note-attachment payloads.

Schema field naming follows the public OpenAPI contract
(``specs/003-annotation/contracts/``): the wire format exposes
``species_id``, while the ORM layer stores the same value in a column
named ``taxon_id`` because Echoroo's canonical taxonomic entity is
:class:`echoroo.models.taxon.Taxon`. Schemas that hydrate directly from
ORM instances use Pydantic ``AliasChoices`` so both names are accepted
on input and the ORM attribute is picked up correctly on output.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

# ---------------------------------------------------------------------------
# Shared sub-schemas (filters)
# ---------------------------------------------------------------------------


class DateRangeFilter(BaseModel):
    """Inclusive date range ``{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}``.

    Persisted as JSONB on ``annotation_sets.filter_date_range``.
    """

    start: str = Field(..., description="Inclusive start date, ISO 8601 (YYYY-MM-DD)")
    end: str = Field(..., description="Inclusive end date, ISO 8601 (YYYY-MM-DD)")


class TimeOfDayRangeFilter(BaseModel):
    """Local time-of-day range; may wrap midnight.

    Persisted as JSONB on ``annotation_sets.filter_time_of_day_range``.
    """

    start: str = Field(..., description="Start time, HH:MM (24h)")
    end: str = Field(..., description="End time, HH:MM (24h)")


# ---------------------------------------------------------------------------
# AnnotationSet
# ---------------------------------------------------------------------------


class AnnotationSetCreate(BaseModel):
    """Request schema for creating an ``AnnotationSet``.

    The background sampling job is dispatched via ``POST
    /annotation-sets/{id}/sample`` after creation; on successful create the
    row is returned with ``status = sampling``.
    """

    project_id: UUID = Field(..., description="Owning project ID")
    dataset_id: UUID = Field(..., description="Source dataset ID")
    name: str = Field(..., min_length=1, max_length=200, description="Display name")
    filter_date_range: DateRangeFilter | None = Field(
        default=None,
        description="Optional inclusive date filter on recording.recorded_at",
    )
    filter_time_of_day_range: TimeOfDayRangeFilter | None = Field(
        default=None,
        description="Optional local time-of-day filter (may wrap midnight)",
    )
    segment_length_sec: int = Field(
        ...,
        ge=10,
        description="Length of every sampled segment in seconds (minimum 10)",
    )
    num_segments: int = Field(
        ...,
        ge=1,
        description="Target number of segments to materialize",
    )


class AnnotationSetUpdate(BaseModel):
    """Request schema for updating an ``AnnotationSet``.

    Sampling parameters cannot be changed once sampling is in progress
    (enforced at the service layer); ``name`` is always mutable.
    """

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="New display name",
    )
    filter_date_range: DateRangeFilter | None = Field(
        default=None,
        description="New date filter (only accepted before sampling completes)",
    )
    filter_time_of_day_range: TimeOfDayRangeFilter | None = Field(
        default=None,
        description="New time-of-day filter (only accepted before sampling completes)",
    )
    segment_length_sec: int | None = Field(
        default=None,
        ge=10,
        description="New segment length (only accepted before sampling completes)",
    )
    num_segments: int | None = Field(
        default=None,
        ge=1,
        description="New target count (only accepted before sampling completes)",
    )


class AnnotationSetResponse(BaseModel):
    """Response schema for an ``AnnotationSet`` row."""

    id: UUID
    project_id: UUID
    dataset_id: UUID
    created_by_id: UUID
    name: str
    filter_date_range: DateRangeFilter | None = None
    filter_time_of_day_range: TimeOfDayRangeFilter | None = None
    segment_length_sec: int
    num_segments: int
    status: Literal["sampling", "ready", "in_progress", "completed"]
    sampling_warning: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnnotationSetProgress(BaseModel):
    """Per-status segment counts aggregated for an AnnotationSet."""

    total: int
    unannotated: int
    annotated: int
    skipped: int
    empty: int


class PaletteEntryResponse(BaseModel):
    """Response schema for a palette entry.

    ``species_id`` is the wire name for the underlying ``taxon_id`` column.
    """

    species_id: UUID = Field(
        ...,
        validation_alias=AliasChoices("species_id", "taxon_id"),
        serialization_alias="species_id",
    )
    scientific_name: str | None = None
    common_name: str | None = None
    position: int

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class AnnotationSetDetailResponse(AnnotationSetResponse):
    """Detail response with palette and per-status progress counts."""

    palette: list[PaletteEntryResponse] = Field(default_factory=list)
    progress: AnnotationSetProgress


class AnnotationSetListResponse(BaseModel):
    """Paginated list of annotation sets."""

    items: list[AnnotationSetResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Species palette
# ---------------------------------------------------------------------------


class PaletteItemCreate(BaseModel):
    """Request schema for adding a species to the per-set palette.

    Accepts either ``species_id`` (preferred, matches the contract) or
    ``taxon_id`` (legacy alias).
    """

    species_id: UUID = Field(
        ...,
        validation_alias=AliasChoices("species_id", "taxon_id"),
        serialization_alias="species_id",
        description="Taxon (species) ID to add",
    )
    position: int = Field(
        default=0, ge=0, description="Ordering hint for UI / keyboard slots",
    )

    model_config = ConfigDict(populate_by_name=True)


# ---------------------------------------------------------------------------
# AnnotationSegment
# ---------------------------------------------------------------------------


class AnnotationSegmentResponse(BaseModel):
    """Response schema for an ``AnnotationSegment`` row (list view)."""

    id: UUID
    annotation_set_id: UUID
    recording_id: UUID
    recording_filename: str | None = None
    start_time_sec: float
    end_time_sec: float
    is_empty: bool
    status: Literal["unannotated", "annotated", "skipped"]
    annotated_by_id: UUID | None = None
    annotated_at: datetime | None = None
    annotation_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnnotationSegmentStatusUpdate(BaseModel):
    """Request schema for updating an ``AnnotationSegment``'s lifecycle state.

    - To mark empty: ``is_empty = true`` (service layer rejects this when any
      TimeRangeAnnotation exists).
    - To finalize with existing annotations: ``status = "annotated"``.
    - To skip: ``status = "skipped"``.
    """

    status: Literal["unannotated", "annotated", "skipped"] | None = None
    is_empty: bool | None = None


class AnnotationSegmentListResponse(BaseModel):
    """Paginated list of annotation segments."""

    items: list[AnnotationSegmentResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# TimeRangeAnnotation
# ---------------------------------------------------------------------------


class TimeRangeAnnotationCreate(BaseModel):
    """Request schema for creating a ``TimeRangeAnnotation`` inside a segment.

    Accepts either ``species_id`` or ``taxon_id`` on the wire.
    """

    start_time_sec: float = Field(
        ..., ge=0, description="Start offset in seconds inside the segment",
    )
    end_time_sec: float = Field(
        ..., gt=0, description="End offset in seconds inside the segment",
    )
    species_id: UUID = Field(
        ...,
        validation_alias=AliasChoices("species_id", "taxon_id"),
        serialization_alias="species_id",
        description="Taxon (species) ID",
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Optional annotator confidence",
    )

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _check_range(self) -> TimeRangeAnnotationCreate:
        if self.end_time_sec <= self.start_time_sec:
            raise ValueError("end_time_sec must be greater than start_time_sec")
        return self


class TimeRangeAnnotationUpdate(BaseModel):
    """Request schema for updating a ``TimeRangeAnnotation``.

    All fields are optional; only supplied fields are modified.
    """

    start_time_sec: float | None = Field(default=None, ge=0)
    end_time_sec: float | None = Field(default=None, gt=0)
    species_id: UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("species_id", "taxon_id"),
        serialization_alias="species_id",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    model_config = ConfigDict(populate_by_name=True)


class TimeRangeAnnotationResponse(BaseModel):
    """Response schema for a ``TimeRangeAnnotation`` row."""

    id: UUID
    segment_id: UUID
    start_time_sec: float
    end_time_sec: float
    species_id: UUID = Field(
        ...,
        validation_alias=AliasChoices("species_id", "taxon_id"),
        serialization_alias="species_id",
    )
    species_scientific_name: str | None = None
    species_common_name: str | None = None
    confidence: float | None = None
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    note_count: int = 0

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Segment detail (with annotations + notes)
# ---------------------------------------------------------------------------


class AnnotationNoteCreate(BaseModel):
    """Request schema for attaching a note to a segment or TimeRangeAnnotation."""

    content: str = Field(..., min_length=1, max_length=5000)
    is_issue: bool = Field(
        default=False,
        description="Flag this note as raising a quality concern (surfaced in UI)",
    )


class AnnotationNoteResponse(BaseModel):
    """Response schema for a note attached to an annotation entity."""

    id: UUID
    content: str
    is_issue: bool
    is_review: bool
    created_by_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AnnotationSegmentDetailResponse(BaseModel):
    """Response schema for a segment detail view, including children."""

    id: UUID
    annotation_set_id: UUID
    recording_id: UUID
    recording_filename: str | None = None
    recording_duration_sec: float | None = None
    start_time_sec: float
    end_time_sec: float
    is_empty: bool
    status: Literal["unannotated", "annotated", "skipped"]
    annotated_by_id: UUID | None = None
    annotated_at: datetime | None = None
    annotations: list[TimeRangeAnnotationResponse] = Field(default_factory=list)
    notes: list[AnnotationNoteResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Celery dispatch response
# ---------------------------------------------------------------------------


class AnnotationSetSampleDispatchResponse(BaseModel):
    """Response for ``POST /annotation-sets/{id}/sample``."""

    task_id: str
    status: Literal["sampling", "ready", "in_progress", "completed"]
