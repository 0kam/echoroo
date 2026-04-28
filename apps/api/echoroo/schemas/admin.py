"""Admin request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    """System setting response schema."""

    key: str = Field(..., description="Setting key")
    value: str | int | float | bool | dict[str, object] = Field(..., description="Setting value")
    value_type: str = Field(..., description="Value type (string, number, boolean, json)")
    description: str | None = Field(None, description="Setting description")
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
