"""Permission engine for 006-permissions-redesign.

This module is the SINGLE source of truth for authorization decisions.
The decision engine itself does not perform SQLAlchemy session / database
access; callers resolve state upstream (role, project, trusted capabilities,
API key scopes, taxon sensitivity maps) and pass it in. Small FastAPI helper
wrappers at the end of the file load Project rows for router call sites.

Section layout (matches T040a-g):

    T040a  Permission enum (28 members), USER_SCOPE_PERMISSIONS,
           TRUSTED_ALLOWED_PERMISSIONS, SUPERUSER_PROJECT_SCOPE_ALLOWLIST.
    T040b  Action Pydantic model + ACTIONS catalog + register_action helper.
    T040c  ROLE_PERMISSIONS canonical matrix (frozenset-valued).
    T040d  is_allowed — stage-1 permission gate.
    T040e  compute_effective_permissions — Canonical + Trusted overlay +
           Restricted toggle + API key intersection.
    T040f  compute_effective_resolution — HIDDEN clamp, looser override
           replacement, Trusted boost, taxon sensitivity.
    T040g  normalize_role, resolve_role, active_trusted_capabilities,
           permissions_from_toggles_* helpers.

Spec references (Rev.3.2):
    FR-008 / FR-008a / FR-008b (gate algorithm, Action model, superuser allowlist)
    FR-009 / FR-010 / FR-011 / FR-012 / FR-014 / FR-015 / FR-015a (Permission
      enum, Canonical Matrix, Response filter, Trusted allowlist)
    FR-016 / FR-017 / FR-017a / FR-018 / FR-019 / FR-020 (Visibility behaviour)
    FR-027 / FR-034 / FR-035 (Location sensitivity, override, HIDDEN clamp)
    NFR-001 / NFR-001a / NFR-008 (performance, request-scope cache rule)
    SC-001 / SC-017 (structural safety nets)

Legacy compatibility: ``check_project_access`` is retained below because
Phase 3 has not yet rewritten the existing routers that import it.
"""
from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import ProjectMemberRole
from echoroo.models.project import Project

# =============================================================================
# T040a. Enums + constants
# =============================================================================

class Permission(StrEnum):
    """Canonical permission set (spec FR-009 + AD-1B Option A: Project 27 + User 2 = 29).

    AD-1B Option A (2026-05-12, behavior-preserving): MANAGE_DATASET_ADMIN
    was introduced to make explicit the split between admin-only dataset
    operations and the existing MANAGE_DATASET. Only Admin/Owner hold
    MANAGE_DATASET_ADMIN. The pre-AD-1B Canonical Matrix already restricts
    MANAGE_DATASET to Admin/Owner (Member does not hold it), so this enum
    addition is purely additive at the matrix level. Action-level
    required_permission rewiring (so currently-MANAGE_DATASET endpoints
    targeting admin-only operations migrate to MANAGE_DATASET_ADMIN) is
    intentionally deferred to spec/007 task #6.
    """

    # -- Project viewing (6) --
    VIEW_PROJECT_METADATA = "view_project_metadata"
    VIEW_DATASET_LIST = "view_dataset_list"
    VIEW_MEDIA = "view_media"
    VIEW_DETECTION = "view_detection"
    VIEW_PRECISE_LOCATION = "view_precise_location"
    VIEW_AUDIT_LOG = "view_audit_log"

    # -- Search / output (4) --
    SEARCH_WITHIN_PROJECT = "search_within_project"
    SEARCH_CROSS_PROJECT = "search_cross_project"
    DOWNLOAD = "download"
    EXPORT = "export"

    # -- Editing (9) --
    VOTE = "vote"
    COMMENT = "comment"
    CREATE_TAG = "create_tag"
    ANNOTATE = "annotate"
    UPLOAD = "upload"
    MANAGE_SITE = "manage_site"
    MANAGE_DATASET = "manage_dataset"
    MANAGE_DATASET_ADMIN = "manage_dataset_admin"
    RUN_INFERENCE = "run_inference"
    TRAIN_MODEL = "train_model"

    # -- Project administration (7) --
    MANAGE_MEMBERS = "manage_members"
    MANAGE_TRUSTED = "manage_trusted"
    EDIT_PROJECT = "edit_project"
    MANAGE_LICENSE = "manage_license"
    DELETE_PROJECT = "delete_project"
    TRANSFER_OWNERSHIP = "transfer_ownership"
    OVERRIDE_TAXON_SENSITIVITY = "override_taxon_sensitivity"

    # -- User self-management (2, Matrix-exempt) --
    MANAGE_API_KEY = "manage_api_key"
    MANAGE_2FA = "manage_2fa"


class ComputedRole(StrEnum):
    """Computed project role used by the gate engine.

    The DB enum equivalent is ``ProjectMemberRole`` in ``models/enums.py`` and
    does NOT include ``OWNER``; OWNER is derived at runtime from
    ``projects.owner_id``.
    """

    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


# Backwards-compat shim — DEPRECATED, remove after consumers migrate.
# TODO(006-permissions Phase 3 cleanup): remove this shim once external
# consumers (frontend bindings, third-party API clients) have migrated to
# ComputedRole. Internal code already uses ComputedRole exclusively.
ProjectRole = ComputedRole


class ProjectVisibility(StrEnum):
    """2-value visibility (spec FR-001, Private removed)."""

    PUBLIC = "public"
    RESTRICTED = "restricted"


class TaxonOverrideDirection(StrEnum):
    """FR-033: override direction."""

    STRICTER = "stricter"
    LOOSER = "looser"


class TaxonOverrideApprovalStatus(StrEnum):
    """FR-033: looser override approval lifecycle."""

    APPLIED = "applied"
    PENDING_SUPERUSER_APPROVAL = "pending_superuser_approval"
    REJECTED = "rejected"


# --- H3 resolution constants (spec FR-027 discrete set) -----------------------
H3_RES_2 = 2   # HIDDEN
H3_RES_5 = 5   # very coarse
H3_RES_7 = 7   # coarse
H3_RES_9 = 9   # open / non-member default
H3_RES_15 = 15  # member precise (default, NFR-003)

VALID_H3_RESOLUTIONS: frozenset[int] = frozenset({H3_RES_2, H3_RES_5, H3_RES_7, H3_RES_9, H3_RES_15})
DEFAULT_PUBLIC_LOCATION_PRECISION_H3_RES = 3


# --- Permission classification (spec data-model §1) ---------------------------

# USER_SCOPE_PERMISSIONS is defined in the AD-8 Permission Category
# Classification block below (after ROLE_PERMISSIONS). The pre-AD-8 definition
# additionally listed SEARCH_CROSS_PROJECT; spec/007 §AD-8 re-categorises that
# permission as ENDPOINT_BACKED because its grant is project-context-dependent.

TRUSTED_ALLOWED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
        Permission.VIEW_PRECISE_LOCATION,
        Permission.DOWNLOAD,
        Permission.EXPORT,
        Permission.SEARCH_WITHIN_PROJECT,
        Permission.VOTE,
        Permission.COMMENT,
    }
)
"""FR-012: the only permissions a Trusted overlay may grant.

Out-of-allowlist entries in a ProjectTrustedUser row are filtered at runtime
(FR-014) — this frozenset is the safety net.
"""

SUPERUSER_PROJECT_SCOPE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "project.archive",
        "project.restore",
        "project.taxon_override.approve_looser",
        "project.taxon_override.reject_looser",
        "project.iucn.force_resync",
        "project.audit_log.read_platform",
    }
)
"""FR-008b: Superuser may bypass per-project Permission gate ONLY for these actions."""


