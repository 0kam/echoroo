"""Project request and response schemas."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_serializer,
)

from echoroo.models.enums import (
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.schemas.auth import UserResponse

RequiredProjectLicenseInput = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]
ProjectLicenseInput = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=50),
]


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

    Phase 9 polish round 2 致命 1 (2026-04-27): a single ``email`` slot is
    exposed as **optional** so the Restricted detail surface (US4 AC2) can
    populate it for Authenticated callers, while every Public-detail and
    Guest-reachable response keeps it ``None``. The endpoint layer is the
    only place that decides whether to write the value — see
    ``apps/api/echoroo/api/v1/projects.py::_assemble_project_response`` /
    ``apps/api/echoroo/api/web_v1/projects/_core.py``. The field defaults
    to ``None`` so ``ProjectResponse.model_validate(project)`` cannot
    accidentally serialise the SQLAlchemy ``User.email`` attribute via
    ``from_attributes`` — that path is now blocked because the ORM column
    is named ``email`` and the Pydantic field has the same name, but the
    default ``None`` keeps the privacy contract: callers must opt in.

    Email is **only** ever exposed for the project owner on a Restricted
    project to an Authenticated caller. Guests, Public-detail callers, and
    every other user's email never reach the wire through this schema.

    Implementation note: ``from_attributes`` stays ``True`` so the parent
    :class:`ProjectResponse.model_validate` call can hydrate this nested
    object from ``Project.owner`` (the ORM relationship). To keep the
    privacy contract intact, the endpoint layer **scrubs** the email back
    to ``None`` immediately after model_validate for every path that is
    not "Authenticated caller + Restricted project" — see
    :func:`echoroo.services.project.scrub_owner_email_for_visibility`.
    """

    id: UUID
    display_name: str | None
    # Phase 9 polish round 2 致命 1: optional contact email for the project
    # owner. Populated only when the caller is Authenticated AND the project
    # is Restricted (US4 AC2 mailto: hook). For every other path the field
    # is scrubbed to ``None`` by the endpoint layer so Public detail / Guest
    # responses never leak the address (FR-030).
    email: str | None = None

    model_config = {"from_attributes": True}

    # Phase 16 Batch 6e (2026-04-29) 真の実害 fix 1A: when ``email`` is
    # ``None`` the **key itself** must not appear in the JSON body. The
    # original Phase 9 contract scrubbed the value to ``None`` on every
    # path that is not "Authenticated caller + Restricted project", but
    # the resulting body still carried ``"email": null`` which is a PII
    # *shape* leak (a hostile crawler can map which projects are
    # Restricted by looking at the absence of the slot, and the slot's
    # mere presence telegraphs that the API stores an email). Dropping
    # the key entirely when scrubbed keeps the privacy contract tight:
    # only the Restricted+Authenticated branch (where the scrubber
    # leaves ``email`` populated) emits the field at all.
    @model_serializer(mode="wrap")
    def _drop_email_when_scrubbed(
        self, handler: Any
    ) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if data.get("email") is None:
            data.pop("email", None)
        return data


