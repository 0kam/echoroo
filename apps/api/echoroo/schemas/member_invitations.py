"""Pydantic v2 schemas for the spec/011 Member-kind invitation surface (T200/T201).

Contract: ``specs/011-zero-email-deployment/contracts/member-invitations.yaml``.

Spec references:
    FR-011-101  POST issue endpoint.
    FR-011-102  Response shape with ``invitation_url`` + cache headers.
    FR-011-108  GET list extension to include ``kind=member`` rows.

The ``ProjectMemberInvitationRole`` Literal mirrors the contract YAML
enum exactly (``viewer|member|admin``) so the generated OpenAPI rejects
malformed payloads before they reach the service layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from echoroo.core.operator_pii_detector import reject_if_pii
from echoroo.models.enums import (
    ProjectInvitationKind,
    ProjectInvitationStatus,
    ProjectMemberRole,
)

ProjectMemberInvitationRole = Literal["viewer", "member", "admin"]
"""Role enum lifted from contract YAML — mirrors :class:`ProjectMemberRole`."""


class MemberInvitationIssueRequest(BaseModel):
    """``POST /projects/{project_id}/invitations`` request body (T200).

    spec/011 FR-011-101: no ``ttl_seconds`` override — the 7-day TTL is
    fixed at the service layer. ``role`` is the new member's role on the
    project (Viewer / Member / Admin per the canonical matrix).
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(
        ...,
        description=(
            "Bound recipient address; NFKC-normalised + casefolded before "
            "storage per FR-054 / FR-011-106."
        ),
    )
    role: ProjectMemberInvitationRole = Field(
        ...,
        description="Project role to grant on accept (FR-011-101).",
    )


class MemberInvitationIssueResponse(BaseModel):
    """``POST /projects/{project_id}/invitations`` 201 response (T200, FR-011-102).

    The handler MUST attach
    ``Cache-Control: no-store, no-cache, must-revalidate, private`` so
    the one-shot URL is never replayed from bfcache or a shared proxy.
    The ``invitation_url`` is never recoverable past this single HTTP
    turn — admins must revoke + reissue if they lose it. Telemetry /
    access-log pipelines MUST scrub this field per FR-011-102.
    """

    model_config = ConfigDict(extra="forbid")

    invitation_id: UUID
    invitation_url: str = Field(
        ...,
        description=(
            "One-shot 4-part signed envelope (spec/011 NFR-011-010). "
            "Display once to the issuing admin; MUST NOT appear in "
            "access logs or telemetry."
        ),
    )
    expires_at: datetime
    bound_email_hash: str = Field(
        ...,
        description=(
            "Hex digest of the canonicalised email (FR-055 enumeration "
            "mitigation; FR-011-102 audit reference)."
        ),
    )


class ProjectInvitationListItem(BaseModel):
    """Single row in the unified invitation listing (T201, FR-011-108).

    Returned by ``GET /projects/{project_id}/invitations``. Includes BOTH
    ``kind=member`` and ``kind=trusted`` rows alongside one another so
    the existing collaborator UI can render a single mixed table.
    ``role`` is non-NULL on member rows; ``granted_permissions`` is
    non-NULL on trusted rows. Both fields ride together in the row so
    the frontend can branch on ``kind``.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: ProjectInvitationKind
    role: ProjectMemberRole | None = None
    granted_permissions: list[str] | None = None
    status: ProjectInvitationStatus
    bound_email: str | None = Field(
        default=None,
        description=(
            "Plaintext bound email IF retained on the row (operator "
            "readability). Lookups go via the email_hash; this column "
            "may be NULL on legacy rows."
        ),
    )
    issued_by: UUID
    issued_at: datetime
    expires_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    declined_at: datetime | None = None
    ownership_transfer_on_accept: bool = False


class ProjectInvitationListResponse(BaseModel):
    """``GET /projects/{project_id}/invitations`` response shape (T201)."""

    model_config = ConfigDict(extra="forbid")

    items: list[ProjectInvitationListItem]


# ---------------------------------------------------------------------------
# spec/011 Step 8 (T260..T264) — Bulk invitation request / per-row result
# ---------------------------------------------------------------------------


BulkInvitationRowStatus = Literal[
    "issued",
    "duplicate_pending",
    "already_member",
    "rate_limited",
    "internal_error",
]
"""Per-row outcome enum surfaced in :class:`BulkInvitationResultItem.status`.

