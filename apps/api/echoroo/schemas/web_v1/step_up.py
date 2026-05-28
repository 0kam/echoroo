"""Step-up authentication request / response schemas (spec/011 T300/T301).

Models for ``POST /web-api/v1/auth/step-up/begin`` and
``POST /web-api/v1/auth/step-up/complete``. Lives in its own module so
the broader ``schemas/web_v1/auth.py`` stays focused on the password /
2FA / WebAuthn login surface — the step-up flow is a distinct
post-authentication primitive (FR-011-206).

Contract reference:
``specs/011-zero-email-deployment/contracts/admin-password-reset.yaml``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: ``scope`` values currently accepted by the begin endpoint. Mirrors
#: :data:`echoroo.services.step_up_token_service.SCOPE_ADMIN_RECOVERY`
#: literally — kept as a typing-only Literal so a future scope addition
#: (e.g. DSR export, audit-log purge) registers as a schema-level change.
StepUpScope = Literal["admin_recovery"]


class StepUpBeginRequest(BaseModel):
    """Request body for ``POST /web-api/v1/auth/step-up/begin``."""

    model_config = ConfigDict(extra="forbid")

    scope: StepUpScope = Field(
        ...,
        description=(
            "Operational scope of the step-up challenge. Currently only "
            "``admin_recovery`` (spec/011 FR-011-206) is wired."
        ),
    )


class StepUpBeginResponse(BaseModel):
    """Response body for ``POST /web-api/v1/auth/step-up/begin``.

    ``factors_required`` is derived server-side from the authenticated
    user's 2FA enrollment so a misconfigured frontend cannot bypass the
    second factor by hiding the UI prompt.
    """

    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(
        ...,
        description=(
            "Opaque correlator (UUID4) the frontend must echo back on "
            "the matching ``complete`` call."
        ),
    )
    factors_required: list[Literal["password", "totp", "webauthn"]] = Field(
        ...,
        description=(
            "Ordered list of factors the caller must supply in the "
            "matching ``complete`` request. ``password`` is always "
            "first; the second-factor value depends on the user's 2FA "
            "enrollment (TOTP or WebAuthn)."
        ),
    )


class StepUpCompleteFactorsTotp(BaseModel):
    """Password + TOTP factor payload for ``complete``.

    The contract YAML declares ``factors`` as a ``oneOf`` between the
    TOTP and WebAuthn shapes; the live implementation currently only
    wires the TOTP variant (spec/011 T300/T301). Submitting a
    WebAuthn-shaped payload is rejected by the handler with a 422 to
    keep the surface honest.
    """

    model_config = ConfigDict(extra="forbid")

    password: str = Field(..., min_length=1, max_length=4096)
    totp_code: str = Field(..., min_length=6, max_length=6)


class StepUpCompleteRequest(BaseModel):
    """Request body for ``POST /web-api/v1/auth/step-up/complete``."""

    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="``challenge_id`` returned by the matching begin call.",
    )
    factors: StepUpCompleteFactorsTotp = Field(
        ...,
        description=(
            "Authentication factors. Currently the TOTP shape is the "
            "only accepted variant — the WebAuthn variant declared in "
            "the contract YAML is reserved for a later step."
        ),
    )


class StepUpCompleteResponse(BaseModel):
    """Response body for ``POST /web-api/v1/auth/step-up/complete``."""

    model_config = ConfigDict(extra="forbid")

    step_up_token: str = Field(
        ...,
        description=(
            "Opaque JWT held in-memory by the frontend ONLY. Telemetry "
            "/ access logs scrub this field (spec/011 NFR-011-001)."
        ),
    )
    expires_at: str = Field(
        ...,
        description="Absolute UTC ISO-8601 expiry of the step-up token.",
    )
    scope_set: list[str] = Field(
        ...,
        description=(
            "Scopes the issued token covers. Always a single-element "
            "list mirroring the request's ``scope``."
        ),
    )


__all__ = [
    "StepUpBeginRequest",
    "StepUpBeginResponse",
    "StepUpCompleteFactorsTotp",
    "StepUpCompleteRequest",
    "StepUpCompleteResponse",
    "StepUpScope",
]
