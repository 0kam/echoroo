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
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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


__all__ = [
    "MemberInvitationIssueRequest",
    "MemberInvitationIssueResponse",
    "ProjectInvitationListItem",
    "ProjectInvitationListResponse",
    "ProjectMemberInvitationRole",
]
