"""User profile request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class UserResponse(BaseModel):
    """User profile response schema."""

    id: UUID
    email: str
    display_name: str | None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    two_factor_enabled: bool

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    """User profile update request schema."""

    display_name: str | None = Field(None, max_length=100, description="Display name")


class PasswordChangeRequest(BaseModel):
    """Password change request schema."""

    current_password: str = Field(..., max_length=128, description="Current password (max 128 chars)")
    new_password: str = Field(
        ..., min_length=8, max_length=128, description="New password (min 8 chars, max 128 chars)"
    )

    @field_validator("new_password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        """Validate password complexity requirements."""
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number")
        return v


class PasswordChangeResponse(BaseModel):
    """Password change response schema."""

    message: str = Field(default="Password changed successfully")
