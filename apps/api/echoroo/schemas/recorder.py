"""Recorder request and response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class RecorderBase(BaseModel):
    """Base recorder schema with common fields."""

    id: str = Field(..., description="Unique recorder identifier (e.g., 'am120')", max_length=50)
    manufacturer: str = Field(..., description="Manufacturer name", max_length=100)
    recorder_name: str = Field(..., description="Model or name of the recorder", max_length=100)
    version: str | None = Field(None, description="Optional version or revision number", max_length=50)


class RecorderCreate(RecorderBase):
    """Schema for creating a new recorder."""

    pass


class RecorderUpdate(BaseModel):
    """Schema for updating a recorder."""

    manufacturer: str | None = Field(None, description="Manufacturer name", max_length=100)
    recorder_name: str | None = Field(None, description="Model or name of the recorder", max_length=100)
    version: str | None = Field(None, description="Optional version or revision number", max_length=50)


class RecorderResponse(RecorderBase):
    """Schema for recorder response with timestamps."""

    created_at: datetime = Field(..., description="Record creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}


class RecorderListResponse(BaseModel):
    """Schema for paginated recorder list response."""

    items: list[RecorderResponse] = Field(..., description="List of recorders")
    total: int = Field(..., description="Total number of recorders")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Number of items per page")