class ProjectOverviewSite(BaseModel):
    """Site summary within project overview.

    Phase 13 P4 / T807: ``h3_index_member`` matches ORM
    ``Site.h3_index_member`` and the spec data-model §3.10 canonical
    name (full rename, no facade). Raw latitude/longitude coordinates
    are intentionally absent from this public-facing overview shape; H3
    is the only site location signal exposed here.
    """

    id: UUID
    name: str
    h3_index_member: str
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
    target_taxa: str | None = Field(
        None,
        max_length=500,
        description="Operator-typed comma-separated focus taxa (optional).",
    )
    # Phase 7 polish round 2 (Major 2): contract ``ProjectCreateRequest``
    # marks ``visibility`` as ``required`` (projects.yaml:408). A pydantic
    # default would silently fill the field on omission and emit 201 instead
    # of the contract-mandated 422, so the field is declared without a
    # default to match ``additionalProperties: false`` + ``required`` in the
    # OpenAPI shape.
    visibility: ProjectVisibility = Field(..., description="Project visibility level")
    license_id: RequiredProjectLicenseInput = Field(
        ...,
        description=(
            "Project data license id — required at creation (FR-085). "
            "Carries the ``licenses.id`` primary key (e.g. ``cc-by``); an "
            "unknown id is rejected with 422 ``license_not_found``."
        ),
    )
    restricted_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Restricted visibility capability toggles",
    )
    # spec/011 FR-011-120..125 — system superuser project bootstrap.
    # The field is OPTIONAL at the schema layer for every caller (so
    # ``extra="forbid"`` does not 422 a non-superuser submission).
    #
    # spec/011 Step 9 R1 P0-2 (anti-enumeration): the field is typed as
    # ``str | None`` instead of ``EmailStr | None`` so Pydantic does NOT
    # run email-format validation at schema-decode time. Without this
    # weakening a non-superuser submitting ``intended_owner_email="x"``
    # would receive a 422 "value is not a valid email address" response,
    # leaking that the server recognises the field. Format validation is
    # moved into the handler AFTER the SU check so non-SU callers' values
    # are silently dropped without ANY validation feedback (FR-011-125).
    intended_owner_email: str | None = Field(
        default=None,
        description=(
            "Optional system-superuser-only field. When supplied by a "
            "superuser, the project is created with the superuser as "
            "the placeholder owner and an Admin-role invitation is "
            "issued for the supplied email with ownership_transfer_on_"
            "accept=true. Silently ignored for non-superuser callers "
            "(FR-011-125). Format validation runs inside the handler "
            "AFTER the superuser check so non-superuser submissions "
            "of malformed values are silently dropped without leaking "
            "the field's existence via a 422 email-format error."
        ),
    )


