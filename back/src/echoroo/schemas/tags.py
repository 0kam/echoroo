"""Schemas for handling Tags."""

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema

__all__ = [
    "Tag",
    "TagCreate",
    "TagUpdate",
    "TagCount",
    "PredictedTag",
]


class TagCreate(BaseModel):
    """Schema for creating Tag objects."""

    key: str = Field(min_length=1, max_length=255)
    """Key of the tag."""

    value: str = Field(min_length=1, max_length=255)
    """Value of the tag (e.g., a GBIF usage key)."""

    canonical_name: str = Field(min_length=1, max_length=255)
    """Human readable representation of the tag (e.g., scientific name)."""


class Tag(BaseSchema):
    """Schema for Tag objects returned to the user."""

    id: int
    """Database ID of the tag."""

    key: str
    """Key of the tag."""

    value: str
    """Value of the tag (e.g., usage key)."""

    canonical_name: str
    """Human readable representation of the tag."""

    vernacular_name: str | None = None
    """Vernacular (common) name for species tags."""


class TagUpdate(BaseModel):
    """Schema for updating Tag objects."""

    key: str | None = Field(default=None, min_length=1, max_length=255)
    """Key of the tag."""

    value: str | None = Field(default=None, min_length=1, max_length=255)
    """Value of the tag."""

    canonical_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
    )
    """Human readable representation of the tag."""


class PredictedTag(BaseSchema):
    """Schema for PredictedTag objects returned to the user."""

    tag: Tag
    """The tag that was predicted."""

    score: float
    """The confidence score for the assignment of the tag."""


class TagCount(BaseSchema):
    """Schema for TagCount objects returned to the user."""

    tag: Tag
    """Tag object."""

    count: int
    """Count of the tag."""
