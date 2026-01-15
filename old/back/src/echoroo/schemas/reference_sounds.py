"""Schemas for Reference Sounds."""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.clips import Clip
from echoroo.schemas.tags import Tag

__all__ = [
    "ReferenceSoundSource",
    "ReferenceSound",
    "ReferenceSoundCreate",
    "ReferenceSoundFromXenoCanto",
    "ReferenceSoundFromClip",
    "ReferenceSoundUpdate",
]


class ReferenceSoundSource(str, Enum):
    """Source type for a reference sound."""

    XENO_CANTO = "xeno_canto"
    """Reference sound imported from Xeno-Canto database."""

    CLIP = "clip"
    """Reference sound extracted from an existing clip in the dataset."""

    UPLOAD = "upload"
    """Reference sound uploaded directly by the user."""

    ANNOTATION = "annotation"
    """Reference sound derived from an existing annotation."""


class ReferenceSoundCreate(BaseModel):
    """Base schema for creating a reference sound."""

    name: str = Field(..., min_length=1, max_length=255)
    """Human-readable name for the reference sound."""

    tag_id: int = Field(..., description="Tag identifier for classification")
    """Tag that this reference sound represents."""

    start_time: float = Field(ge=0.0)
    """Start time of the sound segment in seconds."""

    end_time: float = Field(gt=0.0)
    """End time of the sound segment in seconds."""

    notes: str | None = Field(default=None, max_length=1000)
    """Optional notes about the reference sound."""

    @model_validator(mode="after")
    def validate_times(self):
        """Validate that start_time < end_time."""
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be less than end_time")
        return self


class ReferenceSoundFromXenoCanto(ReferenceSoundCreate):
    """Schema for creating a reference sound from Xeno-Canto."""

    xeno_canto_id: str = Field(..., min_length=1, max_length=50)
    """Xeno-Canto recording identifier (e.g., 'XC123456')."""

    source: ReferenceSoundSource = Field(
        default=ReferenceSoundSource.XENO_CANTO,
        frozen=True,
    )
    """Source type (fixed to xeno_canto)."""


class ReferenceSoundFromClip(ReferenceSoundCreate):
    """Schema for creating a reference sound from an existing clip."""

    clip_id: int = Field(..., description="Clip identifier")
    """Clip to use as the basis for the reference sound."""

    source: ReferenceSoundSource = Field(
        default=ReferenceSoundSource.CLIP,
        frozen=True,
    )
    """Source type (fixed to clip)."""


class ReferenceSound(BaseSchema):
    """Schema for a reference sound returned to the user."""

    uuid: UUID
    """UUID of the reference sound."""

    id: int = Field(..., exclude=True)
    """Database ID of the reference sound."""

    name: str
    """Human-readable name for the reference sound."""

    ml_project_id: int = Field(..., exclude=True)
    """ML project that owns this reference sound."""

    ml_project_uuid: UUID
    """UUID of the owning ML project."""

    source: ReferenceSoundSource
    """Source type of the reference sound."""

    tag_id: int = Field(..., exclude=True)
    """Tag identifier for classification."""

    tag: Tag
    """Tag that this reference sound represents."""

    start_time: float
    """Start time of the sound segment in seconds."""

    end_time: float
    """End time of the sound segment in seconds."""

    duration: float = Field(default=0.0)
    """Duration of the reference sound in seconds."""

    xeno_canto_id: str | None = None
    """Xeno-Canto recording identifier if sourced from XC."""

    clip_id: int | None = Field(default=None, exclude=True)
    """Clip identifier if sourced from a clip."""

    clip: Clip | None = None
    """Hydrated clip information if sourced from a clip."""

    audio_path: str | None = None
    """Path to the cached audio file."""

    embedding_count: int = 0
    """Number of embeddings computed for this sound."""

    notes: str | None = None
    """Optional notes about the reference sound."""

    is_active: bool = True
    """Whether the reference sound is active for searches."""

    created_by_id: UUID
    """User who created the reference sound."""


class ReferenceSoundUpdate(BaseModel):
    """Schema for updating a reference sound."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    """Human-readable name for the reference sound."""

    tag_id: int | None = None
    """Tag identifier for classification."""

    start_time: float | None = Field(default=None, ge=0.0)
    """Start time of the sound segment in seconds."""

    end_time: float | None = Field(default=None, gt=0.0)
    """End time of the sound segment in seconds."""

    notes: str | None = Field(default=None, max_length=1000)
    """Optional notes about the reference sound."""

    is_active: bool | None = None
    """Whether the reference sound is active for searches."""

    @model_validator(mode="after")
    def validate_times(self):
        """Validate that start_time < end_time if both are provided."""
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time >= self.end_time
        ):
            raise ValueError("start_time must be less than end_time")
        return self
