"""Admin request and response schemas."""

from datetime import datetime
from ipaddress import AddressValueError, NetmaskValueError, ip_network
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from echoroo.core.operator_pii_detector import (
    OperatorReasonText,
    OperatorSupportTicketId,
    reject_if_pii,
)
from echoroo.models.enums import ProjectMemberRole
from echoroo.schemas.auth import UserResponse


def _validate_cidr_list(value: list[str]) -> list[str]:
    """Validate and canonicalise a list of CIDR strings.

    Phase 15 Batch 5a R2 (Codex Major 2 fix): reject malformed CIDR
    entries at the API surface so the auth middleware never has to
    parse garbage from ``superusers.allowed_ip_cidrs``. ``strict=False``
    permits "10.0.0.5/24" style host-bit-set inputs but immediately
    canonicalises to the network address ("10.0.0.0/24") so an
    operator cannot smuggle a host-laden allowlist past the schema
    that the middleware would later silently mask off.
    """
    validated: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"CIDR entry must be a string: {entry!r}")
        if "/" not in entry:
            raise ValueError(f"missing /prefix in CIDR: {entry!r}")
        try:
            network = ip_network(entry, strict=False)
        except (AddressValueError, NetmaskValueError, ValueError) as exc:
            raise ValueError(f"invalid CIDR {entry!r}: {exc}") from exc
        validated.append(str(network))
    return validated


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

    Phase 17 backlog A-13: ``reason`` uses :data:`OperatorReasonText` which
    enforces the FR-091a PII reject gate (HTTP 422 on email / phone / NID /
    credit-card / token input) so that the persisted ``rejected_reason`` and
    the audit ``reason_excerpt`` cannot leak PII into business tables.
    """

    model_config = ConfigDict(extra="forbid")

    reason: OperatorReasonText


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

    Phase 17 backlog A-13: ``reason`` uses :data:`OperatorReasonText` so the
    FR-091a PII reject gate runs at the API boundary. ``project_audit_log``
    is NOT routed through :class:`AuditLogSanitizer` (only
    ``platform_audit_log`` is), and the reason is also copied into outbox
    payloads via the archive event — boundary rejection prevents PII from
    landing in any of those sinks.
    """

    model_config = ConfigDict(extra="forbid")

    reason: OperatorReasonText


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


# =============================================================================
# Phase 15 Batch 5a — Superuser CRUD admin endpoints (FR-111 / FR-072 / FR-084)
# =============================================================================


