"""Schemas for detection visualization."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

__all__ = [
    "DetectionTemporalData",
    "SpeciesTemporalData",
    "HourlyDetection",
]


class HourlyDetection(BaseModel):
    """Detection count for a specific date and hour."""

    date: dt.date
    """The date of detections."""

    hour: int = Field(ge=0, le=23)
    """Hour of day (0-23)."""

    count: int
    """Number of detections in this hour."""


class SpeciesTemporalData(BaseModel):
    """Temporal detection data for a single species."""

    scientific_name: str
    """Scientific name of the species."""

    common_name: str | None = None
    """Common name (localized)."""

    total_detections: int
    """Total number of detections for this species."""

    detections: list[HourlyDetection]
    """List of hourly detection counts."""


class DetectionTemporalData(BaseModel):
    """Complete temporal data for all detected species."""

    run_uuid: str
    """Foundation model run UUID."""

    filter_application_uuid: str | None = None
    """Species filter application UUID if filtered."""

    date_range: tuple[dt.date, dt.date] | None = None
    """Date range of detections (min, max)."""

    species: list[SpeciesTemporalData]
    """Temporal data for each species."""
