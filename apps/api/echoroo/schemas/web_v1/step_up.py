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

from pydantic import UUID4, BaseModel, ConfigDict, Field

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
    factors_required: list[Literal["password", "totp"]] = Field(
        ...,
        description=(
            "Ordered list of factors the caller must supply in the "
            "matching ``complete`` request. ``password`` is always "
            "first; the second factor is ``totp``. This release does "
            "not advertise WebAuthn here — see the matching note on "
            "the contract YAML — and the begin handler refuses "
            "WebAuthn-only callers with a 409."
        ),
    )


class StepUpCompleteFactorsTotp(BaseModel):
    """Password + TOTP factor payload for ``complete``.

    This release supports only the TOTP shape; the WebAuthn variant has
    been removed from the contract YAML (initial release) and will be
    re-introduced under a separate task / spec. Submitting unknown keys
    is rejected with a 422 (``extra="forbid"``).
    """

    model_config = ConfigDict(extra="forbid")

    password: str = Field(..., min_length=1, max_length=4096)
    totp_code: str = Field(..., min_length=6, max_length=6)


class StepUpCompleteRequest(BaseModel):
    """Request body for ``POST /web-api/v1/auth/step-up/complete``."""

    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID4 = Field(
        ...,
        description=(
            "``challenge_id`` (UUID4) returned by the matching begin "
            "call. Strict UUID4 validation rejects malformed values "
            "with 422 before the handler runs — defence in depth "
            "against probing callers that could otherwise spam Redis "
            "with arbitrary keys."
        ),
    )
    factors: StepUpCompleteFactorsTotp = Field(
        ...,
        description=(
            "Authentication factors. TOTP-only for the initial release; "
            "WebAuthn step-up is planned as a follow-up spec."
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
