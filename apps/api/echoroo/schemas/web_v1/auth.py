"""First-party authentication request / response schemas."""

from __future__ import annotations

from typing import Any, Literal
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


class TotpSetupRequest(BaseModel):
    """Request body for beginning TOTP enrollment after password verification."""

    model_config = ConfigDict(extra="forbid")

    interim_token: str


class TotpSetupResponse(BaseModel):
    """TOTP enrollment artifacts shown once to the user."""

    model_config = ConfigDict(extra="forbid")

    secret: str
    provisioning_uri: str
    issuer: str
    account_name: str
    next_interim_token: str


class TotpSetupConfirmRequest(BaseModel):
    """Request body for confirming first-login TOTP enrollment."""

    model_config = ConfigDict(extra="forbid")

    interim_token: str
    secret: str
    totp_code: str


class TotpSetupConfirmResponse(BaseModel):
    """Response body after TOTP enrollment succeeds and a session is issued."""

    model_config = ConfigDict(extra="forbid")

    backup_codes: list[str]
    access_token: str
    expires_in: int


class TwoFactorChallengeRequest(BaseModel):
    """Request body for completing an existing user's 2FA challenge."""

    model_config = ConfigDict(extra="forbid")

    interim_token: str
    method: Literal["totp", "backup_code"]
    code: str


class TwoFactorChallengeResponse(BaseModel):
    """Response body after 2FA challenge succeeds and a session is issued."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    expires_in: int


class WebAuthnRegisterRequest(BaseModel):
    """Request body for beginning or completing WebAuthn registration."""

    model_config = ConfigDict(extra="forbid")

    interim_token: str
    credential: dict[str, Any] | None = None
    name: str | None = None


class WebAuthnRegisterBeginResponse(BaseModel):
    """WebAuthn registration options and next one-time interim token."""

    model_config = ConfigDict(extra="forbid")

    options: dict[str, Any]
    next_interim_token: str


class WebAuthnRegisterCompleteResponse(BaseModel):
    """Persisted WebAuthn credential metadata."""

    model_config = ConfigDict(extra="forbid")

    credential_id: str
    name: str
    registered_at: str


class WebAuthnChallengeRequest(BaseModel):
    """Request body for beginning or completing WebAuthn authentication."""

    model_config = ConfigDict(extra="forbid")

    interim_token: str
    credential: dict[str, Any] | None = None


class WebAuthnChallengeBeginResponse(BaseModel):
    """WebAuthn authentication options and next one-time interim token."""

    model_config = ConfigDict(extra="forbid")

    options: dict[str, Any]
    next_interim_token: str


class WebAuthnChallengeCompleteResponse(BaseModel):
    """Response body after WebAuthn authentication issues a session."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    expires_in: int
