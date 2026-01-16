"""API token request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class APITokenCreateRequest(BaseModel):
    """Request schema for creating an API token."""

    name: str = Field(
        ...,
        max_length=100,
        description="Human-readable name for the token",
    )
    expires_at: datetime | None = Field(
        None,
        description="Optional expiration timestamp",
    )


class APITokenResponse(BaseModel):
    """Response schema for API token (without token value)."""

    id: UUID
    name: str
    last_used_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class APITokenCreateResponse(APITokenResponse):
    """Response schema for created API token (includes plain text token).

    The token field is only included when creating a new token.
    It is shown only once and cannot be retrieved again.
    """

    token: str = Field(
        ...,
        description="Plain text token (shown only once)",
    )
