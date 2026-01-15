"""Schemas for Annotation Projects."""

from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.tags import Tag
from echoroo.models.dataset import VisibilityLevel

__all__ = [
    "VisibilityLevel",
    "AnnotationProjectCreate",
    "AnnotationProject",
    "AnnotationProjectUpdate",
]


class AnnotationProjectCreate(BaseModel):
    """Schema for creating an annotation project."""

    name: str
    """Name of the annotation project."""

    description: str
    """A description of the annotation project."""

    annotation_instructions: str | None = None
    """Project instructions for annotating."""

    visibility: VisibilityLevel = VisibilityLevel.RESTRICTED
    """Visibility level for the project."""

    dataset_id: int = Field(..., description="Primary dataset identifier")
    """Dataset that backs the annotation project."""


class AnnotationProject(BaseSchema):
    """Schema for an annotation project."""

    uuid: UUID
    """UUID of the annotation project."""

    id: int = Field(..., exclude=True)
    """Database ID of the annotation project."""

    name: str
    """Name of the annotation project."""

    description: str
    """A description of the annotation project."""

    annotation_instructions: str | None = None
    """Project instructions for annotating."""

    tags: list[Tag] = Field(default_factory=list)
    """Tags to be used throughout the annotation project."""

    visibility: VisibilityLevel
    """Visibility level for the project."""

    created_by_id: UUID
    """User who created the project."""

    dataset_id: int
    """Dataset identifier backing the annotation project."""

    project_id: str
    """Project identifier derived from the dataset."""


class AnnotationProjectUpdate(BaseModel):
    """Schema for updating an annotation project."""

    name: str | None = None
    """Name of the annotation project."""

    description: str | None = None
    """A description of the annotation project."""

    annotation_instructions: str | None = None
    """Project instructions for annotating."""

    visibility: VisibilityLevel | None = None
    """Updated visibility."""

    dataset_id: int | None = None
    """Dataset identifier backing the annotation project."""
