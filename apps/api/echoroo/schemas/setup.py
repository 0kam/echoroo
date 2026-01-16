"""Pydantic schemas for setup endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SetupStatusResponse(BaseModel):
    """Response schema for GET /setup/status.

    Attributes:
        setup_required: Whether initial setup is required
        setup_completed: Whether initial setup has been completed
    """

    setup_required: bool = Field(
        ...,
        description="True if no users exist and setup is required",
    )
    setup_completed: bool = Field(
        ...,
        description="True if initial setup has been completed",
    )


class SetupInitializeRequest(BaseModel):
    """Request schema for POST /setup/initialize.

    Attributes:
        email: Email address for the first admin user
        password: Password (min 8 characters)
        display_name: Optional display name
    """

    email: EmailStr = Field(
        ...,
        description="Email address for the admin account",
        examples=["admin@example.com"],
    )
    password: str = Field(
        ...,
        min_length=8,
        description="Password with minimum 8 characters",
        examples=["SecurePassword123!"],
    )
    display_name: str | None = Field(
        default=None,
        max_length=100,
        description="Optional display name",
        examples=["System Administrator"],
    )


class UserResponse(BaseModel):
    """Response schema for user data.

    Used when returning user information after setup.

    Attributes:
        id: User UUID
        email: User email
        display_name: Display name
        organization: Organization
        is_active: Active status
        is_superuser: Superuser status
        is_verified: Verification status
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    id: UUID = Field(..., description="User unique identifier")
    email: str = Field(..., description="User email address")
    display_name: str | None = Field(None, description="Display name")
    organization: str | None = Field(None, description="Organization")
    is_active: bool = Field(..., description="Account active status")
    is_superuser: bool = Field(..., description="Superuser flag")
    is_verified: bool = Field(..., description="Email verified status")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}
