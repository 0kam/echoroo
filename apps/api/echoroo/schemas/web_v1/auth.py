"""First-party authentication request / response schemas."""

from __future__ import annotations

import unicodedata
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from echoroo.core.text import has_control_chars


class RegisterRequest(BaseModel):
    """Request body for ``POST /web-api/v1/auth/register``."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str
    display_name: str | None = None
    timezone: str | None = None


class RegisterResponse(BaseModel):
    """Registration response; first login must continue to 2FA setup.

    spec/011 §FR-011-002 / FR-011-005 / Step 10 (T126): the
    ``email_verified_at`` + ``email_verification_required`` fields were
    removed alongside the email-verification subsystem. Frontend
    consumers branch on ``two_factor_setup_required`` only.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    email: str
    two_factor_setup_required: bool = True


# spec/011 Step 10 (T126) — ``EmailVerifyRequest`` / ``EmailVerifyResponse``
# / ``EmailVerificationResendRequest`` / ``EmailVerificationResendResponse``
# schemas were removed alongside the deleted ``/verify-email*`` endpoints
# (FR-011-005).


class LoginRequest(BaseModel):
    """Password credential request for the first step of login."""

    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class LoginResponse(BaseModel):
    """Password-verified login state, or complete trusted-device login."""

    model_config = ConfigDict(extra="forbid")

    login_state: Literal["2fa_setup_required", "2fa_required", "complete"]
    interim_token: str | None = None
    access_token: str | None = None
    expires_in: int | None = None
    trusted_device_used: bool | None = None

    @model_validator(mode="after")
    def validate_variant(self) -> LoginResponse:
        """Reject mixed interim/complete response shapes."""
        if self.login_state == "complete":
            if (
                self.interim_token is not None
                or self.access_token is None
                or self.expires_in is None
                or self.trusted_device_used is None
            ):
                raise ValueError("complete login response requires only session fields")
            return self

        if (
            self.interim_token is None
            or self.access_token is not None
            or self.expires_in is not None
            or self.trusted_device_used is not None
        ):
            raise ValueError("interim login response requires only interim_token")
        return self

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("exclude_none", True)
        dumped = super().model_dump(*args, **kwargs)
        assert isinstance(dumped, dict)
        return dumped


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
    trust_device: bool = False
    device_label: str | None = Field(default=None, max_length=100)


class TotpSetupConfirmResponse(BaseModel):
    """Response body after TOTP enrollment succeeds and a session is issued."""

    model_config = ConfigDict(extra="forbid")

    backup_codes: list[str]
    access_token: str
    expires_in: int
    trusted_device_created: bool = False


class TwoFactorChallengeRequest(BaseModel):
    """Request body for completing an existing user's 2FA challenge."""

    model_config = ConfigDict(extra="forbid")

    interim_token: str
    method: Literal["totp", "backup_code"]
    code: str
    trust_device: bool = False
    device_label: str | None = Field(default=None, max_length=100)


class TwoFactorChallengeResponse(BaseModel):
    """Response body after 2FA challenge succeeds and a session is issued."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    expires_in: int
    trusted_device_created: bool = False


class WebAuthnRegisterRequest(BaseModel):
    """Request body for beginning or completing WebAuthn registration."""

    model_config = ConfigDict(extra="forbid")

    interim_token: str
    credential: dict[str, Any] | None = None
    name: str | None = Field(default=None, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = unicodedata.normalize("NFKC", str(value))
        if has_control_chars(normalized):
            raise ValueError("name contains control characters")
        return normalized.strip()


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
    """Response body after WebAuthn authentication issues a session.

    Phase 16 Batch 6g-3: a successful assertion *also* produces a
    short-lived ``step_up_token`` bound to ``scope='admin_destructive'``
    so destructive admin endpoints can require a fresh hardware-key
    presence check via the ``X-Step-Up-Token`` header. ``expires_at`` is
    the absolute UTC ISO-8601 timestamp at which the token stops being
    accepted.
    """

    model_config = ConfigDict(extra="forbid")

    access_token: str
    expires_in: int
    step_up_token: str
    step_up_expires_at: str
    step_up_scope: str


# spec/011 §FR-011-005 / Step 10 (T126) — ``PasswordResetRequest`` and
# ``PasswordResetConfirmRequest`` were removed alongside the deleted
# self-service ``/password-reset/{request,confirm}`` endpoints. Password
# recovery is now admin-mediated (``services/admin_password_reset.py``).
