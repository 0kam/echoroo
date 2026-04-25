"""First-party authentication request / response schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RegisterRequest(BaseModel):
    """Request body for ``POST /web-api/v1/auth/register``."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    display_name: str | None = None
    timezone: str | None = None


class RegisterResponse(BaseModel):
    """Registration response; first login must continue to 2FA setup."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    email: str
    two_factor_setup_required: bool = True


class LoginRequest(BaseModel):
    """Password credential request for the first step of login."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class LoginResponse(BaseModel):
    """Password-verified login state for T150b to complete."""

    model_config = ConfigDict(extra="forbid")

    login_state: str
    interim_token: str


class RefreshResponse(BaseModel):
    """Response body for rotated first-party session tokens."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    expires_in: int
