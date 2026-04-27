"""Project request and response schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool

from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.schemas.auth import UserResponse


class PublicOwnerResponse(BaseModel):
    """Public-safe owner sub-object embedded in :class:`ProjectResponse`.

    FR-030 (Phase 5 polish round 2): ``ProjectResponse`` is reachable by Guest
    callers on Public + Active projects, so the embedded owner *must not* leak
    PII (``email``, ``last_login_at``, ``created_at`` etc.). The full
    :class:`UserResponse` is only safe inside authenticated, owner-scope
    surfaces (``/auth/me``, ``/web-api/v1/admin/users``).

    The shape deliberately mirrors what the Web UI needs for a "by <author>"
    byline — display name plus an opaque ID for navigation. Anything else
    (avatar URLs, profile bios, etc.) MUST be added here explicitly with
    a privacy review, not via field inheritance.
    """

    id: UUID
    display_name: str | None

    model_config = {"from_attributes": True}


class ProjectOverviewSite(BaseModel):
    """Site summary within project overview."""

    id: UUID
    name: str
    h3_index: str
    latitude: float | None
    longitude: float | None
    recording_count: int
    dataset_count: int


class RecordingCalendarEntry(BaseModel):
    """Monthly recording activity entry."""

    year: int
    month: int
    site_count: int
    recording_count: int


class ProjectOverviewResponse(BaseModel):
    """Project overview aggregated statistics."""

    sites: list[ProjectOverviewSite]
    recording_calendar: list[RecordingCalendarEntry]
    total_recordings: int
    total_sites: int
    total_duration: float


class ProjectCreateRequest(BaseModel):
    """Project creation request schema.

    Phase 7 / T320 (FR-085): ``license`` is **required** at creation time;
    omitting it is a 422 (``ERR_LICENSE_REQUIRED`` semantics) and unknown
    fields are rejected with 422 (``ERR_UNKNOWN_FIELD`` semantics) per
    contracts/projects.yaml ``ProjectCreateRequest``
    (``additionalProperties: false`` + ``required: [name, visibility, license]``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200, description="Project name")
    description: str | None = Field(None, description="Project description")
    # Phase 7 polish round 2 (Major 2): contract ``ProjectCreateRequest``
    # marks ``visibility`` as ``required`` (projects.yaml:408). A pydantic
    # default would silently fill the field on omission and emit 201 instead
    # of the contract-mandated 422, so the field is declared without a
    # default to match ``additionalProperties: false`` + ``required`` in the
    # OpenAPI shape.
    visibility: ProjectVisibility = Field(..., description="Project visibility level")
    license: ProjectLicense = Field(
        ...,
        description=(
            "Project data license — required at creation (FR-085). "
            "One of CC0 / CC-BY / CC-BY-NC / CC-BY-SA."
        ),
    )
    restricted_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Restricted visibility capability toggles",
    )


class ProjectUpdateRequest(BaseModel):
    """Project update request schema."""

    name: str | None = Field(None, min_length=1, max_length=200, description="Project name")
    description: str | None = Field(None, description="Project description")
    visibility: ProjectVisibility | None = Field(None, description="Project visibility level")
    license: ProjectLicense | None = Field(None, description="Project data license")
    restricted_config: dict[str, Any] | None = Field(
        None,
        description="Restricted visibility capability toggles",
    )
    status: ProjectStatus | None = Field(None, description="Project lifecycle status")


class ProjectResponse(BaseModel):
    """Project response schema."""

    id: UUID
    name: str
    description: str | None
    visibility: ProjectVisibility
    license: ProjectLicense
    restricted_config: dict[str, Any]
    restricted_config_version: int
    status: ProjectStatus
    dormant_since: datetime | None
    archived_since: datetime | None
    owner: PublicOwnerResponse
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """Project list response schema with pagination."""

    items: list[ProjectResponse]
    total: int
    page: int
    limit: int