class ProjectUpdateRequest(BaseModel):
    """Project update request schema."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=200, description="Project name")
    description: str | None = Field(None, description="Project description")
    target_taxa: str | None = Field(
        None,
        max_length=500,
        description="Operator-typed comma-separated focus taxa (optional).",
    )
    visibility: ProjectVisibility | None = Field(None, description="Project visibility level")
    license_id: ProjectLicenseInput | None = Field(
        None,
        description=(
            "Project data license id (``licenses.id`` primary key, e.g. "
            "``cc-by``). An unknown id is rejected with 422 "
            "``license_not_found``."
        ),
    )
    restricted_config: dict[str, Any] | None = Field(
        None,
        description="Restricted visibility capability toggles",
    )
    status: ProjectStatus | None = Field(None, description="Project lifecycle status")


class ProjectResponse(BaseModel):
    """Project response schema.

    Phase 9 polish round 2 Major 2 (2026-04-27): ``current_user_role``
    surfaces the caller's effective project role on the detail response so
    the Web UI can decide whether to show the Restricted "Request access"
    callout without round-tripping the admin-only ``GET /members``
    endpoint (which 403s for Members / Viewers and would silently break
    the gate). The field is one of:

        * ``"owner"``   — caller is the project owner.
        * ``"admin"``   — caller is an active member with role ``ADMIN``.
        * ``"member"``  — caller is an active member with role ``MEMBER``.
        * ``"viewer"``  — caller is an active member with role ``VIEWER``.
        * ``None``      — caller is Authenticated but not a member, or
                          Guest. The Web UI uses this to render the
                          mailto: callout for outsiders on Restricted
                          projects.

    The endpoint layer is the only place that resolves the role (the
    schema default is ``None`` so a model_validate path that forgets to
    set it can never leak a stale value from a previous request).
    """

    id: UUID
    name: str
    description: str | None
    target_taxa: str | None = Field(
        None,
        description="Operator-typed comma-separated focus taxa.",
    )
    visibility: ProjectVisibility
    license: str | None
    restricted_config: dict[str, Any]
    restricted_config_version: int
    status: ProjectStatus
    dormant_since: datetime | None
    archived_since: datetime | None
    owner: PublicOwnerResponse
    created_at: datetime
    updated_at: datetime
    # Phase 9 polish round 2 Major 2: caller's effective project role.
    # ``None`` for Guest and for Authenticated non-members. The Web UI
    # gate for the Restricted "Request access" callout uses
    # ``current_user_role is None`` instead of probing the admin-only
    # ``GET /members`` endpoint.
    current_user_role: Literal["owner", "admin", "member", "viewer"] | None = None

    model_config = {"from_attributes": True}


class ProjectCreateResponse(ProjectResponse):
    """Project response shape returned by ``POST /web-api/v1/projects``.

    spec/011 FR-011-121: extends :class:`ProjectResponse` with two
    optional bootstrap-invitation fields. Both fields appear on EVERY
    create response (as ``null`` for non-superuser callers and for
    superuser submissions that omit ``intended_owner_email``) so the
    response shape is identical between superuser and non-superuser
    callers — the field's existence alone MUST NOT let a non-superuser
    enumerate the SU bootstrap feature (FR-011-125).

    When the system superuser supplies ``intended_owner_email`` on the
    create request, the create-project transaction atomically issues
    a Member-kind ADMIN-role invitation with
    ``ownership_transfer_on_accept=True`` and surfaces the 4-part
    signed envelope under ``invitation_url`` (one-shot — NOT
    recoverable past this single HTTP turn). The endpoint mirrors the
    Step 6 / Step 7 invitation surface by setting
    ``Cache-Control: no-store, no-cache, must-revalidate, private`` on
    EVERY create response so the header alone cannot reveal whether
    the bootstrap branch fired.
    """

    invitation_url: str | None = Field(
        default=None,
        description=(
            "spec/011 FR-011-121: one-shot signed envelope returned only "
            "when the system superuser supplied ``intended_owner_email``. "
            "MUST NOT be logged or telemetered past this single HTTP "
            "turn (FR-011-102 token confidentiality)."
        ),
    )
    invitation_id: UUID | None = Field(
        default=None,
        description=(
            "spec/011 FR-011-121: id of the bootstrap invitation row, "
            "populated alongside ``invitation_url``. ``None`` for the "
            "non-bootstrap branch (anti-enumeration: same shape)."
        ),
    )


class ProjectListResponse(BaseModel):
    """Internal full-:class:`ProjectResponse` paginated list shape.

    .. deprecated:: Phase 9 polish round 3
        Both public list surfaces — ``/api/v1/projects`` (programmatic) and
        ``/web-api/v1/projects`` (Web UI) — now emit
        :class:`ProjectSummaryListResponse` / :class:`ProjectSummary` so the
        Restricted enumeration contract (FR-018 / FR-019 / FR-030) cannot
        leak ``restricted_config`` or any field beyond the documented
        summary slot. This schema is retained as an **internal-only** detail
        type (kept for any in-process helper that genuinely needs the full
        body alongside pagination metadata) and is no longer wired to any
        FastAPI route. Slated for removal once the last in-tree caller is
        migrated; do not add new references.
    """

    items: list[ProjectResponse]
    total: int
    page: int
    limit: int


class ProjectSummary(BaseModel):
    """Web UI project summary (contracts/projects.yaml ``ProjectSummary``).

    Phase 9 polish round 2 致命 1: ``GET /web-api/v1/projects`` MUST return
    this shape — **not** :class:`ProjectResponse` — so the Restricted
    enumeration surface (FR-019) carries owner display name, dataset count
    and species preview but never leaks ``restricted_config`` or any field
    beyond the documented summary contract. The detail endpoint
    (``GET /web-api/v1/projects/{id}``) keeps using
    :class:`ProjectResponse` (which Owner / Admin Trusted callers see in
    full + Restricted ``restricted_config``).

    Per ``contracts/projects.yaml:384-395`` the summary deliberately omits
    every internal-state field exposed on :class:`ProjectResponse`
    (``dormant_since``, ``archived_since``, ``created_at``,
    ``updated_at``, ``restricted_config``, ``restricted_config_version``,
    ``owner`` sub-object) so a Guest enumeration call cannot pivot from a
    Restricted row's metadata into anything else (FR-018 / FR-019 /
    FR-030).
    """

    id: UUID
    name: str
    description: str | None
    visibility: ProjectVisibility
    status: ProjectStatus
    license: str | None
    owner_display_name: str = Field(
        ...,
        description=(
            "Public-safe display string for the project owner. Falls back "
            "to the local-part of the email when the User row has no "
            "``display_name`` set; never the full email address (FR-030)."
        ),
    )
    dataset_count: int = Field(
        ...,
        ge=0,
        description="Number of Datasets attached to this project.",
    )
    species_preview: list[str] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Up to 5 most-frequent species labels for the project. Phase 9 "
            "ships the field as an empty list when the helper aggregator "
            "is not yet wired (Phase 11 backlog); the contract slot is "
            "kept so consumers can switch over without a schema migration."
        ),
    )

    model_config = {"from_attributes": True}


class ProjectSummaryListResponse(BaseModel):
    """Paginated :class:`ProjectSummary` list — the canonical list contract.

    Mirrors ``contracts/projects.yaml:374-382`` ``ProjectListResponse``
    (the contract reuses the schema name; we disambiguate via the
    ``Summary`` suffix here so the deprecated full-body
    :class:`ProjectListResponse` can keep its identifier while it is being
    phased out). Phase 9 polish round 3 (2026-04-27) migrated **both**
    public list surfaces — ``/api/v1/projects`` (programmatic) and
    ``/web-api/v1/projects`` (Web UI) — onto this schema so neither route
    can leak ``restricted_config`` or owner sub-objects in an enumeration
    response (FR-018 / FR-019 / FR-030).

    Phase 9 polish round 3 Major 1 (2026-04-27): the OpenAPI shape
    (``ProjectListResponse`` at ``contracts/projects.yaml:375-383``) only
    declares ``items / total / page`` — there is **no** ``limit`` field
    on the contract. A previous iteration of this schema also exposed
    ``limit`` for symmetry with :class:`ProjectListResponse`, but that
    was contract drift; clients on the contract-correct surface know the
    page size from the request query and never see it echoed back.
    Removing the field keeps the response strict-equal to the contract
    so consumers cannot accidentally rely on a non-spec field.
    """

    items: list[ProjectSummary]
    total: int
    page: int


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
    * ``public_location_precision_h3_res`` is constrained to continuous
      integer H3 resolutions 3 through 15; values outside that range are
      rejected at validation time so the service layer never receives a
      free-form value.
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
    public_location_precision_h3_res: Annotated[
        StrictInt,
        Field(
            ge=3,
            le=15,
            description=(
                "H3 resolution exposed to non-members for site / detection cells "
                "(FR-021). Accepts any integer from 3 through 15."
            ),
        ),
    ]
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
    one-field object — ``license_id`` is required and must reference an
    existing ``licenses.id`` primary key; an unknown id is rejected with
    422 ``license_not_found`` and any extra field is rejected with 422 per
    ``additionalProperties: false`` in the OpenAPI shape.
    """

    model_config = ConfigDict(extra="forbid")

    license_id: ProjectLicenseInput = Field(
        ...,
        description=(
            "Target license id — required (FR-085). Carries the "
            "``licenses.id`` primary key (e.g. ``cc-by``); an unknown id "
            "is rejected with 422 ``license_not_found``."
        ),
    )


class ProjectLicenseHistoryEntry(BaseModel):
    """Single ``ProjectLicenseHistory`` row in the GET response."""

    id: UUID
    project_id: UUID
    old_license: str | None
    new_license: str
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
