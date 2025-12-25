"""Schemas for species filtering functionality."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "SpeciesFilter",
    "SpeciesFilterApplication",
    "SpeciesFilterApplicationCreate",
    "SpeciesFilterApplicationProgress",
    "SpeciesFilterApplicationStatus",
    "SpeciesFilterType",
]


class SpeciesFilterType(str, Enum):
    """Type of species filter."""

    GEOGRAPHIC = "geographic"
    OCCURRENCE = "occurrence"
    CUSTOM = "custom"


class SpeciesFilterApplicationStatus(str, Enum):
    """Status of species filter application."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SpeciesFilter(BaseModel):
    """Available species filter."""

    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    slug: str
    display_name: str
    provider: str
    version: str
    description: str | None = None
    filter_type: SpeciesFilterType
    default_threshold: float = 0.03
    requires_location: bool = True
    requires_date: bool = True
    is_active: bool = True


class SpeciesFilterApplicationCreate(BaseModel):
    """Request to apply a species filter."""

    filter_slug: str
    threshold: float = Field(default=0.03, ge=0.0, le=1.0)
    apply_to_all_detections: bool = True


class SpeciesFilterApplication(BaseModel):
    """Filter application result."""

    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    species_filter: SpeciesFilter | None = None
    threshold: float
    apply_to_all_detections: bool = True
    status: SpeciesFilterApplicationStatus = SpeciesFilterApplicationStatus.PENDING
    progress: float = 0.0
    total_detections: int = 0
    filtered_detections: int = 0
    excluded_detections: int = 0
    started_on: datetime | None = None
    completed_on: datetime | None = None
    error: dict | None = None


class SpeciesFilterApplicationProgress(BaseModel):
    """Progress of filter application."""

    uuid: UUID
    status: SpeciesFilterApplicationStatus
    progress: float
    total_detections: int
    filtered_detections: int
    excluded_detections: int
