"""Schemas for foundation model detection to annotation project conversion."""

from uuid import UUID

from pydantic import BaseModel, Field

__all__ = [
    "ConvertToAnnotationProjectRequest",
    "ConvertToAnnotationProjectResponse",
]


class ConvertToAnnotationProjectRequest(BaseModel):
    """Request payload for converting foundation model detections to annotation project."""

    name: str = Field(..., min_length=1, max_length=255)
    """Name of the annotation project to create."""

    description: str | None = None
    """Optional description of the annotation project."""

    include_only_filtered: bool = False
    """If True, only include detections that passed the species filter."""

    species_filter_application_uuid: UUID | None = None
    """UUID of the species filter application to use for filtering.

    Required if include_only_filtered is True.
    """


class ConvertToAnnotationProjectResponse(BaseModel):
    """Response from converting foundation model detections to annotation project."""

    annotation_project_uuid: UUID
    """UUID of the created annotation project."""

    annotation_project_name: str
    """Name of the created annotation project."""

    total_tasks_created: int
    """Total number of annotation tasks created."""

    total_annotations_created: int
    """Total number of clip annotations created."""

    total_tags_added: int = 0
    """Total number of species tags added to the project."""