class SuperuserSummary(BaseModel):
    """Snapshot of a ``superusers`` row for the admin list view.

    Returned by ``GET /admin/superusers``. Mirrors the columns surfaced
    by ``contracts/admin.yaml`` (operationId ``listSuperusers``).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID = Field(..., description="Superuser entitlement row id (FR-111)")
    user_id: UUID = Field(..., description="Underlying user account id")
    added_by_id: UUID | None = Field(
        default=None,
        description=(
            "User that promoted this superuser (NULL for the genesis "
            "bootstrap row)"
        ),
    )
    added_at: datetime = Field(..., description="Promotion timestamp")
    revoked_at: datetime | None = Field(
        default=None,
        description=(
            "Revocation timestamp (NULL while active). Revoked rows are "
            "preserved for the audit trail."
        ),
    )
    allowed_ip_cidrs: list[str] = Field(
        default_factory=list,
        description="Optional CIDR allowlist enforced by auth middleware (FR-072)",
    )
    webauthn_credential_count: int = Field(
        ...,
        description=(
            "Number of registered WebAuthn authenticators. Spec FR-111 "
            "requires >= 2 (primary + backup); a value below 2 is a "
            "warning state surfaced in the dashboard."
        ),
    )


class SuperuserListResponse(BaseModel):
    """Response body for ``GET /admin/superusers``."""

    model_config = ConfigDict(frozen=True)

    items: list[SuperuserSummary] = Field(
        ..., description="All superuser rows (active + revoked, FR-111)"
    )
    active_count: int = Field(
        ..., description="Number of rows with ``revoked_at IS NULL``"
    )
    min_superusers: int = Field(
        ...,
        description=(
            "Spec floor (= 3). When ``active_count`` falls below this "
            "threshold the platform enters break-glass mode (FR-111)."
        ),
    )
    break_glass_active: bool = Field(
        ...,
        description=(
            "True when the 72 h emergency window is open. Surfaced here "
            "so the admin UI can render a banner without an extra round-trip."
        ),
    )


class SuperuserAddRequest(BaseModel):
    """Body for ``POST /admin/superusers``.

    Promotes a user to superuser. The first three rows are seeded
    directly (creation-time exception); subsequent additions open an
    M-of-N approval ticket and require two co-signers (FR-111).
    """

    model_config = ConfigDict(extra="forbid")

    target_user_id: UUID = Field(
        ..., description="User to promote to superuser"
    )
    allowed_ip_cidrs: list[str] = Field(
        default_factory=list,
        description=(
            "Optional CIDR allowlist for the new superuser. Empty means "
            "no IP restriction. Each entry is parsed as a CIDR and "
            "canonicalised (host bits zeroed) before persistence so the "
            "auth middleware (FR-072) only sees well-formed networks."
        ),
    )

    @field_validator("allowed_ip_cidrs")
    @classmethod
    def _validate_allowed_ip_cidrs(cls, v: list[str]) -> list[str]:
        return _validate_cidr_list(v)


class SuperuserActionResponse(BaseModel):
    """Generic envelope returned by superuser CRUD actions.

    Distinguishes between three terminal states surfaced by the
    M-of-N engine:

    * ``"direct"``      — creation-time exception (count < 3) — the row
                          was inserted immediately.
    * ``"pending"``     — M-of-N approval ticket opened; awaiting two
                          co-signers.
    * ``"applied"``     — quorum met, the underlying mutation has been
                          executed.
    * ``"rejected"``    — ticket rejected by a co-signer.
    """

    model_config = ConfigDict(frozen=True)

    status: str = Field(
        ...,
        description=(
            "Engine state: ``direct`` / ``pending`` / ``applied`` / ``rejected``"
        ),
    )
    superuser_id: UUID | None = Field(
        default=None,
        description=(
            "Resulting superuser row id. Populated for ``direct`` and "
            "``applied`` (revoke); NULL while pending."
        ),
    )
    approval_request_id: UUID | None = Field(
        default=None,
        description="``superuser_approval_requests.id`` while pending",
    )
    detail: dict[str, object] = Field(
        default_factory=dict,
        description="Engine outcome detail (action / counts / approver / etc.)",
    )


class SuperuserApprovalRequestSummary(BaseModel):
    """Snapshot of a ``superuser_approval_requests`` row.

    Returned by ``GET /admin/superusers/approval-requests``. Surfaces the
    columns needed by the operator dashboard to render the M-of-N queue
    (FR-111).
    """

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID = Field(..., description="Approval request row id")
    action: str = Field(
        ...,
        description=(
            "Pending action — ``superuser.add`` / ``superuser.revoke`` / "
            "``backup_code_reset`` / ``looser_override_*``"
        ),
    )
    detail: dict[str, object] | None = Field(
        default=None,
        description="Action-specific payload (target user, etc.)",
    )
    requested_by_id: UUID = Field(
        ..., description="``superusers.id`` that opened the ticket"
    )
    approvals: list[dict[str, object]] = Field(
        default_factory=list,
        description="Co-signer entries appended by ``approve_request``",
    )
    status: str = Field(
        ..., description="``pending`` / ``applied`` / ``rejected``"
    )
    created_at: datetime = Field(
        ..., description="Ticket creation timestamp"
    )
    executed_at: datetime | None = Field(
        default=None,
        description="Final-decision timestamp (NULL while pending)",
    )


class SuperuserApprovalRequestListResponse(BaseModel):
    """Response body for ``GET /admin/superusers/approval-requests``."""

    model_config = ConfigDict(frozen=True)

    items: list[SuperuserApprovalRequestSummary] = Field(
        ..., description="Approval requests (filtered by ``status`` query param)"
    )
    pending_count: int = Field(
        ..., description="Number of items with status=='pending'"
    )
    min_approvals: int = Field(
        ..., description="Spec quorum (= 2)"
    )


class SuperuserRejectRequest(BaseModel):
    """Body for ``POST /admin/superusers/approval-requests/{id}/reject``.

    Phase 17 backlog A-13: ``reason`` uses :data:`OperatorReasonText`. The
    rejection reason is appended to ``superuser_approval_requests.approvals``
    JSONB (a business table, not the audit log) so the FR-091a PII reject
    gate at the API boundary is the only safeguard against PII landing in
    that JSONB array.
    """

    model_config = ConfigDict(extra="forbid")

    reason: OperatorReasonText


class SuperuserBreakGlassEnterRequest(BaseModel):
    """Body for ``POST /admin/superusers/break-glass/enter``.

    Phase 17 backlog A-13: ``reason`` uses :data:`OperatorReasonText`. The
    reason is persisted on ``superuser_break_glass.reason`` (business
    table) and surfaced verbatim by ``GET /admin/superusers/break-glass/
    status``, so PII rejection at the API boundary protects both the
    persisted column and the read-back response.
    """

    model_config = ConfigDict(extra="forbid")

    reason: OperatorReasonText


class SuperuserBreakGlassStatusResponse(BaseModel):
    """Response body for ``GET /admin/superusers/break-glass/status``."""

    model_config = ConfigDict(frozen=True)

    active: bool = Field(
        ..., description="True iff the 72 h window is currently open"
    )
    started_at: datetime | None = Field(
        default=None,
        description=(
            "Start of the current window (NULL when inactive). Wall-clock "
            "+ 72 h is the deadline."
        ),
    )
    expires_at: datetime | None = Field(
        default=None,
        description="``started_at + 72h`` (NULL when inactive)",
    )
    replacement_deadline_at: datetime | None = Field(
        default=None,
        description=(
            "``started_at + 24h`` — by which a replacement superuser must "
            "be added per FR-111 (NULL when inactive)."
        ),
    )
    reason: str | None = Field(
        default=None,
        description="Operator-supplied reason recorded at entry",
    )


class SuperuserIpAllowlistUpdateRequest(BaseModel):
    """Body for ``PATCH /admin/superusers/{id}/ip-allowlist``.

    Replaces ``superusers.allowed_ip_cidrs`` wholesale. Phase 15 Batch
    5a R2 (Codex Major 2 fix): each CIDR entry is now validated and
    canonicalised at the API surface so the auth middleware (FR-072)
    cannot be fed malformed input that would otherwise persist into
    ``superusers.allowed_ip_cidrs`` and silently neuter the
    allowlist gate.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_ip_cidrs: list[str] = Field(
        ...,
        description=(
            "New allowlist (replaces the existing array). Empty means "
            "no IP restriction. Each entry is parsed as a CIDR and "
            "canonicalised (host bits zeroed) before persistence."
        ),
    )

    @field_validator("allowed_ip_cidrs")
    @classmethod
    def _validate_allowed_ip_cidrs(cls, v: list[str]) -> list[str]:
        return _validate_cidr_list(v)


