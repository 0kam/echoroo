"""Schemas for Annotation Projects."""

from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from whombat.schemas.base import BaseSchema
from whombat.schemas.tags import Tag
from whombat.models.dataset import VisibilityLevel

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

    visibility: VisibilityLevel = VisibilityLevel.PRIVATE
    """Visibility level for the project."""

    owner_group_id: int | None = None
    """Owning group when restricted."""

    @model_validator(mode="after")
    def _validate_visibility(self):
        if (
            self.visibility == VisibilityLevel.RESTRICTED
            and self.owner_group_id is None
        ):
            raise ValueError(
                "Restricted visibility requires owner_group_id to be set."
            )
        if (
            self.visibility != VisibilityLevel.RESTRICTED
            and self.owner_group_id is not None
        ):
            raise ValueError(
                "owner_group_id can only be set when visibility is 'restricted'."
            )
        return self


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

    owner_group_id: int | None = None
    """Owning group when restricted."""


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

    owner_group_id: int | None = None
    """Owning group when restricted."""

    @model_validator(mode="after")
    def _validate_visibility(self):
        if (
            self.visibility == VisibilityLevel.RESTRICTED
            and self.owner_group_id is None
        ):
            raise ValueError(
                "Changing visibility to 'restricted' requires owner_group_id."
            )
        if (
            self.visibility is not None
            and self.visibility != VisibilityLevel.RESTRICTED
            and self.owner_group_id is not None
        ):
            raise ValueError(
                "owner_group_id can only be set when visibility is 'restricted'."
            )
        return self
