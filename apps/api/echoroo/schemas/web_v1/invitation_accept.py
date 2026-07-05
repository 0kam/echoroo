"""Public invitation resolve / accept schemas (spec/011, FR-011-105/106/107).

Request / response bodies for the public ``/web-api/v1/auth/invitations``
resolver and accept endpoints (mirror ``contracts/invitation-public.yaml``).
Extracted from :mod:`echoroo.api.web_v1.auth` so the large auth router
keeps only its handlers.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class InvitationContextResponse(BaseModel):
    """``GET /auth/invitations/{token}`` 200 body (FR-011-105)."""

    model_config = ConfigDict(extra="forbid")

    project_name: str
    role: str | None = Field(
        default=None,
        description=(
            "Project role (Member-kind) — Viewer / Member / Admin. NULL "
            "for trusted-overlay rows."
        ),
    )
    kind: str = Field(
        ...,
        description="``member`` or ``trusted``.",
    )
    bound_email: str | None = Field(
        default=None,
        description=(
            "Bound recipient email for the signup form prefill. "
            "**spec/011 step 7 R1 P0-4**: surfaced ONLY when the caller "
            "is anonymous (signup branch needs the email for the "
            "read-only form field) OR when the caller is authenticated "
            "AND ``authenticated_email_matches_bound`` is ``true`` "
            "(they already know their own email). When the caller is "
            "authenticated as a DIFFERENT user, this field is "
            "``null`` — never leak the bound recipient identity to a "
            "wrong-account session, which would convert the resolver "
            "into an email-of-invitee oracle for anyone holding a "
            "leaked invitation URL. The hashed counterpart "
            "``bound_email_hash`` is intentionally NOT surfaced by the "
            "public resolver: it lives in the admin listing endpoint "
            "only, where the caller has already passed the "
            "``MANAGE_MEMBERS`` gate."
        ),
    )
    expires_at: datetime
    is_bootstrap: bool = Field(
        default=False,
        description=(
            "True when ``ownership_transfer_on_accept`` is set (SU bootstrap)."
        ),
    )
    is_logged_in: bool
    authenticated_email_matches_bound: bool


class _AcceptTotpEnrollment(BaseModel):
    """Initial TOTP enrollment payload for the signup branch."""

    model_config = ConfigDict(extra="forbid")

    totp_secret_signed: str = Field(
        ...,
        description=(
            "Server-issued TOTP secret returned by the public-signup TOTP "
            "begin step. For spec/011 step 7 this is accepted as the "
            "plain TOTP secret string; a future revision MAY wrap it in "
            "an HMAC envelope without breaking the contract field name."
        ),
    )
    totp_initial_code: str = Field(..., min_length=6, max_length=6)


class _AcceptNewUserPayload(BaseModel):
    """New-user signup branch (FR-011-106 step 1a)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(
        ...,
        description=(
            "MUST canonicalize-equal the bound email. Mismatch → generic "
            "404 (no leak)."
        ),
    )
    password: str = Field(..., min_length=12)
    totp_enrollment: _AcceptTotpEnrollment


class _AcceptExistingUserPayload(BaseModel):
    """Existing-user accept branch (FR-011-106 step 1b)."""

    model_config = ConfigDict(extra="forbid")

    accept: bool = Field(
        ...,
        description=(
            "MUST be ``true``. The single field exists only as a guard so "
            "a misconfigured client cannot send an empty body and trip the "
            "signup branch by accident."
        ),
    )


class InvitationAcceptResponse(BaseModel):
    """``POST /auth/invitations/{token}/accept`` 201 body (FR-011-106)."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    role: str | None = None
    kind: str
    ownership_transferred: bool = False
    membership_created: bool


__all__ = [
    "InvitationAcceptResponse",
    "InvitationContextResponse",
    "_AcceptExistingUserPayload",
    "_AcceptNewUserPayload",
    "_AcceptTotpEnrollment",
]
