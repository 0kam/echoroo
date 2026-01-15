"""Schemas for Clip Prediction related objects."""

from uuid import UUID

from pydantic import BaseModel, Field

from echoroo.schemas.base import BaseSchema
from echoroo.schemas.clips import Clip
from echoroo.schemas.sound_event_predictions import SoundEventPrediction
from echoroo.schemas.tags import PredictedTag, Tag

__all__ = [
    "ClipPrediction",
    "ClipPredictionCreate",
    "ClipPredictionUpdate",
]


class ClipPredictionCreate(BaseModel):
    """Schema for creating a new clip prediction."""

    tags: list[PredictedTag] = Field(default_factory=list)
    """Tags of the prediction."""


class ClipPredictionTag(BaseSchema):
    """Schema for a clip prediction tag."""

    tag: Tag
    """Tag of the prediction."""

    score: float
    """Confidence of the prediction."""


class ClipPrediction(BaseSchema):
    """Schema for a clip prediction."""

    uuid: UUID
    """UUID of the prediction."""

    id: int = Field(..., exclude=True)
    """Database ID of the prediction."""

    clip: Clip
    """Clip to which this prediction belongs."""

    sound_events: list[SoundEventPrediction] = Field(default_factory=list)
    """Sound event predictions of the clip."""

    tags: list[ClipPredictionTag] = Field(default_factory=list)
    """Tags of the prediction."""


class ClipPredictionUpdate(BaseModel):
    """Schema for updating a clip prediction."""

    uuid: UUID | None = None
    """UUID of the prediction."""
