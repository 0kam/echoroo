"""Pydantic v2 schemas for the Trusted User overlay endpoints (T510).

Contract: ``specs/006-permissions-redesign/contracts/trusted.yaml``.

Spec references (Rev.3.2):
    FR-012  — TRUSTED_ALLOWED_PERMISSIONS allowlist (8 entries).
    FR-014  — runtime allowlist intersection.
    FR-041 / FR-043  — Trusted overlay row, expiry bound by ``granted_at + 1y``.
    FR-046  — Owner may extend / revoke / edit granted_permissions.
    FR-050  — Web UI surface (Cookie + CSRF only).
    FR-051  — plain-text token confidentiality (the invite POST returns
        ``invitation_id`` ONLY — never the signed URL token).
    FR-052  — invitation lives at most 7 days.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from echoroo.models.enums import ProjectTrustedStatus

#: Phase 10 Batch 2 Round 2 fix (Major 2): the contract's enum-of-eight
#: matches :data:`echoroo.core.permissions.TRUSTED_ALLOWED_PERMISSIONS`
#: exactly. Pydantic surfaces the constraint in the generated OpenAPI
#: schema so the Web UI / SDKs cannot construct an invalid payload.
TrustedGrantedPermission = Literal[
    "view_media",
    "view_detection",
    "view_precise_location",
    "download",
    "export",
    "search_within_project",
    "vote",
    "comment",
]

#: Minimum acceptable Trusted overlay duration (1 second). The default in the
#: invitation service is 90 days; this lower bound only exists so a buggy
#: client cannot pass 0 / negative integers.
TRUSTED_MIN_DURATION_SECONDS: int = 1

#: Hard upper bound on Trusted overlay duration in seconds (FR-043: 1 year).
TRUSTED_MAX_DURATION_SECONDS: int = 365 * 24 * 3600


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class TrustedUserInviteRequest(BaseModel):
    """``POST /projects/{id}/trusted-users`` request body (Owner only).

    The ``granted_permissions`` array is intersected against
    :data:`echoroo.core.permissions.TRUSTED_ALLOWED_PERMISSIONS` inside the
    invitation service so manually-INSERTed values cannot escalate. The
    runtime safety net in :mod:`echoroo.core.permissions` filters again
    on every request (FR-014).
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(
        ...,
        description="Plain-text recipient email (NFKC + casefold normalised "
        "downstream for FR-054 match).",
    )
    granted_permissions: list[TrustedGrantedPermission] = Field(
        ...,
        min_length=1,
        description="Permission enum names to grant on accept; must be a "
        "non-empty subset of TRUSTED_ALLOWED_PERMISSIONS (FR-042).",
    )
    duration_seconds: int = Field(
        ...,
        ge=TRUSTED_MIN_DURATION_SECONDS,
        le=TRUSTED_MAX_DURATION_SECONDS,
        description="Validity window in seconds [1, 31_536_000] (FR-043).",
    )


class TrustedUserUpdateRequest(BaseModel):
    """``PATCH /projects/{id}/trusted-users/{trustedUserId}`` body (Owner only).

    All fields optional; an empty body is rejected at the endpoint layer
    (no-op PATCH ⇒ 422 to surface the misuse). ``expires_at`` and
    ``extension_seconds`` are mutually exclusive: pass one. ``granted_at + 1y``
    is the upper bound on either, enforced inside the trusted service.
    """

    model_config = ConfigDict(extra="forbid")

    expires_at: datetime | None = Field(
        default=None,
        description="Absolute new expiry (UTC). Must be in the future and "
        "≤ granted_at + 1 year (FR-043).",
    )
    extension_seconds: int | None = Field(
        default=None,
        ge=TRUSTED_MIN_DURATION_SECONDS,
        le=TRUSTED_MAX_DURATION_SECONDS,
        description="Convenience knob — extend the current expiry by N "
        "seconds. Mutually exclusive with ``expires_at``.",
    )
    granted_permissions: list[TrustedGrantedPermission] | None = Field(
        default=None,
        min_length=1,
        description="Replacement permission set; allowlist re-validated.",
    )


# ---------------------------------------------------------------------------
# Response bodies
# ---------------------------------------------------------------------------


class TrustedUserInviteResponse(BaseModel):
    """``POST /projects/{id}/trusted-users`` 202 response.

    spec/011 FR-011-103 (T207): the outbound-email enqueue is removed and
    the plain-text invitation envelope is surfaced directly on this
    response as ``invitation_url``. This formally supersedes spec/006
    FR-051 ("plain-text invitation tokens leave the process only through
    the post-commit email outbox"). The Owner MUST hand the URL off
    out-of-band — the value is one-shot, never persisted past this HTTP
    turn, and never recoverable through any other endpoint.

    The handler MUST attach
    ``Cache-Control: no-store, no-cache, must-revalidate, private`` so
    a browser back / refresh does not replay the URL from the
    bfcache (mirror of FR-011-102 on the Member endpoint).
    """

    model_config = ConfigDict(extra="forbid")

    invitation_id: UUID
    invitation_url: str = Field(
        ...,
        description=(
            "One-shot 4-part signed envelope (spec/011 NFR-011-010). "
            "Display once to the issuing Owner; MUST NOT appear in "
            "access logs or telemetry."
        ),
    )
    expires_at: datetime = Field(
        ...,
        description="Wall-clock instant after which the URL is rejected (UTC).",
    )


class TrustedUserResponse(BaseModel):
    """Single :class:`ProjectTrustedUser` row."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    project_id: UUID
    user_id: UUID
    invitation_id: UUID
    granted_by_id: UUID
    granted_at: datetime
    expires_at: datetime
    status: ProjectTrustedStatus
    granted_permissions: list[str]
    revoked_at: datetime | None = None


class TrustedUserListResponse(BaseModel):
    """``GET /projects/{id}/trusted-users`` response (Owner / Admin)."""

    model_config = ConfigDict(extra="forbid")

    items: list[TrustedUserResponse]
    total: int


__all__ = [
    "TRUSTED_MAX_DURATION_SECONDS",
    "TRUSTED_MIN_DURATION_SECONDS",
    "TrustedUserInviteRequest",
    "TrustedUserInviteResponse",
    "TrustedUserListResponse",
    "TrustedUserResponse",
    "TrustedUserUpdateRequest",
]