class RestrictedConfigUpdateRequest(BaseModel):
    """Request body for ``PATCH /projects/{id}/restricted-config`` (FR-014/020-023).

    Contract: ``contracts/projects.yaml:174-197`` + the ``RestrictedConfig``
    schema at lines 430-454. All eight keys are required (no defaults at the
    request layer — defaults live on the model column for new projects only)
    and unknown keys are rejected with 422 per FR-023
    (``additionalProperties: false`` in the OpenAPI shape, ``Extra.forbid``
    here).

    Phase 8 / T400 invariants:

    * ``allow_media_playback`` / ``allow_detection_view`` /
      ``mask_species_in_detection`` / ``allow_download`` / ``allow_export`` /
      ``allow_voting_and_comments`` map directly onto the matching
      :class:`echoroo.models.project.Project.restricted_config` JSONB keys.
    * ``public_location_precision_h3_res`` is constrained to the discrete
      H3 resolutions in spec FR-021 (``Literal[2, 5, 7, 9, 15]``); any other
      integer is rejected at validation time so the service layer never
      receives a free-form value.
    * ``allow_precise_location_to_viewer`` is the FR-022 capability toggle
      that lifts ``VIEW_PRECISE_LOCATION`` for project Viewers when ``True``.
    """

    # Phase 8 polish round 2 Major 2 — use ``StrictBool`` for every bool
    # toggle so ``"true"`` / ``"false"`` / ``0`` / ``1`` strings are
    # rejected with 422 instead of silently coerced. Pydantic's default
    # ``bool`` is permissive (case-insensitive str -> bool, int -> bool)
    # which would let a buggy Web UI ship the wrong toggle state past the
    # contract; the spec FR-023 ``additionalProperties: false`` shape on
    # the OpenAPI side mandates strict JSON-typed values.
    model_config = ConfigDict(extra="forbid")

    allow_media_playback: StrictBool = Field(
        ...,
        description="Whether non-members may stream raw audio (FR-020).",
    )
    allow_detection_view: StrictBool = Field(
        ...,
        description="Whether non-members may read detection rows (FR-020).",
    )
    mask_species_in_detection: StrictBool = Field(
        ...,
        description=(
            "Mask species names in detection responses for non-members "
            "(FR-020 / response_filter)."
        ),
    )
    allow_download: StrictBool = Field(
        ...,
        description="Whether authenticated non-members may download (FR-020).",
    )
    allow_export: StrictBool = Field(
        ...,
        description="Whether authenticated non-members may CSV/ML-export (FR-020).",
    )
    allow_voting_and_comments: StrictBool = Field(
        ...,
        description=(
            "Whether authenticated non-members may vote / comment on "
            "annotations (FR-020)."
        ),
    )
    public_location_precision_h3_res: Literal[2, 5, 7, 9, 15] = Field(
        ...,
        description=(
            "Discrete H3 resolution exposed to non-members for site / "
            "detection cells (FR-021). 2=HIDDEN, 5≈30km, 7≈5km, 9≈175m, "
            "15=member-precise."
        ),
    )
    allow_precise_location_to_viewer: StrictBool = Field(
        ...,
        description=(
            "Lift VIEW_PRECISE_LOCATION for project Viewers (FR-022). "
            "Members / Admins / Owners are unaffected by this toggle."
        ),
    )


class ProjectLicenseUpdateRequest(BaseModel):
    """Request body for ``PATCH /projects/{id}/license`` (FR-085 / FR-087).

    Contract: ``contracts/projects.yaml:325-347``. The body is a
    one-field object — ``license`` is required and must be one of the four
    CC enum values; any extra field is rejected with 422 per
    ``additionalProperties: false`` in the OpenAPI shape.
    """

    model_config = ConfigDict(extra="forbid")

    license: ProjectLicense = Field(
        ...,
        description=(
            "Target license — required (FR-085). One of "
            "CC0 / CC-BY / CC-BY-NC / CC-BY-SA."
        ),
    )


class ProjectLicenseHistoryEntry(BaseModel):
    """Single ``ProjectLicenseHistory`` row in the GET response."""

    id: UUID
    project_id: UUID
    old_license: ProjectLicense | None
    new_license: ProjectLicense
    changed_at: datetime
    changed_by_id: UUID | None

    model_config = {"from_attributes": True}


class ProjectLicenseHistoryResponse(BaseModel):
    """Sorted list of license-history rows (oldest → newest, contract:357)."""

    items: list[ProjectLicenseHistoryEntry]


class ProjectMemberAddRequest(BaseModel):
    """Request to add a member to a project."""

    email: EmailStr = Field(..., description="User's email address")
    role: ProjectMemberRole = Field(default=ProjectMemberRole.MEMBER, description="Member role")


class ProjectMemberUpdateRequest(BaseModel):
    """Request to update a member's role."""

    role: ProjectMemberRole = Field(..., description="New member role")


class ProjectMemberResponse(BaseModel):
    """Project member response schema."""

    id: UUID
    user: UserResponse
    role: ProjectMemberRole
    joined_at: datetime
    expires_at: datetime | None
    removed_at: datetime | None

    model_config = {"from_attributes": True}