Distinct from the contract YAML's narrower
``[issued | duplicate_pending | rate_limited | error]`` set: the live shape
uses ``internal_error`` so an operator scanning the response can tell a
malformed-input cause from a per-row infra fault, and ``already_member``
(preview issue #4) so a row whose recipient already holds an active
membership is reported distinctly from a ``duplicate_pending`` row (a
pending invitation that has not yet been accepted). Both shapes are subset-
asserted by ``tests/contract/test_openapi_diff.py`` (FR-011-113).
"""


class BulkInvitationRequest(BaseModel):
    """``POST /projects/{project_id}/invitations/bulk`` body (FR-011-110).

    Per FR-011-110 the operator submits a single role + up to 50 emails;
    the per-row outcome rides on the response array. ``emails`` is enforced
    at the Pydantic layer (``min_length=1``, ``max_length=50``) so malformed
    sizes are rejected with HTTP 422 before any SAVEPOINT loop runs.
    """

    model_config = ConfigDict(extra="forbid")

    role: ProjectMemberInvitationRole = Field(
        ...,
        description="Single role applied to every issued invitation (FR-011-110).",
    )
    emails: list[EmailStr] = Field(
        ...,
        min_length=1,
        max_length=50,
        description=(
            "Recipient list (NFKC + casefolded before storage, FR-011-111). "
            "Maximum 50 entries (FR-011-115). All-or-nothing validation rejects "
            "the entire request on a single malformed email OR an in-list "
            "duplicate (FR-011-111)."
        ),
    )


class BulkInvitationResultItem(BaseModel):
    """One per-row outcome from :class:`BulkInvitationRequest` (FR-011-113).

    ``invitation_url`` and ``invitation_id`` are populated ONLY for rows
    whose ``status='issued'``. ``error_message`` is populated for the
    ``rate_limited`` and ``internal_error`` rows so the operator can
    surface a contextual reason without leaking row-internal stack traces.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(
        ...,
        description="Original submission email (NOT canonicalised — operator-readable).",
    )
    status: BulkInvitationRowStatus = Field(
        ...,
        description="Per-row outcome discriminator (FR-011-113).",
    )
    invitation_id: UUID | None = Field(
        default=None,
        description="Issued invitation id; populated only when ``status='issued'``.",
    )
    invitation_url: str | None = Field(
        default=None,
        description=(
            "One-shot signed envelope (spec/011 NFR-011-010); populated only "
            "when ``status='issued'``. MUST NOT appear in access logs or "
            "telemetry (FR-011-102)."
        ),
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Invitation expiry; populated only when ``status='issued'``.",
    )
    error_message: str | None = Field(
        default=None,
        description=(
            "Short human-readable reason for non-issued rows. Never carries "
            "stack traces or invitation row internals."
        ),
    )


# ---------------------------------------------------------------------------
# spec/011 Step 8 — Revoke endpoint body
# ---------------------------------------------------------------------------


class InvitationRevokeRequest(BaseModel):
    """``POST /projects/{project_id}/invitations/{invitation_id}/revoke`` body.

    ``reason`` is an OPTIONAL free-form operator note. The Phase 17 A-13
    PII detector (:func:`reject_if_pii`) rejects any payload carrying
    email / phone / national identifier patterns BEFORE the audit row
    persists.

    spec/011 Step 8 R1 P1-2: the 500-character cap matches the contract
    YAML's ``maxLength: 500`` and follows the
    :class:`schemas.admin.AdminPasswordResetBody.reason` precedent
    (Step 5). The dedicated cap is intentionally distinct from the
    canonical :data:`OperatorReasonText` 2000-char limit — the contract
    YAML is the source of truth and the revoke surface is bounded
    tighter.
    """

    model_config = ConfigDict(extra="forbid")

    reason: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
            description=(
                "Operator-supplied free-form reason. MUST NOT contain "
                "PII (email, phone, national identifier, credit card, "
                "API tokens). Validated server-side (Phase 17 A-13) — "
                "submitting PII yields HTTP 422."
            ),
        ),
        AfterValidator(reject_if_pii),
    ] | None = Field(
        default=None,
        description=(
            "Optional free-form rationale recorded in the audit detail. "
            "Persisted into the post-commit ``project.invitation.revoke`` "
            "audit row only; the ``project_invitations`` table itself "
            "does not currently carry a ``revoked_reason`` column."
        ),
    )


__all__ = [
    "BulkInvitationRequest",
    "BulkInvitationResultItem",
    "BulkInvitationRowStatus",
    "InvitationRevokeRequest",
    "MemberInvitationIssueRequest",
    "MemberInvitationIssueResponse",
    "ProjectInvitationListItem",
    "ProjectInvitationListResponse",
    "ProjectMemberInvitationRole",
]