class SuperuserIpAllowlistResponse(BaseModel):
    """Response body for ``PATCH /admin/superusers/{id}/ip-allowlist``."""

    model_config = ConfigDict(frozen=True)

    superuser_id: UUID = Field(..., description="Updated superuser row id")
    allowed_ip_cidrs: list[str] = Field(
        ..., description="Persisted allowlist after the update"
    )
    updated_at: datetime = Field(
        ..., description="Wall-clock timestamp of the update"
    )


# =============================================================================
# Phase 17 follow-up — admin 2FA reset stub (FR-072)
# =============================================================================


class ResetTwoFactorRequest(BaseModel):
    """Body for ``POST /admin/users/{userId}/reset-2fa`` (Phase 17 A-11).

    The 4-factor identity proof (FR-072) is performed out-of-band via
    ``POST /web-api/v1/auth/confirm-identity-for-2fa-reset`` — the user
    receives a magic link by email, redeems it, and the redeem
    endpoint mints a short-lived ``confirmation_token`` (5 min TTL)
    that the support agent pastes into this body. The token binds the
    target ``user_id`` + a one-time-use nonce + an HMAC signature so
    forging or reusing it is rejected with 409.

    Defaults:

    * ``skip_delay=False`` → row enters ``pending_delay`` and the
      Celery beat poller dispatches after the 24h delay.
    * ``skip_delay=True`` → opens an M-of-N
      :class:`~echoroo.models.superuser_approval_request.SuperuserApprovalRequest`
      with action ``two_factor_reset.skip_delay``; quorum (two
      co-signing superusers) flips the row to ``approved`` with
      ``dispatch_at = now()``.

    Phase 17 backlog A-13: both ``support_ticket_id`` and ``reason`` use
    the operator-PII Annotated types so the FR-091a reject gate runs at
    the API boundary. The values are persisted verbatim on
    ``two_factor_reset_requests`` (a business table — NOT routed through
    :class:`AuditLogSanitizer`), so boundary rejection is the only
    safeguard against PII landing in that row.
    """

    model_config = ConfigDict(extra="forbid")

    support_ticket_id: OperatorSupportTicketId
    reason: OperatorReasonText
    skip_delay: bool = Field(
        default=False,
        description=(
            "When ``true``, open an M-of-N approval ticket "
            "(``two_factor_reset.skip_delay``) instead of waiting 24 h "
            "for the dispatch poller. Quorum (two co-signing "
            "superusers) immediately flips the row to ``approved``."
        ),
    )
    confirmation_token: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description=(
            "Short-lived HMAC token returned by "
            "``POST /web-api/v1/auth/confirm-identity-for-2fa-reset/redeem`` "
            "after the user redeems the emailed magic link. Bound to "
            "the target ``user_id`` and consumed exactly once. "
            "Mismatched / expired / replayed tokens yield HTTP 409."
        ),
    )