# =============================================================================
# T040b. Action model + ACTIONS catalog
# =============================================================================

class Action(BaseModel):
    """Declarative description of an API endpoint's authorization contract.

    Every FastAPI path operation registers an ``Action`` in ``ACTIONS`` so the
    gate can look up the required permission without the endpoint having to
    re-implement the decision logic. See spec FR-008a.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    """Canonical action name (e.g. ``detection.vote``, ``project.restore``)."""

    required_permission: Permission | None = None
    """Project-scope permission required. ``None`` iff is_platform_scope=True."""

    is_mutating: bool = False
    """State-changing endpoint? Archived projects block mutating actions."""

    is_superuser_only: bool = False
    """May ONLY be executed by a Superuser."""

    is_platform_scope: bool = False
    """Platform-scope (no project resource). Implies superuser_only + no permission."""

    @model_validator(mode="after")
    def _validate_consistency(self) -> Action:
        if self.is_platform_scope:
            if self.required_permission is not None:
                raise ValueError(
                    f"Action {self.name!r}: is_platform_scope=True requires "
                    f"required_permission=None"
                )
            if not self.is_superuser_only:
                raise ValueError(
                    f"Action {self.name!r}: is_platform_scope=True implies "
                    f"is_superuser_only=True"
                )
        else:
            if self.required_permission is None:
                raise ValueError(
                    f"Action {self.name!r}: project-scope actions must declare "
                    f"required_permission"
                )
        return self


ACTIONS: dict[str, Action] = {}
"""Global Action catalog — filled in Phase 3 endpoint rewrite. Kept empty here
so CI enforcement starts in warn-only mode; T100f flips it to hard-fail."""


def register_action(action: Action) -> Action:
    """Idempotently register an Action in the catalog. Returns the Action.

    Raises ``ValueError`` on duplicate name (protects against copy-paste bugs).
    """
    if action.name in ACTIONS and ACTIONS[action.name] != action:
        raise ValueError(f"Duplicate Action registration with different shape: {action.name!r}")
    ACTIONS[action.name] = action
    return action


# =============================================================================
# T040c. Canonical Matrix — ROLE_PERMISSIONS
# =============================================================================

_VIEWER_PERMS: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
        Permission.SEARCH_WITHIN_PROJECT,
    }
)

_MEMBER_PERMS: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
        Permission.VIEW_PRECISE_LOCATION,
        Permission.SEARCH_WITHIN_PROJECT,
        Permission.SEARCH_CROSS_PROJECT,
        Permission.DOWNLOAD,
        Permission.EXPORT,
        Permission.VOTE,
        Permission.COMMENT,
        Permission.CREATE_TAG,
        Permission.ANNOTATE,
        Permission.UPLOAD,
        # spec/007 Phase 2A.6 hotfix (Codex consultation 2026-05-12, Option A):
        # Member retains MANAGE_DATASET for dataset-CONTENT operations (clip
        # CRUD, generate, etc.) per spec/007 Rev.5.1 § 4A glossary +
        # spec/008-permissions-vocabulary-refinement. The current backend
        # `check_project_access()` allows any member to mutate clips; gating
        # those endpoints on MANAGE_DATASET without granting it to member
        # would regress member access (P0). Resource-level dataset CRUD
        # (create/delete/edit dataset itself, import, datetime apply,
        # annotation_project CRUD, etc.) remains admin/owner-only via the new
        # MANAGE_DATASET_ADMIN below.
        Permission.MANAGE_DATASET,
        Permission.MANAGE_SITE,  # TODO(spec/008-audit): SUPERUSER_ONLY category vs member-held — flagged for audit in Codex consultation 2026-05-12; out of scope for this hotfix.
        Permission.RUN_INFERENCE,
    }
)

_ADMIN_PERMS: frozenset[Permission] = _MEMBER_PERMS | frozenset(
    {
        Permission.VIEW_AUDIT_LOG,
        # MANAGE_DATASET now inherited from _MEMBER_PERMS (admin gets it implicitly).
        Permission.MANAGE_DATASET_ADMIN,  # AD-1B Option A: admin-only dataset-resource ops
        Permission.TRAIN_MODEL,
        Permission.MANAGE_MEMBERS,
        Permission.EDIT_PROJECT,
        Permission.MANAGE_LICENSE,
    }
)

_OWNER_PERMS: frozenset[Permission] = _ADMIN_PERMS | frozenset(
    {
        Permission.MANAGE_TRUSTED,
        Permission.DELETE_PROJECT,
        Permission.TRANSFER_OWNERSHIP,
        Permission.OVERRIDE_TAXON_SENSITIVITY,
    }
)


ROLE_PERMISSIONS: Mapping[ComputedRole, frozenset[Permission]] = MappingProxyType(
    {
        ComputedRole.VIEWER: _VIEWER_PERMS,
        ComputedRole.MEMBER: _MEMBER_PERMS,
        ComputedRole.ADMIN: _ADMIN_PERMS,
        ComputedRole.OWNER: _OWNER_PERMS,
    }
)
"""FR-010: the Canonical Matrix. Immutable (MappingProxyType) to prevent
runtime mutation that would bypass CI matrix tests."""


# Superuser synthetic "role" — receives Owner-equivalent perms when on the
# project-scope allowlist (FR-008b). Stored separately since ComputedRole is
# strictly persisted values.
_SUPERUSER_PERMS: frozenset[Permission] = _OWNER_PERMS


# =============================================================================
# AD-8. Permission Category Classification (spec/007 Rev.5.1 + spec/008)
# =============================================================================
#
# Partitions the Permission enum into four disjoint categories so that:
#   * test scaffolding can iterate "all permissions an endpoint should back"
#     without re-listing the enum,
#   * the frontend permissions binding (FRONTEND_PROJECT_PERMISSIONS) has a
#     single source of truth, and
#   * structural assertions fail at import time if a new permission is added
#     without classifying it.
#
# Category semantics:
#   ENDPOINT_BACKED_PERMISSIONS — granted/denied per Action; an endpoint
#     advertises the permission via Action.required_permission.
#   COMPUTED_ONLY_PERMISSIONS — never appears on an endpoint as a required
#     permission; consumed solely by the response filter / stage-2 resolution
#     (e.g. VIEW_PRECISE_LOCATION).
#   USER_SCOPE_PERMISSIONS — judged on the user (not the project); does NOT
#     participate in the Canonical Matrix. NOTE (AD-8): this differs from the
#     pre-AD-8 USER_SCOPE_PERMISSIONS definition above which also contained
#     SEARCH_CROSS_PROJECT — spec/007 §AD-8 re-categorises SEARCH_CROSS_PROJECT
#     as ENDPOINT_BACKED because its grant is project-context-dependent
#     (Authenticated on Public gets it; Authenticated on Restricted does not).
#     The rebind below intentionally overwrites the earlier definition.
#   SUPERUSER_ONLY_PERMISSIONS — never granted to any project role; reachable
#     only via the superuser path.
#
# FRONTEND_PROJECT_PERMISSIONS — the subset the SvelteKit client binds for
# UI gating. Excludes SEARCH_CROSS_PROJECT (cross-project, not project-scoped)
# and the user-scope + superuser-only categories.

ENDPOINT_BACKED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
        Permission.VIEW_AUDIT_LOG,
        Permission.SEARCH_WITHIN_PROJECT,
        Permission.SEARCH_CROSS_PROJECT,
        Permission.DOWNLOAD,
        Permission.EXPORT,
        Permission.VOTE,
        Permission.COMMENT,
        Permission.CREATE_TAG,
        Permission.ANNOTATE,
        Permission.UPLOAD,
        Permission.MANAGE_DATASET,
        Permission.MANAGE_DATASET_ADMIN,
        Permission.RUN_INFERENCE,
        Permission.TRAIN_MODEL,
        Permission.MANAGE_MEMBERS,
        Permission.MANAGE_TRUSTED,
        Permission.EDIT_PROJECT,
        Permission.MANAGE_LICENSE,
        Permission.DELETE_PROJECT,
        Permission.TRANSFER_OWNERSHIP,
        # OVERRIDE_TAXON_SENSITIVITY — temporarily moved BACK to COMPUTED_ONLY
        # per spec/007 plan Rev.5.1 § Phase 2A.5 fallback. Backend audit
        # 2026-05-12: taxa.py exposes only /taxa/{search,gbif-search,{id}};
        # no submit/revoke override endpoint exists yet. Action registration
        # deferred to spec/008 follow-up. When the endpoints land,
        # TAXON_SENSITIVITY_OVERRIDE_{SUBMIT,REVOKE}_ACTION should be
        # registered and this permission moved back here.
    }
)

COMPUTED_ONLY_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PRECISE_LOCATION,
        # OVERRIDE_TAXON_SENSITIVITY — temporarily here until taxa override
        # endpoints land (see ENDPOINT_BACKED_PERMISSIONS comment above).
        Permission.OVERRIDE_TAXON_SENSITIVITY,
    }
)

# AD-8 rebind: USER_SCOPE_PERMISSIONS no longer includes SEARCH_CROSS_PROJECT
# (that permission is endpoint-backed and project-context-dependent). The
# earlier definition near the top of this module is intentionally shadowed.
USER_SCOPE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.MANAGE_API_KEY,
        Permission.MANAGE_2FA,
    }
)

SUPERUSER_ONLY_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.MANAGE_SITE,
    }
)

FRONTEND_PROJECT_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
        Permission.VIEW_AUDIT_LOG,
        Permission.SEARCH_WITHIN_PROJECT,
        Permission.VIEW_PRECISE_LOCATION,
        Permission.DOWNLOAD,
        Permission.EXPORT,
        Permission.VOTE,
        Permission.COMMENT,
        Permission.CREATE_TAG,
        Permission.ANNOTATE,
        Permission.UPLOAD,
        Permission.MANAGE_DATASET,
        Permission.MANAGE_DATASET_ADMIN,
        Permission.RUN_INFERENCE,
        Permission.TRAIN_MODEL,
        Permission.MANAGE_MEMBERS,
        Permission.MANAGE_TRUSTED,
        Permission.EDIT_PROJECT,
        Permission.MANAGE_LICENSE,
        Permission.DELETE_PROJECT,
        Permission.TRANSFER_OWNERSHIP,
        Permission.OVERRIDE_TAXON_SENSITIVITY,
    }
)

# --- Structural safety nets (run at import time) ----------------------------
# These fail loud if a new Permission member is added without classifying it,
# or if the partition invariant is broken.
assert FRONTEND_PROJECT_PERMISSIONS.issubset(
    ENDPOINT_BACKED_PERMISSIONS | COMPUTED_ONLY_PERMISSIONS
), "FRONTEND_PROJECT_PERMISSIONS contains a permission outside endpoint+computed"
assert Permission.SEARCH_CROSS_PROJECT not in FRONTEND_PROJECT_PERMISSIONS, (
    "SEARCH_CROSS_PROJECT is cross-project — must not appear in the per-project "
    "frontend binding"
)
assert set(Permission) == (
    ENDPOINT_BACKED_PERMISSIONS
    | COMPUTED_ONLY_PERMISSIONS
    | USER_SCOPE_PERMISSIONS
    | SUPERUSER_ONLY_PERMISSIONS
), (
    "Permission categories do not cover the full Permission enum — "
    "a new permission was added without classifying it"
)
# Pairwise disjoint check.
_categories: list[frozenset[Permission]] = [
    ENDPOINT_BACKED_PERMISSIONS,
    COMPUTED_ONLY_PERMISSIONS,
    USER_SCOPE_PERMISSIONS,
    SUPERUSER_ONLY_PERMISSIONS,
]
for _i, _a in enumerate(_categories):
    for _b in _categories[_i + 1:]:
        assert _a.isdisjoint(_b), "Permission categories must be pairwise disjoint"
del _categories, _i, _a, _b


# =============================================================================
# T040g. Helper functions (resolve_role, normalize_role, toggle maps)
# =============================================================================

# Restricted-toggle → Permission maps (spec §Restricted Toggle).
# Split by audience to avoid FR-017a regression (Guest never gains DL/EXPORT/
# VOTE/COMMENT/SEARCH via toggles).

_RESTRICTED_TOGGLE_PERMS_GUEST: Mapping[str, frozenset[Permission]] = MappingProxyType(
    {
        "allow_media_playback": frozenset({Permission.VIEW_MEDIA}),
        "allow_detection_view": frozenset({Permission.VIEW_DETECTION}),
    }
)

_RESTRICTED_TOGGLE_PERMS_AUTHENTICATED: Mapping[str, frozenset[Permission]] = MappingProxyType(
    {
        "allow_media_playback": frozenset({Permission.VIEW_MEDIA}),
        "allow_detection_view": frozenset({Permission.VIEW_DETECTION}),
        "allow_download": frozenset({Permission.DOWNLOAD}),
        "allow_export": frozenset({Permission.EXPORT}),
        "allow_voting_and_comments": frozenset({Permission.VOTE, Permission.COMMENT}),
    }
)


def permissions_from_toggles_for_guest(
    restricted_config: Mapping[str, Any],
) -> frozenset[Permission]:
    """FR-017a: Guest-visible permissions from Restricted toggles."""
    granted: set[Permission] = set()
    for toggle, perms in _RESTRICTED_TOGGLE_PERMS_GUEST.items():
        if restricted_config.get(toggle, False):
            granted |= perms
    return frozenset(granted)


def permissions_from_toggles_for_authenticated(
    restricted_config: Mapping[str, Any],
) -> frozenset[Permission]:
    """Spec §Restricted Toggle map for Authenticated principals."""
    granted: set[Permission] = set()
    for toggle, perms in _RESTRICTED_TOGGLE_PERMS_AUTHENTICATED.items():
        if restricted_config.get(toggle, False):
            granted |= perms
    return frozenset(granted)


def resolve_role(user: Any, project: Any) -> str:
    """Compute the principal's raw (non-normalised) role string.

    This does NOT touch the DB — the caller is expected to have looked up the
    ProjectMember row and set ``user.project_role`` (or similar) upstream. The
    function simply maps that lookup to the canonical string.

    Returns one of ``{"Guest", "Authenticated", "Viewer", "Member", "Admin",
    "Owner"}``. Superuser is never returned (handled separately by
    ``is_allowed``).
    """
    if user is None:
        return "Guest"

    # Owner short-circuit: project.owner_id == user.id
    user_id = getattr(user, "id", None)
    owner_id = getattr(project, "owner_id", None)
    if user_id is not None and owner_id is not None and user_id == owner_id:
        return "Owner"

    # The upstream resolver populates user.project_role as a role enum or str.
    raw = getattr(user, "project_role", None)
    if raw is None:
        return "Authenticated"

    role = raw.value if isinstance(raw, (ComputedRole, ProjectMemberRole)) else str(raw).lower()

    return {
        "viewer": "Viewer",
        "member": "Member",
        "admin": "Admin",
        "owner": "Owner",
    }.get(role, "Authenticated")


def normalize_role(raw_role: str, project: Any) -> str:
    """FR-004 / FR-007: normalise Public + Viewer → Authenticated.

    Pure function. Callers pass the result of ``resolve_role`` (or an already-
    known role string) and the project's visibility is consulted here so the
    algorithm is uniform between ``compute_effective_permissions`` and
    ``compute_effective_resolution``.
    """
    visibility = getattr(project, "visibility", None)
    if visibility == ProjectVisibility.PUBLIC and raw_role == "Viewer":
        return "Authenticated"
    return raw_role


def active_trusted_capabilities(
    trusted_rows: list[Any] | None,
    *,
    now_utc: Any = None,
) -> frozenset[Permission]:
    """Extract active Trusted permissions from pre-loaded overlay rows.

    FR-044 says "capability is read from DB every request", but the DB read
    happens upstream — this function filters the row set by ``status=active``
    and ``expires_at > now``, then unions the ``granted_permissions`` arrays,
    then intersects with ``TRUSTED_ALLOWED_PERMISSIONS`` (FR-014 safety net).

    Args:
        trusted_rows: List of ProjectTrustedUser rows for the current (user,
            project) pair. May be None / empty.
        now_utc: Reference "now" for expiry evaluation. If None, all non-
            revoked rows with status=active are considered live.

    Returns:
        Frozenset of TRUSTED_ALLOWED_PERMISSIONS members actually granted.
    """
    if not trusted_rows:
        return frozenset()
    union: set[Permission] = set()
    for row in trusted_rows:
        status_val = getattr(row, "status", None)
        status_str = getattr(status_val, "value", status_val)
        if str(status_str) != "active":
            continue
        expires_at = getattr(row, "expires_at", None)
        if now_utc is not None and expires_at is not None and expires_at <= now_utc:
            continue
        granted = getattr(row, "granted_permissions", ()) or ()
        for perm in granted:
            try:
                union.add(perm if isinstance(perm, Permission) else Permission(perm))
            except ValueError:
                # FR-014: unknown permission names are silently dropped here.
                continue
    return frozenset(union) & TRUSTED_ALLOWED_PERMISSIONS


# =============================================================================
# T040e. compute_effective_permissions
# =============================================================================

def compute_effective_permissions(
    normalized_role: str,
    project: Any,
    *,
    trusted_capabilities: frozenset[Permission] = frozenset(),
    api_key_granted_permissions: frozenset[Permission] | None = None,
) -> frozenset[Permission]:
    """Stage-1 permission set (spec §Permission decision algorithm).

    Args:
        normalized_role: Output of ``normalize_role(resolve_role(...))``. One
            of the 6 principal strings.
        project: Project with ``visibility`` + ``restricted_config``.
        trusted_capabilities: Pre-filtered (allowlist applied) Trusted overlay.
            Only meaningful when normalized_role == "Authenticated".
        api_key_granted_permissions: If authentication used an API key, the
            key's scopes (already project-scoped upstream). ``None`` when
            authentication was session-based.

    Returns:
        Frozen effective permission set.
    """
    # --- Matrix base ---------------------------------------------------------
    base: set[Permission] = set()
    visibility: ProjectVisibility | None = getattr(project, "visibility", None)

    if normalized_role == "Guest":
        base |= {
            Permission.VIEW_PROJECT_METADATA,
            Permission.VIEW_DATASET_LIST,
        }
        if visibility == ProjectVisibility.PUBLIC:
            # FR-016: Public Guest always sees media + detection.
            base |= {Permission.VIEW_MEDIA, Permission.VIEW_DETECTION}
    elif normalized_role == "Authenticated":
        base |= {
            Permission.VIEW_PROJECT_METADATA,
            Permission.VIEW_DATASET_LIST,
        }
        if visibility == ProjectVisibility.PUBLIC:
            # FR-017: Public Authenticated gets the full non-member bundle.
            base |= {
                Permission.VIEW_MEDIA,
                Permission.VIEW_DETECTION,
                Permission.SEARCH_WITHIN_PROJECT,
                Permission.SEARCH_CROSS_PROJECT,
                Permission.DOWNLOAD,
                Permission.EXPORT,
                Permission.VOTE,
                Permission.COMMENT,
            }
        # Authenticated always gets SEARCH_CROSS_PROJECT user-scope right
        # (SC-exempt from matrix but still included here for convenience —
        # callers may also check USER_SCOPE_PERMISSIONS separately).
    elif normalized_role == "Viewer":
        base |= set(ROLE_PERMISSIONS[ComputedRole.VIEWER])
    elif normalized_role == "Member":
        base |= set(ROLE_PERMISSIONS[ComputedRole.MEMBER])
    elif normalized_role == "Admin":
        base |= set(ROLE_PERMISSIONS[ComputedRole.ADMIN])
    elif normalized_role == "Owner":
        base |= set(ROLE_PERMISSIONS[ComputedRole.OWNER])
    elif normalized_role == "Superuser":
        base |= set(_SUPERUSER_PERMS)
    # Unknown role: base stays empty (safe default).

    # --- Trusted overlay (Authenticated only, FR-015) ------------------------
    if normalized_role == "Authenticated" and trusted_capabilities:
        # Apply allowlist safety net a second time — defence in depth.
        base |= (trusted_capabilities & TRUSTED_ALLOWED_PERMISSIONS)

    # --- Restricted toggles --------------------------------------------------
    if visibility == ProjectVisibility.RESTRICTED:
        cfg = getattr(project, "restricted_config", None) or {}
        if normalized_role == "Guest":
            base |= permissions_from_toggles_for_guest(cfg)
        elif normalized_role == "Authenticated":
            base |= permissions_from_toggles_for_authenticated(cfg)
        elif (
            normalized_role == "Viewer"
            and cfg.get("allow_precise_location_to_viewer", False)
        ):
            # allow_precise_location_to_viewer is a capability toggle (not a
            # permission-set toggle).
            base |= {Permission.VIEW_PRECISE_LOCATION}

    # --- API key scope intersection (FR-079) ---------------------------------
    if api_key_granted_permissions is not None:
        base &= api_key_granted_permissions

    return frozenset(base)


# =============================================================================
# T040f. compute_effective_resolution
# =============================================================================

def compute_effective_resolution(
    *,
    resource: Any,
    role: str,
    project: Any,
    effective_permissions: frozenset[Permission] = frozenset(),
    taxon_sensitivity_map: Mapping[str, int] | None = None,
    override_map: Mapping[tuple[Any, str], Any] | None = None,
) -> int:
    """Stage-2 location resolution (spec §Permission decision algorithm).

    Steps A-E from spec.md:
      A) apply override.direction to compute ``effective_global_res``
      B) HIDDEN clamp (FR-035) — applied to ``effective_global_res``
      C) Member / Admin / Owner / Superuser return member resolution
      D) VIEW_PRECISE_LOCATION in effective → member resolution
      E) Non-member ceiling: Public always H3_RES_9, Restricted uses config

    Args:
        resource: Recording / Detection / Site with ``taxon_id`` +
            ``h3_index_member_resolution``.
        role: Already-normalised role string.
        project: Project with ``visibility`` + ``restricted_config``.
        effective_permissions: Output of ``compute_effective_permissions``.
        taxon_sensitivity_map: ``{taxon_id: H3 resolution}`` preloaded via
            ``WHERE taxon_id IN (...)`` (NFR-001a). Missing keys default to
            H3_RES_9 (OPEN). Resources without ``taxon_id`` do not get this
            taxon cap, so Site-only locations can reflect Restricted project
            precision values above H3_RES_9.
        override_map: ``{(project.id, taxon_id): ProjectTaxonSensitivityOverride}``
            preloaded bulk.

    Returns:
        H3 resolution. Taxon sensitivity values remain the discrete
        ``VALID_H3_RESOLUTIONS`` set; project precision can additionally
        return continuous Restricted public-location resolutions 3-15.
    """
    sensitivity_map = taxon_sensitivity_map or {}
    overrides = override_map or {}

    taxon_id = getattr(resource, "taxon_id", None)
    member_res = getattr(resource, "h3_index_member_resolution", H3_RES_15)
    global_res = (
        sensitivity_map.get(taxon_id, H3_RES_9)
        if taxon_id is not None
        else member_res
    )

    # --- Step A: resolve global post-override --------------------------------
    override = overrides.get((getattr(project, "id", None), taxon_id)) if taxon_id else None

    if override is not None:
        direction = getattr(override, "direction", None)
        status_val = getattr(override, "approval_status", None)
        # C2 fix: ORM column is ``sensitivity_h3_res`` per
        # ``ProjectTaxonSensitivityOverride.sensitivity_h3_res``. The earlier
        # name ``resolution`` was a docstring drift — using getattr against
        # the wrong name silently dropped every override row in the live API.
        override_res = getattr(override, "sensitivity_h3_res", None)

        if direction == TaxonOverrideDirection.LOOSER:
            # FR-034: looser replaces global only once approved.
            if status_val == TaxonOverrideApprovalStatus.APPLIED and override_res is not None:
                effective_global = override_res
            else:
                effective_global = global_res
        elif direction == TaxonOverrideDirection.STRICTER:
            # Stricter is always applied (no approval needed).
            if override_res is not None:
                effective_global = _min_resolution(global_res, override_res)
            else:
                effective_global = global_res
        else:
            effective_global = global_res
    else:
        effective_global = global_res

    # --- Step B: HIDDEN clamp (FR-035) ---------------------------------------
    if effective_global == H3_RES_2:
        return H3_RES_2

    # --- Step C: privileged roles see member precision -----------------------
    # Spec step C: Members / Admins / Owners / Superusers see the member
    # resolution exactly. ``effective_global`` has already been consumed by
    # the HIDDEN clamp above, which is the only filter that can reduce
    # precision for privileged principals.
    if role in ("Member", "Admin", "Owner", "Superuser"):
        return member_res

    # --- Step D: Trusted / Viewer-with-boost sees member precision -----------
    if Permission.VIEW_PRECISE_LOCATION in effective_permissions:
        return member_res

    # --- Step E: Non-member ceiling ------------------------------------------
    visibility = getattr(project, "visibility", None)
    if visibility == ProjectVisibility.PUBLIC:
        project_toggle_res = H3_RES_9
    else:
        cfg = getattr(project, "restricted_config", None) or {}
        project_toggle_res = _public_location_precision_h3_res(cfg)

    return _min_resolution(effective_global, project_toggle_res)


def _public_location_precision_h3_res(cfg: Mapping[str, Any]) -> int:
    """Return the Restricted public-location precision, defaulting to res 3."""
    value = cfg.get(
        "public_location_precision_h3_res",
        DEFAULT_PUBLIC_LOCATION_PRECISION_H3_RES,
    )
    if isinstance(value, int) and 3 <= value <= 15:
        return value
    return DEFAULT_PUBLIC_LOCATION_PRECISION_H3_RES


def _min_resolution(a: int, b: int) -> int:
    """Return the COARSER (lower-numbered) of two H3 resolutions.

    H3 resolution semantics: LOWER number = larger cell = coarser precision.
    So "min" in the privacy sense is the integer min.
    """
    return min(a, b)


# =============================================================================
# T040d. is_allowed — stage-1 gate
# =============================================================================

def is_allowed(
    *,
    action: Action,
    user: Any,
    project: Any | None,
    auth_method: str | None = None,  # noqa: ARG001 - reserved for Phase 3
    request: Any | None = None,
    trusted_capabilities: frozenset[Permission] = frozenset(),
    api_key_granted_permissions: frozenset[Permission] | None = None,
) -> tuple[bool, frozenset[Permission]]:
    """Stage-1 Permission gate (spec §Permission decision algorithm).

    Pure decision function — no DB access, no HTTP raise. The caller (a
    FastAPI dependency or middleware) is responsible for:

      * upstream DB lookups (project, member, trusted rows)
      * raising HTTPException on False
      * caching the returned set in ``request.state`` for Stage 2

    Steps (fixed, non-recursive):

        -1 API key universal veto for is_superuser_only actions
        0  authentication
        0a platform-scope action branch
        0b superuser project-scope allowlist branch
        0c superuser-only project-scope hard-fail
        1  archived projects reject mutating actions
        2  normalize_role
        3  compute_effective_permissions
        4  final membership check

    Returns:
        ``(allowed, effective_permissions)``.
    """
    # --- Step 0: authentication ---------------------------------------------
    # This function is pure — we trust the caller to have attached
    # ``user`` (None or an authenticated principal) already.
    if user is None and not _is_guest_action_permitted(action):
        return False, frozenset()

    # --- Step -1: API key universal veto for superuser-only actions ---------
    # FR-084 defence-in-depth (Phase 15 R4 — Codex R3 NO-GO fix):
    # ANY action flagged ``is_superuser_only=True`` MUST be unconditionally
    # denied for API-key principals, regardless of action scope (platform
    # vs project), regardless of whether the action name is on the
    # ``SUPERUSER_PROJECT_SCOPE_ALLOWLIST``, and regardless of whether the
    # API key happens to carry an ``EDIT_PROJECT`` (or any other) scope.
    #
    # Why this is necessary: the middleware (:mod:`echoroo.middleware.auth`)
    # stamps ``is_superuser=True`` from the live ``superusers`` table for
    # API-key authentication paths too (auth.py line 173-174). Without this
    # universal veto, a superuser-owned API key carrying an ``EDIT_PROJECT``
    # scope could fall through Steps 0b/0c (which only fail-closed for
    # non-superusers) and land in the Matrix path, where the Step-2 role
    # upgrade ("Superuser → Owner") combined with the Matrix's Owner-grants
    # would let ``EDIT_PROJECT`` survive the
    # ``api_key_granted_permissions`` intersection — green-lighting actions
    # like ``project.archive`` that must require session-level superuser
    # identity.
    #
    # Cookie/JWT session superusers (no ``_api_key_scopes`` attribute) are
    # unaffected and continue through Steps 0a/0b/0c unchanged.
    if action.is_superuser_only and getattr(user, "_api_key_scopes", None) is not None:
        _stash_state(request, effective=frozenset(), normalized_role="Authenticated")
        return False, frozenset()

    # --- Step 0a: platform-scope action -------------------------------------
    if action.is_platform_scope:
        # FR-084 defence-in-depth: API key principals MUST NOT be permitted
        # on superuser-only platform actions even when the owning user holds
        # ``is_superuser=True``.  The middleware stamps ``is_superuser`` from
        # the live ``superusers`` table for ALL authentication paths — including
        # API key paths — so ``_is_superuser(user)`` alone is insufficient to
        # block a superuser-owned API key from reaching this branch.
        # We therefore add an explicit veto: any caller that has the
        # ``_api_key_scopes`` attribute (stamped by ``_stamp_api_key_scopes``
        # in :mod:`echoroo.middleware.auth`) is an API-key principal and is
        # categorically denied platform-scope operations regardless of the
        # underlying user's superuser status.
        #
        # NOTE (R4): this veto is now redundant with the Step -1 universal
        # veto above (every platform-scope action in the catalog is also
        # flagged ``is_superuser_only=True``). Kept here for clarity and as
        # a second layer of defence-in-depth — should a future platform
        # action be added that is NOT ``is_superuser_only=True``, the
        # Step -1 universal veto would not catch it but this branch still
        # would. This branch must therefore remain authoritative for the
        # ``is_platform_scope`` decision.
        is_api_key_caller = getattr(user, "_api_key_scopes", None) is not None
        allowed = bool(user) and _is_superuser(user) and not is_api_key_caller
        effective = frozenset(_SUPERUSER_PERMS) if allowed else frozenset()
        _stash_state(request, effective=effective, normalized_role="Superuser" if allowed else "Guest")
        return allowed, effective

    # --- Step 0b: superuser project-scope allowlist -------------------------
    # FR-084 defence-in-depth: same veto as Step 0a. The middleware
    # (:mod:`echoroo.middleware.auth`) stamps ``is_superuser`` from the live
    # ``superusers`` table for ALL authentication paths — including API key
    # paths — so ``_is_superuser(user)`` alone would otherwise let a
    # superuser-owned API key short-circuit through this allowlist
    # (e.g. ``project.archive`` / ``project.restore``). We therefore
    # require the caller to be a non-API-key principal here. API-key
    # callers fall through to the normal Matrix path so the request can
    # still succeed under regular project-role permissions if the API
    # key's intersected scopes happen to grant the underlying permission.
    #
    # NOTE (R4): all members of ``SUPERUSER_PROJECT_SCOPE_ALLOWLIST`` are
    # ``is_superuser_only=True``, so the Step -1 universal veto already
    # blocks API-key callers from reaching this branch. The
    # ``_api_key_scopes is None`` clause below is therefore redundant for
    # the current allowlist but is kept to preserve the local invariant
    # ("Step 0b never honours an API-key principal") in case the allowlist
    # ever grows to include a non-``is_superuser_only`` action.
    if (
        user is not None
        and _is_superuser(user)
        and getattr(user, "_api_key_scopes", None) is None
        and action.name in SUPERUSER_PROJECT_SCOPE_ALLOWLIST
    ):
        effective = frozenset(_SUPERUSER_PERMS)
        _stash_state(request, effective=effective, normalized_role="Superuser")
        return True, effective
        # Superusers without allowlist membership (or API-key principals)
        # fall through to the normal path below — they effectively map to
        # Owner on the target project (FR-112a), but still go through the
        # Matrix + Response filter.

    # --- Step 0c: superuser-only project-scope hard-fail (Phase 12 R1 C1) ----
    # Project-scope actions flagged ``is_superuser_only=True`` MUST never
    # reach the Matrix path: an Owner that holds the action's nominal
    # ``required_permission`` (e.g. EDIT_PROJECT) would otherwise pass
    # the Step-4 Matrix check and execute the action without proving
    # superuser status. We fail closed here so a non-superuser caller
    # cannot escalate via a project-role coincidence.
    if action.is_superuser_only and not (user is not None and _is_superuser(user)):
        _stash_state(request, effective=frozenset(), normalized_role="Authenticated")
        return False, frozenset()

    # project is required for project-scope actions from here on.
    if project is None:
        return False, frozenset()

    # --- Step 1: archived block -----------------------------------------------
    if getattr(project, "status", None) == "archived" and action.is_mutating:
        _stash_state(request, effective=frozenset(), normalized_role="Authenticated")
        return False, frozenset()

    # --- Step 1a: Guest read block on non-Active projects ---------------------
    # Phase 5 polish round 2 (FR-016 / FR-018): Guests may only read Public +
    # Active projects. A Public project that has transitioned to
    # ``dormant`` or ``archived`` MUST NOT serve any read action (including
    # ``recording.audio`` / ``recording.list``) to a signed-out caller.
    # This is the central enforcement point — endpoint handlers no longer
    # need ad-hoc status checks.
    if user is None and getattr(project, "status", None) != "active":
        _stash_state(request, effective=frozenset(), normalized_role="Guest")
        return False, frozenset()

    # --- Step 2: normalise role ----------------------------------------------
    raw_role = resolve_role(user, project) if user is not None else "Guest"
    normalized = normalize_role(raw_role, project)

    # FR-112b (spec Rev.3.3): non-member superuser project-scope role mapping.
    # Superusers who reach Step 2 are by construction outside the Step 0b
    # allowlist (otherwise they would already have returned) and the action
    # is not `is_superuser_only` (otherwise Step 0c would have hard-failed).
    # Upgrade the normalized role to Owner so the Canonical Matrix grants
    # owner-equivalent project permissions. This is what makes admin tools
    # and operational debugging work on non-member projects regardless of
    # Public / Restricted visibility.
    #
    # Safety guards stacked on top of this upgrade:
    #   - FR-112a: Response filter still strips raw lat/lng and HIDDEN-clamps
    #     H3 even for the Superuser normalized role.
    #   - FR-084 / Step -1 / Step 0a-0c: API key superuser principals and
    #     `is_superuser_only` actions never reach this branch.
    #   - Step 1: archived projects still block mutating actions.
    # Audit-log enrichment for this code path is tracked as PHASE17_BACKLOG
    # section G (FR-112b follow-up); current code does not emit a
    # `platform_audit_log` entry on the upgrade.
    if user is not None and _is_superuser(user) and normalized not in {
        "Owner",
        "Admin",
    }:
        normalized = "Owner"

    # --- Step 3: compute effective permissions -------------------------------
    effective = compute_effective_permissions(
        normalized_role=normalized,
        project=project,
        trusted_capabilities=trusted_capabilities,
        api_key_granted_permissions=api_key_granted_permissions,
    )

    # --- Step 4: final check -------------------------------------------------
    required = action.required_permission
    # User-scope permissions (MANAGE_API_KEY / MANAGE_2FA / SEARCH_CROSS_PROJECT)
    # are Matrix-exempt. Any logged-in user has them (with the Guest exclusion
    # for SEARCH_CROSS_PROJECT already handled above).
    if required in USER_SCOPE_PERMISSIONS:
        allowed = user is not None
        if required == Permission.SEARCH_CROSS_PROJECT and normalized == "Guest":
            allowed = False
        # Phase 15 R3 NO-GO Major 1: API keys must NOT silently inherit
        # the caller's user-scope rights. A key issued with
        # ``scopes=("view_detection",)`` should not be able to mint a
        # second key (``MANAGE_API_KEY``) or pivot 2FA settings
        # (``MANAGE_2FA``) just because its owning user trivially holds
        # those user-scope permissions. Intersect the allow-bit with the
        # API key's persisted scopes when authentication used an API
        # key. ``None`` (session / JWT auth) preserves the legacy
        # behaviour bit-for-bit.
        if allowed and api_key_granted_permissions is not None:
            allowed = required in api_key_granted_permissions
    else:
        allowed = required in effective if required is not None else False

    _stash_state(request, effective=effective, normalized_role=normalized)
    return allowed, effective


# --- tiny helpers ------------------------------------------------------------

def _is_superuser(user: Any) -> bool:
    return bool(getattr(user, "is_superuser", False))


def _is_guest_action_permitted(action: Action) -> bool:
    """True when the action's semantic permits Guest (unauthenticated) access.

    Currently implemented as "no authentication needed if the required
    permission is reachable from the Guest matrix cell". Callers that need
    tighter control should set ``action.is_superuser_only=True`` explicitly.
    """
    return action.required_permission in {
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
    }


def _stash_state(
    request: Any | None,
    *,
    effective: frozenset[Permission],
    normalized_role: str,
) -> None:
    """Cache stage-1 decision into ``request.state`` for stage-2 consumption.

    No-op when called from unit tests without a request (NFR-008).
    """
    if request is None:
        return
    state = getattr(request, "state", None)
    if state is None:
        return
    try:
        state.effective_permissions = effective
        state.normalized_role = normalized_role
    except (AttributeError, TypeError):  # pragma: no cover - defensive
        return


# =============================================================================
# Legacy compatibility — used by Phase 2 routers until Phase 3 rewrite
# =============================================================================

async def load_project_or_404(db: AsyncSession, project_id: UUID) -> Project:
    """Load the Project ORM row needed by :func:`is_allowed`. 404 if absent."""
    project_result = await db.execute(sa_select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="project not found")
    return project


async def _resolve_project_member_role(
    db: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
) -> ProjectMemberRole | None:
    """Look up the caller's :class:`ProjectMember` role row for ``project_id``.

    Phase 7 polish round 3 (Major 1): :func:`is_allowed` consults
    ``user.project_role`` via :func:`resolve_role` to decide whether a
    caller is Member / Admin / Viewer. The attribute was previously never
    populated by ``gate_action`` so non-owner Admins fell through to the
    "Authenticated" cell of the matrix and lost their elevated permissions
    (notably ``MANAGE_LICENSE`` per FR-010). This helper performs the
    membership lookup once per request so the gate sees the right role.

    Returns the ``ProjectMemberRole`` enum value or ``None`` when the user
    is not a member (callers fall back to ``Authenticated`` / ``Guest``).
    """
    # Local import — keep ``ProjectMember`` out of the module import surface
    # so the permission engine keeps its "no SQLAlchemy session" purity at
    # the public-API level.
    from echoroo.models.project import ProjectMember

    result = await db.execute(
        sa_select(ProjectMember.role).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    if isinstance(row, ProjectMemberRole):
        return row
    # Some drivers surface the underlying Postgres enum string; coerce.
    try:
        return ProjectMemberRole(str(row).lower())
    except ValueError:
        return None


class _ScopedPrincipal:
    """Per-call principal view exposing a project-scoped ``project_role``.

    Phase 7 polish round 4 (Major 3): :func:`gate_action` previously stamped
    the resolved membership role directly onto ``current_user.project_role``.
    That mutation persists for the rest of the request — so a single
    request that gates two different projects (e.g. a controller that
    cascades into a sub-resource on another project) would carry the FIRST
    project's role into the SECOND ``is_allowed`` call. The leak escalated
    permissions (e.g. Admin on project A → Admin on project B for the same
    request) and was the highest-severity regression to surface from the
    Round 3 audit.

    The fix is structural: ``gate_action`` no longer touches the principal
    object. Instead, it wraps ``current_user`` in this thin view that
    proxies every attribute except ``project_role``, which it returns from
    a per-call value. ``resolve_role`` reads the freshly-resolved role
    without seeing any state from a sibling project.

    This keeps :func:`is_allowed` and :func:`resolve_role` unchanged
    (preserving the pure-function unit-test contract in
    ``tests/contract/test_permissions.py`` which constructs
    ``SimpleNamespace`` users with ``project_role`` set directly).
    """

    __slots__ = ("_inner", "_project_role")

    def __init__(self, inner: Any, project_role: Any) -> None:
        # ``object.__setattr__`` bypasses any ``__setattr__`` defined on
        # the wrapped principal (e.g. SQLAlchemy ORM listeners) — we are
        # only ever stashing the wrapper's own attributes here.
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_project_role", project_role)

    def __getattr__(self, item: str) -> Any:
        if item == "project_role":
            return self._project_role
        return getattr(self._inner, item)

    def __setattr__(self, item: str, value: Any) -> None:
        # The wrapper is read-only by contract. The only writable
        # attributes are the two declared in ``__slots__``, which are
        # populated via ``object.__setattr__`` in ``__init__``. Any other
        # write would silently leak back onto the wrapped principal —
        # exactly the regression we are guarding against.
        raise AttributeError(
            "_ScopedPrincipal is immutable — wrap a fresh instance instead "
            "of mutating a per-call view"
        )


class PermissionDecision:
    """Outcome of :func:`decide_action_permission`.

    Phase 17 backlog A-5 Round 2 R1-I1: split the decision logic shared
    by :func:`gate_action` (HTTP-time, raises ``HTTPException``) and
    :func:`echoroo.core.stream_guard.recheck_action_permission`
    (mid-stream, raises ``PermissionRevokedMidStream``) into a single
    public helper. Both callers MUST consult the same source of truth so
    drift is structurally impossible — when a future Phase adds another
    condition to the gate, both code paths pick it up automatically.

    Attributes:
        allowed: Final allow / deny decision after the entire algorithm.
        project: The :class:`Project` row that was loaded (or ``None`` if
            the project no longer exists; used by the mid-stream guard
            to terminate with the dedicated ``project_missing`` reason).
        reason: When ``allowed=False``, a stable machine-readable code
            (``project_missing`` / ``api_key_project_scope_mismatch`` /
            ``api_key_revoked`` / ``action_denied``). Empty string on
            allow. The HTTP gate maps this to a ``detail`` message; the
            mid-stream guard maps it to ``PermissionRevokedMidStream``.
    """

    __slots__ = ("allowed", "project", "reason")

    def __init__(
        self,
        *,
        allowed: bool,
        project: Project | None,
        reason: str,
    ) -> None:
        self.allowed = allowed
        self.project = project
        self.reason = reason


async def decide_action_permission(
    *,
    db: AsyncSession,
    action: Action,
    project_id: UUID,
    current_user: Any,
    request: Request,
    refresh_api_key_scopes: bool = False,
) -> PermissionDecision:
    """Compute the gate decision for ``action`` on ``project_id``.

    This is the single source of truth shared by :func:`gate_action`
    (HTTP-time entry) and
    :func:`echoroo.core.stream_guard.recheck_action_permission`
    (post-start mid-stream re-evaluation).

    Steps (kept identical to the previous in-line implementation in
    :func:`gate_action`):

      1. API-key project-binding scope check.
      2. ``Project`` row load (with ``populate_existing=True`` when
         re-checking mid-stream so the identity-map cache does not hide
         a sibling-session UPDATE).
      3. Membership role resolve (non-owners) → per-call
         :class:`_ScopedPrincipal` wrapper.
      4. Trusted overlay re-fetch (only for Authenticated non-member,
         non-superuser principals — FR-041).
      5. API-key scope translation. When ``refresh_api_key_scopes=True``
         the ``ApiKey`` row is re-loaded from the DB so a sibling-session
         revoke or scope shrink is observed (used by the mid-stream
         guard). When ``False`` (HTTP-time path) the scopes already
         stamped on ``current_user._api_key_scopes`` by the auth
         middleware are used — re-loading every request would be a
         wasted SELECT.
      6. :func:`is_allowed` over the refreshed inputs.

    Returns:
        A :class:`PermissionDecision`. The caller decides the failure
        mode (``HTTPException`` vs ``PermissionRevokedMidStream``).
    """
    # --- Step 1: API-key project-binding scope ------------------------------
    # Phase 15 R3 NO-GO new-Major: enforce per-key project binding BEFORE
    # any DB lookup so a mismatched key cannot probe the existence of
    # arbitrary projects (FR-079 / FR-099 anti-enumeration).
    bound_project_id = getattr(current_user, "_api_key_project_id", None)
    if bound_project_id is not None and bound_project_id != project_id:
        return PermissionDecision(
            allowed=False,
            project=None,
            reason="api_key_project_scope_mismatch",
        )

    # --- Step 2: load project (mid-stream path bypasses identity-map) -------
    project: Project | None
    if refresh_api_key_scopes:
        # Mid-stream re-check: bypass the request-scoped identity map so
        # a sibling-session UPDATE / DELETE is observed.
        result = await db.execute(
            sa_select(Project)
            .where(Project.id == project_id)
            .execution_options(populate_existing=True)
        )
        project = result.scalar_one_or_none()
        if project is None:
            return PermissionDecision(
                allowed=False,
                project=None,
                reason="project_missing",
            )
    else:
        # HTTP-time path: keep the legacy 404 contract via load_project_or_404.
        project = await load_project_or_404(db, project_id)

    # --- Step 3: membership role + ScopedPrincipal wrap ---------------------
    principal: Any = current_user
    trusted_capabilities: frozenset[Permission] = frozenset()
    membership_role: ProjectMemberRole | None = None

    is_owner = (
        current_user is not None
        and getattr(current_user, "id", None) is not None
        and getattr(project, "owner_id", None) == current_user.id
    )
    if (
        current_user is not None
        and getattr(current_user, "id", None) is not None
        and not is_owner
    ):
        membership_role = await _resolve_project_member_role(
            db, project_id=project_id, user_id=current_user.id
        )
        if membership_role is not None:
            principal = _ScopedPrincipal(current_user, membership_role)

    # --- Step 4: trusted overlay (Authenticated non-member non-superuser) ---
    if (
        current_user is not None
        and getattr(current_user, "id", None) is not None
        and not is_owner
        and membership_role is None
        and not _is_superuser(current_user)
    ):
        # Local import to avoid a circular import at module load time
        # (trusted_service imports from echoroo.core.permissions).
        from echoroo.services.trusted_service import (
            get_active_trusted_capabilities,
        )

        trusted_capabilities = await get_active_trusted_capabilities(
            db, user_id=current_user.id, project_id=project_id
        )

    # --- Step 5: API-key scopes (fresh DB load for mid-stream path) ---------
    api_key_granted: frozenset[Permission] | None = None
    if refresh_api_key_scopes:
        # Local import to avoid a circular import at module load time
        # (stream_guard imports from echoroo.core.permissions).
        from echoroo.core.stream_guard import _refresh_api_key_scopes

        revoked, refreshed_api_scopes = await _refresh_api_key_scopes(
            db, current_user=current_user
        )
        if revoked:
            return PermissionDecision(
                allowed=False,
                project=project,
                reason="api_key_revoked",
            )
        api_key_granted = refreshed_api_scopes
    else:
        # Phase 15 NO-GO Major 1: read the scopes stamped on the user
        # at auth time. Unknown scope names are silently dropped
        # (forward-compatible with newly added permissions on older
        # clients) — the safe default is "deny".
        raw_scopes = getattr(current_user, "_api_key_scopes", None)
        if raw_scopes is not None:
            translated: set[Permission] = set()
            for scope in raw_scopes:
                try:
                    translated.add(
                        scope if isinstance(scope, Permission) else Permission(scope)
                    )
                except ValueError:
                    continue
            api_key_granted = frozenset(translated)

    # --- Step 6: is_allowed ------------------------------------------------
    allowed, _ = is_allowed(
        action=action,
        user=principal,
        project=project,
        request=request,
        trusted_capabilities=trusted_capabilities,
        api_key_granted_permissions=api_key_granted,
    )
    if not allowed:
        return PermissionDecision(
            allowed=False,
            project=project,
            reason="action_denied",
        )
    return PermissionDecision(allowed=True, project=project, reason="")


async def gate_action(
    *,
    action: Action,
    project_id: UUID,
    current_user: Any,
    request: Request,
    db: AsyncSession,
) -> Project:
    """Run the Stage-1 :func:`is_allowed` gate for ``action`` on ``project_id``.

    Returns the loaded :class:`Project` row so callers can pass it through to
    the service layer without issuing a second SELECT.

    Phase 7 polish round 4 (Major 3): the caller's project membership row
    is looked up here and exposed via a per-call :class:`_ScopedPrincipal`
    wrapper so :func:`resolve_role` returns the correct cell of the
    canonical matrix (Admin / Member / Viewer) rather than collapsing to
    Authenticated. Owners short-circuit before this lookup via the
    ``project.owner_id`` branch in :func:`resolve_role`, so the extra
    SELECT only fires for non-owners and scales linearly with concurrency.

    The wrapper is the load-bearing change relative to Round 3: prior
    versions mutated ``current_user.project_role`` in-place which leaked
    the role onto sibling-project ``gate_action`` / ``is_allowed`` calls
    later in the same request. The wrapper is per-call, so cross-project
    leakage is structurally impossible.

    Phase 17 backlog A-5 Round 2 R1-I1: the entire decision algorithm
    now lives in :func:`decide_action_permission`. ``gate_action`` is
    the HTTP adaptor — it translates the deny reason to an
    ``HTTPException`` so existing routers keep their contract. The
    mid-stream guard
    (:func:`echoroo.core.stream_guard.recheck_action_permission`) calls
    the same helper and translates the same deny reason to
    ``PermissionRevokedMidStream``.
    """
    decision = await decide_action_permission(
        db=db,
        action=action,
        project_id=project_id,
        current_user=current_user,
        request=request,
        refresh_api_key_scopes=False,
    )
    if not decision.allowed:
        if decision.reason == "api_key_project_scope_mismatch":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="api_key_project_scope_mismatch",
            )
        # ``project_missing`` is unreachable here because
        # ``decide_action_permission`` calls ``load_project_or_404``
        # for the HTTP-time path which already raises 404. Defence in
        # depth: surface a 404 if it ever does come through.
        if decision.reason == "project_missing":
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail="project not found",
            )
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="action denied")
    # ``decision.project`` is guaranteed non-None on the success path
    # because ``load_project_or_404`` would otherwise have raised 404.
    assert decision.project is not None
    return decision.project


async def check_project_access(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> None:
    """Legacy: verify the current user has access to the given project.

    This predates the 006 permissions redesign. Phase 3 (T100+) replaces every
    caller with ``Depends(check_action(...))`` which invokes ``is_allowed``
    directly. Until then the routers keep importing this symbol.

    Raises HTTPException 403 when the user is not a project member / owner.
    """
    # Local import to avoid a heavy import cycle at module load time.
    from echoroo.repositories.project import ProjectRepository

    project_repo = ProjectRepository(db)
    has_access = await project_repo.has_project_access(project_id, user_id)
    if not has_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to project",
        )


__all__ = [
    # enums / constants
    "ACTIONS",
    "Action",
    "COMPUTED_ONLY_PERMISSIONS",
    "ComputedRole",
    "ENDPOINT_BACKED_PERMISSIONS",
    "FRONTEND_PROJECT_PERMISSIONS",
    "H3_RES_15",
    "H3_RES_2",
    "H3_RES_5",
    "H3_RES_7",
    "H3_RES_9",
    "Permission",
    "PermissionDecision",
    "ProjectVisibility",
    "ROLE_PERMISSIONS",
    "SUPERUSER_ONLY_PERMISSIONS",
    "SUPERUSER_PROJECT_SCOPE_ALLOWLIST",
    "TRUSTED_ALLOWED_PERMISSIONS",
    "TaxonOverrideApprovalStatus",
    "TaxonOverrideDirection",
    "USER_SCOPE_PERMISSIONS",
    "VALID_H3_RESOLUTIONS",
    # engine
    "active_trusted_capabilities",
    "check_project_access",
    "compute_effective_permissions",
    "compute_effective_resolution",
    "decide_action_permission",
    "gate_action",
    "is_allowed",
    "load_project_or_404",
    "normalize_role",
    "permissions_from_toggles_for_authenticated",
    "permissions_from_toggles_for_guest",
    "register_action",
    "resolve_role",
]
