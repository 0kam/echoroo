"""Pydantic schemas for setup endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

SETUP_MIN_PASSWORD_LENGTH = 16


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
        password: Password (min 16 characters)
        display_name: Optional display name
    """

    email: EmailStr = Field(
        ...,
        description="Email address for the admin account",
        examples=["admin@example.com"],
    )
    password: str = Field(
        ...,
        min_length=SETUP_MIN_PASSWORD_LENGTH,
        description="Password with minimum 16 characters",
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

    spec/011 §FR-011-002 / Step 10 (T127): ``email_verified_at`` was
    removed alongside the dropped column; the schema no longer surfaces
    a verification timestamp because no automated verification exists
    in a zero-email deployment.

    Attributes:
        id: User UUID
        email: User email
        display_name: Display name
        two_factor_enabled: Whether 2FA is enabled for the user
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    id: UUID = Field(..., description="User unique identifier")
    email: str = Field(..., description="User email address")
    display_name: str | None = Field(None, description="Display name")
    two_factor_enabled: bool = Field(..., description="2FA enabled status")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    model_config = {"from_attributes": True}


class SetupCompleteResponse(BaseModel):
    """Response schema for successful setup initialization."""

    user: UserResponse = Field(..., description="Created bootstrap user")
    totp_secret_base32: str = Field(
        ...,
        description="Plain TOTP base32 secret shown once during setup",
    )
    totp_provisioning_uri: str = Field(
        ...,
        description="Authenticator provisioning URI for the bootstrap user",
    )
    bootstrap_token: str = Field(
        ...,
        description="One-time WebAuthn bootstrap token",
    )
    bootstrap_token_expires_at: datetime = Field(
        ...,
        description="Expiration timestamp for the bootstrap token",
    )
    webauthn_registration_url: str = Field(
        ...,
        description="Relative URL for WebAuthn credential registration",
    )