class AdminPasswordResetBody(BaseModel):
    """Body for ``POST /web-api/v1/admin/users/{user_id}/reset-password``.

    spec/011 §FR-011-201..210 / contracts/admin-password-reset.yaml.

    The body is optional — operators may invoke the reset without a
    reason (the audit row still captures actor + target + timestamp).
    When supplied, the reason is bounded to 500 characters per the
    OpenAPI contract and passes through the Phase 17 A-13 free-form PII
    detector (FR-011-208) so an operator cannot accidentally leak the
    target's email / phone / national identifier into the audit log or
    business-table reason column.

    The dedicated 500-char limit (distinct from
    :data:`OperatorReasonText`'s 2000-char canonical limit) tracks the
    contract verbatim — ``test_openapi_diff.py`` enforces the cap on
    every CI run.
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
                "API tokens). Reference the target user by ``user_id`` "
                "or an external ticket reference instead. Validated "
                "server-side (Phase 17 A-13) — submitting PII yields "
                "HTTP 422."
            ),
        ),
        AfterValidator(reject_if_pii),
    ] | None = Field(
        default=None,
        description=(
            "Optional free-form rationale recorded in the audit detail. "
            "Omit to record an empty-reason reset (still audited)."
        ),
    )


class AdminPasswordResetResponse(BaseModel):
    """Response body for ``POST /web-api/v1/admin/users/{user_id}/reset-password``.

    spec/011 §FR-011-202 / contracts/admin-password-reset.yaml.

    The response carries the one-time temporary password value the
    target user MUST use for the next login. The value is delivered
    verbatim to the issuing superuser exactly once — the API does not
    persist it (only its argon2 hash lands in ``users.password_hash``)
    and the frontend renders it behind a click-to-reveal dialog with
    a 60-second auto-clear copy-to-clipboard button.

    The endpoint sets ``Cache-Control: no-store, no-cache,
    must-revalidate, private`` and ``Referrer-Policy: no-referrer``
    response headers (FR-011-202) so neither browser history nor
    intermediate proxies can retain the value. Telemetry / access logs
    MUST scrub the ``temporary_password`` field
    (:mod:`echoroo.observability.sentry` redaction registry).
    """

    model_config = ConfigDict(frozen=True)

    temporary_password: str = Field(
        ...,
        description=(
            "One-shot value. MUST be scrubbed from telemetry / access "
            "logs. Frontend renders behind click-to-reveal; copies to "
            "clipboard with 60s auto-clear."
        ),
    )
    expires_at: datetime = Field(
        ...,
        description=(
            "UTC instant after which the temporary password no longer "
            "authenticates (FR-011-203 / FR-011-209). Mirrors "
            "``users.temp_password_expires_at``."
        ),
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
