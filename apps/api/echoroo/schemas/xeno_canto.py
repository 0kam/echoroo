"""Xeno-canto API response schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class XenoCantoRecording(BaseModel):
    """A single recording from Xeno-canto."""

    xc_id: str = Field(..., description="Xeno-canto recording ID (e.g. '1065457')")
    scientific_name: str = Field(..., description="Scientific name of the species")
    common_name: str = Field(..., description="English common name of the species")
    recordist: str = Field(..., description="Name of the recordist")
    country: str = Field(..., description="Country where the recording was made")
    location: str = Field(..., description="Specific location of the recording")
    latitude: float | None = Field(default=None, description="GPS latitude of the recording site")
    longitude: float | None = Field(default=None, description="GPS longitude of the recording site")
    recording_type: str = Field(..., description="Type of recording (song, call, alarm call, etc.)")
    quality: str = Field(..., description="Quality rating A (best) through E (worst)")
    length: str = Field(..., description="Duration of the recording in MM:SS format")
    date: str = Field(..., description="Date of the recording (YYYY-MM-DD)")
    file_url: str = Field(..., description="Direct download URL for the audio file")
    sonogram_url: str | None = Field(default=None, description="URL of the spectrogram image")
    license: str = Field(..., description="Creative Commons license URL")


class XenoCantoSearchResponse(BaseModel):
    """Response schema for a Xeno-canto recording search."""

    total_recordings: int = Field(..., description="Total number of recordings matching the query")
    total_species: int = Field(..., description="Number of distinct species in the results")
    page: int = Field(..., description="Current page number (1-indexed)")
    total_pages: int = Field(..., description="Total number of result pages")
    recordings: list[XenoCantoRecording] = Field(
        ..., description="Recordings for the current page"
    )
