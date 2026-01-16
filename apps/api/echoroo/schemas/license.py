"""License request and response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class LicenseBase(BaseModel):
    """Base license schema with core fields."""

    id: str = Field(..., description="License identifier code (e.g., 'BY-NC-SA')", max_length=50)
    name: str = Field(..., description="Full license name", max_length=200)
    short_name: str = Field(..., description="Short license name", max_length=50)
    url: str | None = Field(None, description="URL to license text/details", max_length=500)
    description: str | None = Field(None, description="Detailed description of license terms")


class LicenseCreate(LicenseBase):
    """Schema for creating a new license."""

    pass


class LicenseUpdate(BaseModel):
    """Schema for updating an existing license."""

    name: str | None = Field(None, description="Full license name", max_length=200)
    short_name: str | None = Field(None, description="Short license name", max_length=50)
    url: str | None = Field(None, description="URL to license text/details", max_length=500)
    description: str | None = Field(None, description="Detailed description of license terms")


class LicenseResponse(LicenseBase):
    """License response schema with timestamps."""

    created_at: datetime = Field(..., description="License creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}


class LicenseListResponse(BaseModel):
    """License list response schema."""

    items: list[LicenseResponse] = Field(..., description="List of licenses")
