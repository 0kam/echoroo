"""Admin request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from echoroo.models.enums import ProjectMemberRole
from echoroo.schemas.auth import UserResponse


class AdminUserListResponse(BaseModel):
    """Admin user list response with pagination."""

    items: list[UserResponse] = Field(..., description="List of users")
    total: int = Field(..., description="Total number of users matching the filters")
    page: int = Field(..., description="Current page number")
    limit: int = Field(..., description="Number of items per page")


class AdminUserUpdateRequest(BaseModel):
    """Admin request to update user status."""

    is_active: bool | None = Field(None, description="Whether the user account is active")
    is_superuser: bool | None = Field(None, description="Whether the user is a superuser")
    is_verified: bool | None = Field(None, description="Whether the user's email is verified")


class SystemSettingResponse(BaseModel):
    """System setting response schema.

    Phase 13 P1 (T803a): values are now stored as native JSONB; the legacy
    ``value_type`` and ``description`` fields are retired. ``value_type``
    is preserved as a derived response field for backwards compatibility
    with existing admin UI clients (computed from the runtime Python type
    of ``value``).
    """

    key: str = Field(..., description="Setting key")
    value: str | int | float | bool | dict[str, object] | list[object] | None = Field(
        ..., description="Setting value (native JSONB)"
    )
    value_type: str = Field(
        ...,
        description=(
            "Derived value type label (string, number, boolean, json, null) — "
            "computed from the runtime type of ``value`` for UI compatibility"
        ),
    )
    updated_at: datetime = Field(..., description="Last update timestamp")


class SystemSettingsUpdateRequest(BaseModel):
    """System settings update request schema."""

    registration_mode: Literal["open", "invitation"] | None = Field(
        None, description="Registration mode (open or invitation-only)"
    )
    allow_registration: bool | None = Field(
        None, description="Whether new user registration is allowed"
    )
    session_timeout_minutes: int | None = Field(
        None, ge=5, le=1440, description="Session timeout in minutes (5-1440)"
    )
    birdnet_species_filter: Literal["none", "birdnet_geo"] | None = Field(
        None, description="BirdNET species filter mode (none or birdnet_geo)"
    )
    birdnet_min_conf: float | None = Field(
        None, ge=0.0, le=1.0, description="BirdNET minimum confidence threshold (0.0-1.0)"
    )


# =============================================================================
# Phase 11 / T630 — superuser looser-override approval workflow (FR-034 / FR-111)
# =============================================================================


class TaxonOverrideRejectRequest(BaseModel):
    """Body for ``POST /admin/projects/{id}/taxon-overrides/{overrideId}/reject``.

    The free-form ``reason`` is stored on the override row (``rejected_reason``)
    and copied into the platform audit log so the rejecting superuser leaves a
    durable explanation alongside the ``superuser_approval_requests`` ticket
    closure.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        ...,
        min_length=1,
        max_length=2_000,
        description=(
            "Why the looser override was rejected. Stored verbatim on the "
            "override row (FR-034) and embedded into the audit detail."
        ),
    )


