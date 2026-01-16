"""Admin request and response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from echoroo.schemas.auth import UserResponse


class AdminUserListResponse(BaseModel):
    """Admin user list response with pagination."""

    items: list[UserResponse] = Field(..., description="List of users")
    total: int = Field(..., description="Total number of users matching the filters")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Number of items per page")


class AdminUserUpdateRequest(BaseModel):
    """Admin request to update user status."""

    is_active: bool | None = Field(None, description="Whether the user account is active")
    is_superuser: bool | None = Field(None, description="Whether the user is a superuser")
    is_verified: bool | None = Field(None, description="Whether the user's email is verified")


class SystemSettingResponse(BaseModel):
    """System setting response schema."""

    key: str = Field(..., description="Setting key")
    value: str | int | bool | dict[str, object] = Field(..., description="Setting value")
    value_type: str = Field(..., description="Value type (string, number, boolean, json)")
    description: str | None = Field(None, description="Setting description")
    updated_at: datetime = Field(..., description="Last update timestamp")


class SystemSettingsUpdateRequest(BaseModel):
    """System settings update request schema."""

    registration_mode: Literal["open", "invitation"] | None = Field(
        None, description="Registration mode (open or invitation-only)"
    )
    allow_registration: bool | None = Field(
        None, description="Whether new user registration is allowed"
    )
    session_timeout_minutes: int | None = Field(
        None, ge=5, le=1440, description="Session timeout in minutes (5-1440)"
    )