class TaxonOverrideResponse(BaseModel):
    """Snapshot of a :class:`ProjectTaxonSensitivityOverride` row.

    Returned by the approve / reject endpoints so the admin UI can refresh
    the row without an extra round-trip. Mirrors the columns surfaced in
    ``contracts/admin.yaml`` (FR-034); fields not relevant to the Web UI
    (``requested_by_id``, audit trail) are intentionally omitted.
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID = Field(..., description="Override row identifier")
    project_id: UUID = Field(..., description="Owning project (FR-033)")
    taxon_id: str = Field(..., description="GBIF species key targeted by the override")
    sensitivity_h3_res: int = Field(
        ...,
        description="H3 resolution applied when masking — must be one of {2, 5, 7, 9, 15}",
    )
    direction: str = Field(
        ...,
        description="``'stricter'`` (auto-applied) or ``'looser'`` (approval workflow)",
    )
    approval_status: str = Field(
        ...,
        description=(
            "Current state in the FR-034 approval state machine: "
            "``'applied'`` / ``'pending_superuser_approval'`` / ``'rejected'``"
        ),
    )
    approved_by_id: UUID | None = Field(
        default=None,
        description="Superuser id that approved the looser override (NULL otherwise)",
    )
    approved_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the approval decision (NULL when not yet applied)",
    )
    rejected_reason: str | None = Field(
        default=None,
        description="Free-form reason recorded when the override was rejected",
    )


# =============================================================================
# Phase 12 / T702 — superuser archive / restore endpoints (FR-061 / FR-062)
# =============================================================================


class ArchiveRequest(BaseModel):
    """Body for ``POST /admin/projects/{project_id}/archive`` (FR-061).

    The free-form ``reason`` is recorded on both ``project_audit_log`` and
    ``platform_audit_log`` so the archiving superuser leaves a durable
    explanation. The endpoint flips the project to ``ProjectStatus.ARCHIVED``
    and stamps ``archived_since``; subsequent state-changing actions are
    blocked by Step 1 of :func:`echoroo.core.permissions.is_allowed`.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        ...,
        min_length=1,
        max_length=2_000,
        description=(
            "Why the project is being archived (operator-supplied). Stored "
            "verbatim in audit detail (project + platform tables, FR-088 / "
            "FR-089)."
        ),
    )


class ArchiveResponse(BaseModel):
    """Snapshot of the archived project returned to the superuser UI."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID = Field(..., description="Project identifier")
    status: str = Field(
        ..., description="Project lifecycle status — always ``'archived'`` here"
    )
    archived_since: datetime = Field(
        ..., description="UTC timestamp at which the project was archived"
    )


class RestoreMember(BaseModel):
    """Single entry in ``RestoreRequest.restored_members`` (FR-062).

    Each entry names a previously-removed user and the role to restore them
    with. ``ProjectMemberRole`` covers ``viewer`` / ``member`` / ``admin``;
    Owner is conveyed by the top-level ``new_owner_user_id`` field. The
    role enum is re-exported here so the FastAPI schema validates each
    entry without an extra Literal narrow.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID = Field(..., description="User to restore as a project member")
    role: ProjectMemberRole = Field(
        ...,
        description="Role to grant on restore (viewer / member / admin)",
    )


class RestoreRequest(BaseModel):
    """Body for ``POST /admin/projects/{project_id}/restore`` (FR-062).

    Superuser restores an archived project by nominating a new Owner and
    optionally resurrecting old members under operator-chosen roles. Members
    not present in ``restored_members`` are left with ``removed_at`` set;
    the endpoint does not flip those rows back automatically.
    """

    model_config = ConfigDict(extra="forbid")

    new_owner_user_id: UUID = Field(
        ...,
        description=(
            "User who becomes the new Owner of the restored project. Must "
            "exist in ``users`` (active, not soft-deleted)."
        ),
    )
    restored_members: list[RestoreMember] = Field(
        default_factory=list,
        description=(
            "Previously-removed members to restore; each entry is upserted "
            "into ``project_members`` with ``removed_at = NULL`` and the "
            "supplied role."
        ),
    )


class RestoreResponse(BaseModel):
    """Snapshot of the restored project returned to the superuser UI."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID = Field(..., description="Project identifier")
    status: str = Field(
        ..., description="Project lifecycle status — always ``'active'`` here"
    )
    owner_id: UUID = Field(..., description="New Owner user identifier")
    restored_member_count: int = Field(
        ...,
        description="Number of project_members rows resurrected by this call",
    )


class IucnForceResyncResponse(BaseModel):
    """Body for ``POST /admin/iucn/force-resync`` (FR-036).

    The endpoint is fire-and-forget: it enqueues a Celery task and returns
    the task id so the operator can correlate the request with the
    ``IucnSyncAttempt`` row that the worker creates a moment later.
    """

    model_config = ConfigDict(frozen=True)

    task_id: str = Field(
        ..., description="Celery task id of the queued ``sync_iucn_red_list`` job"
    )
    enqueued_at: datetime = Field(
        ...,
        description="UTC timestamp at which the admin endpoint dispatched the task",
    )
