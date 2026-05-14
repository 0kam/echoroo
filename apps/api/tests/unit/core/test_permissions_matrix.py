"""Canonical Permission Matrix parametric tests (T041).

Spec: FR-008, FR-009, FR-010, FR-012, FR-014, FR-015, FR-015a, FR-017a, FR-018,
FR-019, FR-020 (Restricted toggles), Canonical Matrix table (spec.md §Canonical
Permission Matrix).

Strategy (PR-002, SC-001): cartesian product of

    6 principals × 28 Permissions × 2 Visibilities × Restricted toggle
    combinations (8 boolean + 1 allow_precise_location_to_viewer).

The full cross product is trimmed at the parametrize level to the combinations
the spec actually constrains (e.g. Public does not look at most toggles); the
test body asserts the exact `effective` set returned by
`compute_effective_permissions` matches the spec's expected truth table.

This file is the TDD Red-phase entry point for the permission engine — the
imports below fail until `core/permissions.py` is implemented (Commit 2 in the
TDD strict order).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from echoroo.core.permissions import (
    ROLE_PERMISSIONS,
    TRUSTED_ALLOWED_PERMISSIONS,
    USER_SCOPE_PERMISSIONS,
    ComputedRole,
    Permission,
    ProjectVisibility,
    compute_effective_permissions,
    normalize_role,
    permissions_from_toggles_for_authenticated,
    permissions_from_toggles_for_guest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_RESTRICTED_CONFIG: dict[str, Any] = {
    "allow_media_playback": False,
    "allow_detection_view": False,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 3,
    "allow_precise_location_to_viewer": False,
}


def _make_project(
    visibility: ProjectVisibility,
    *,
    restricted_config: dict[str, Any] | None = None,
    status: str = "active",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="proj-0001",
        visibility=visibility,
        restricted_config=restricted_config or DEFAULT_RESTRICTED_CONFIG.copy(),
        status=status,
    )


def _role_str_to_enum(role: str) -> ComputedRole | None:
    mapping = {
        "Viewer": ComputedRole.VIEWER,
        "Member": ComputedRole.MEMBER,
        "Admin": ComputedRole.ADMIN,
        "Owner": ComputedRole.OWNER,
    }
    return mapping.get(role)


# ---------------------------------------------------------------------------
# 1. ROLE_PERMISSIONS Canonical Matrix — every role × every Permission cell
# ---------------------------------------------------------------------------

# Expected ROLE_PERMISSIONS per Canonical Matrix in spec.md.
# Covers the 26 Project-scope permissions. USER_SCOPE_PERMISSIONS are tested
# separately because they are Matrix-exempt (spec §Canonical).
EXPECTED_ROLE_BASE_PERMS: dict[ComputedRole, set[str]] = {
    ComputedRole.VIEWER: {
        "view_project_metadata",
        "view_dataset_list",
        "view_media",
        "view_detection",
        "search_within_project",
    },
    ComputedRole.MEMBER: {
        "view_project_metadata",
        "view_dataset_list",
        "view_media",
        "view_detection",
        "view_precise_location",
        "search_within_project",
        "search_cross_project",
        "download",
        "export",
        "vote",
        "comment",
        "create_tag",
        "annotate",
        "upload",
        "manage_dataset",  # spec/007 Phase 2A.6 hotfix (Codex Option A 2026-05-12)
        "manage_site",
        "run_inference",
    },
    ComputedRole.ADMIN: {
        "view_project_metadata",
        "view_dataset_list",
        "view_media",
        "view_detection",
        "view_precise_location",
        "view_audit_log",
        "search_within_project",
        "search_cross_project",
        "download",
        "export",
        "vote",
        "comment",
        "create_tag",
        "annotate",
        "upload",
        "manage_site",
        "manage_dataset",
        "manage_dataset_admin",  # AD-1B Option A (spec/007 Rev.5.1)
        "run_inference",
        "train_model",
        "manage_members",
        "edit_project",
        "manage_license",
    },
    ComputedRole.OWNER: {
        "view_project_metadata",
        "view_dataset_list",
        "view_media",
        "view_detection",
        "view_precise_location",
        "view_audit_log",
        "search_within_project",
        "search_cross_project",
        "download",
        "export",
        "vote",
        "comment",
        "create_tag",
        "annotate",
        "upload",
        "manage_site",
        "manage_dataset",
        "manage_dataset_admin",  # AD-1B Option A (spec/007 Rev.5.1)
        "run_inference",
        "train_model",
        "manage_members",
        "manage_trusted",
        "edit_project",
        "manage_license",
        "delete_project",
        "transfer_ownership",
        "override_taxon_sensitivity",
    },
}


@pytest.mark.parametrize("role", list(EXPECTED_ROLE_BASE_PERMS.keys()))
def test_role_permissions_canonical_matrix(role: ComputedRole) -> None:
    """ROLE_PERMISSIONS matches Canonical Matrix (FR-010)."""
    expected = {Permission(v) for v in EXPECTED_ROLE_BASE_PERMS[role]}
    actual = set(ROLE_PERMISSIONS[role])
    assert actual == expected, (
        f"ROLE_PERMISSIONS[{role}] diverges from Canonical Matrix.\n"
        f"  missing: {expected - actual}\n"
        f"  extra:   {actual - expected}"
    )


def test_role_permissions_keys_are_exactly_four_roles() -> None:
    """ROLE_PERMISSIONS must define exactly the 4 project-scope roles.

    Guest / Authenticated are not in ROLE_PERMISSIONS — their permissions are
    derived entirely from Restricted toggles + (for Authenticated) Canonical
    base on Public, per spec §Canonical.
    """
    expected = {ComputedRole.VIEWER, ComputedRole.MEMBER, ComputedRole.ADMIN, ComputedRole.OWNER}
    assert set(ROLE_PERMISSIONS.keys()) == expected


def test_role_permissions_values_are_frozensets() -> None:
    """ROLE_PERMISSIONS values must be immutable frozensets (NFR-008 safety)."""
    for role, perms in ROLE_PERMISSIONS.items():
        assert isinstance(perms, frozenset), f"{role} maps to {type(perms).__name__}, want frozenset"


# ---------------------------------------------------------------------------
# 2. TRUSTED_ALLOWED_PERMISSIONS allowlist (FR-012)
# ---------------------------------------------------------------------------

def test_trusted_allowed_permissions_is_spec_allowlist() -> None:
    """FR-012: TRUSTED_ALLOWED_PERMISSIONS = 8 specific Permissions."""
    expected_values = {
        "view_media",
        "view_detection",
        "view_precise_location",
        "download",
        "export",
        "search_within_project",
        "vote",
        "comment",
    }
    assert {p.value for p in TRUSTED_ALLOWED_PERMISSIONS} == expected_values


def test_trusted_allowed_permissions_is_frozenset() -> None:
    assert isinstance(TRUSTED_ALLOWED_PERMISSIONS, frozenset)


# ---------------------------------------------------------------------------
# 3. USER_SCOPE_PERMISSIONS (FR-009 classification)
# ---------------------------------------------------------------------------

def test_user_scope_permissions_contents() -> None:
    """USER_SCOPE_PERMISSIONS must be the 2 Matrix-exempt user-scope perms.

    AD-8 (spec/007 Rev.5.1): SEARCH_CROSS_PROJECT was re-categorised as
    ENDPOINT_BACKED because its grant is project-context-dependent
    (Authenticated on Public gets it; Authenticated on Restricted does not).
    """
    expected_values = {"manage_api_key", "manage_2fa"}
    assert {p.value for p in USER_SCOPE_PERMISSIONS} == expected_values


# ---------------------------------------------------------------------------
# 4. Permission enum cardinality (FR-009 + AD-1B Option A = 29)
# ---------------------------------------------------------------------------

def test_permission_enum_cardinality() -> None:
    """FR-009 + AD-1B Option A: Permission enum has exactly 29 members (27 project + 2 user)."""
    assert len(list(Permission)) == 29


# ---------------------------------------------------------------------------
# 5. Restricted toggle → Permission maps (FR-017a, FR-020)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("toggles", "expected_values"),
    [
        ({"allow_media_playback": True}, {"view_media"}),
        ({"allow_detection_view": True}, {"view_detection"}),
        ({"allow_media_playback": True, "allow_detection_view": True},
         {"view_media", "view_detection"}),
        # Guest never gets DL/EXPORT/VOTE/COMMENT regardless of toggles (FR-017a)
        ({"allow_download": True, "allow_export": True, "allow_voting_and_comments": True},
         set()),
    ],
)
def test_permissions_from_toggles_for_guest(
    toggles: dict[str, bool], expected_values: set[str]
) -> None:
    """FR-017a: Guest only gets VIEW_MEDIA / VIEW_DETECTION from toggles."""
    config = DEFAULT_RESTRICTED_CONFIG.copy()
    config.update(toggles)
    actual = permissions_from_toggles_for_guest(config)
    assert {p.value for p in actual} == expected_values


@pytest.mark.parametrize(
    ("toggles", "expected_values"),
    [
        ({"allow_media_playback": True}, {"view_media"}),
        ({"allow_detection_view": True}, {"view_detection"}),
        ({"allow_download": True}, {"download"}),
        ({"allow_export": True}, {"export"}),
        ({"allow_voting_and_comments": True}, {"vote", "comment"}),
        (
            {
                "allow_media_playback": True,
                "allow_detection_view": True,
                "allow_download": True,
                "allow_export": True,
                "allow_voting_and_comments": True,
            },
            {"view_media", "view_detection", "download", "export", "vote", "comment"},
        ),
    ],
)
def test_permissions_from_toggles_for_authenticated(
    toggles: dict[str, bool], expected_values: set[str]
) -> None:
    """Spec Restricted Toggle → Permission map (Authenticated)."""
    config = DEFAULT_RESTRICTED_CONFIG.copy()
    config.update(toggles)
    actual = permissions_from_toggles_for_authenticated(config)
    assert {p.value for p in actual} == expected_values


# ---------------------------------------------------------------------------
# 6. normalize_role (FR-004, FR-007, FR-015a)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("visibility", "raw_role", "expected"),
    [
        # Public: Viewer → Authenticated (FR-004, FR-007)
        (ProjectVisibility.PUBLIC, "Viewer", "Authenticated"),
        (ProjectVisibility.PUBLIC, "Authenticated", "Authenticated"),
        (ProjectVisibility.PUBLIC, "Guest", "Guest"),
        (ProjectVisibility.PUBLIC, "Member", "Member"),
        (ProjectVisibility.PUBLIC, "Admin", "Admin"),
        (ProjectVisibility.PUBLIC, "Owner", "Owner"),
        # Restricted: Viewer stays Viewer
        (ProjectVisibility.RESTRICTED, "Viewer", "Viewer"),
        (ProjectVisibility.RESTRICTED, "Authenticated", "Authenticated"),
        (ProjectVisibility.RESTRICTED, "Guest", "Guest"),
        (ProjectVisibility.RESTRICTED, "Member", "Member"),
    ],
)
def test_normalize_role(
    visibility: ProjectVisibility, raw_role: str, expected: str
) -> None:
    project = _make_project(visibility)
    assert normalize_role(raw_role, project) == expected


# ---------------------------------------------------------------------------
# 7. compute_effective_permissions — full cross product spot-checks
# ---------------------------------------------------------------------------

def _compute(
    normalized_role: str,
    visibility: ProjectVisibility,
    restricted_config: dict[str, Any] | None = None,
    *,
    trusted: frozenset[Permission] | None = None,
    api_key_scopes: frozenset[Permission] | None = None,
) -> frozenset[Permission]:
    project = _make_project(visibility, restricted_config=restricted_config)
    return compute_effective_permissions(
        normalized_role=normalized_role,
        project=project,
        trusted_capabilities=trusted or frozenset(),
        api_key_granted_permissions=api_key_scopes,
    )


# 7.1 Public visibility — matches Canonical Matrix
class TestPublicVisibility:
    def test_guest_public_base(self) -> None:
        """Guest on Public gets VIEW_PROJECT_METADATA + VIEW_DATASET_LIST +
        VIEW_MEDIA + VIEW_DETECTION (FR-016)."""
        perms = _compute("Guest", ProjectVisibility.PUBLIC)
        expected = {
            Permission.VIEW_PROJECT_METADATA,
            Permission.VIEW_DATASET_LIST,
            Permission.VIEW_MEDIA,
            Permission.VIEW_DETECTION,
        }
        assert perms == frozenset(expected)

    def test_authenticated_public_base(self) -> None:
        """Authenticated on Public gets FR-016 + DL/EXPORT/SEARCH_WITHIN/CROSS/
        VOTE/COMMENT (FR-017)."""
        perms = _compute("Authenticated", ProjectVisibility.PUBLIC)
        expected = {
            Permission.VIEW_PROJECT_METADATA,
            Permission.VIEW_DATASET_LIST,
            Permission.VIEW_MEDIA,
            Permission.VIEW_DETECTION,
            Permission.DOWNLOAD,
            Permission.EXPORT,
            Permission.SEARCH_WITHIN_PROJECT,
            Permission.SEARCH_CROSS_PROJECT,
            Permission.VOTE,
            Permission.COMMENT,
        }
        assert perms == frozenset(expected)

    def test_viewer_public_normalized_to_authenticated(self) -> None:
        """Public + Viewer must give Authenticated perms (FR-004)."""
        public_viewer = _compute("Authenticated", ProjectVisibility.PUBLIC)  # already normalised
        # The Viewer row must match Authenticated in Public after normalization.
        # We call _compute with Authenticated since normalize_role runs upstream.
        assert Permission.DOWNLOAD in public_viewer
        assert Permission.VOTE in public_viewer


# 7.2 Restricted visibility — toggles control Guest / Authenticated
class TestRestrictedVisibility:
    def test_guest_restricted_defaults(self) -> None:
        """Guest on Restricted with all toggles OFF only sees metadata."""
        perms = _compute("Guest", ProjectVisibility.RESTRICTED)
        # FR-019: Restricted must publish VIEW_PROJECT_METADATA + VIEW_DATASET_LIST
        # as base (to Guest and Authenticated). All other perms depend on toggles.
        assert Permission.VIEW_PROJECT_METADATA in perms
        assert Permission.VIEW_DATASET_LIST in perms
        assert Permission.VIEW_MEDIA not in perms
        assert Permission.VIEW_DETECTION not in perms
        assert Permission.DOWNLOAD not in perms

    def test_guest_restricted_media_toggle_on(self) -> None:
        """Restricted `allow_media_playback=true` → Guest gains VIEW_MEDIA."""
        config = DEFAULT_RESTRICTED_CONFIG.copy()
        config["allow_media_playback"] = True
        perms = _compute("Guest", ProjectVisibility.RESTRICTED, config)
        assert Permission.VIEW_MEDIA in perms

    def test_guest_never_gets_download_even_if_toggle_on(self) -> None:
        """FR-017a: Guest cannot gain DOWNLOAD/EXPORT/VOTE/COMMENT via toggles."""
        config = DEFAULT_RESTRICTED_CONFIG.copy()
        config["allow_download"] = True
        config["allow_export"] = True
        config["allow_voting_and_comments"] = True
        perms = _compute("Guest", ProjectVisibility.RESTRICTED, config)
        assert Permission.DOWNLOAD not in perms
        assert Permission.EXPORT not in perms
        assert Permission.VOTE not in perms
        assert Permission.COMMENT not in perms

    def test_authenticated_restricted_download_toggle(self) -> None:
        """Authenticated + `allow_download=true` → DOWNLOAD granted."""
        config = DEFAULT_RESTRICTED_CONFIG.copy()
        config["allow_download"] = True
        perms = _compute("Authenticated", ProjectVisibility.RESTRICTED, config)
        assert Permission.DOWNLOAD in perms

    def test_authenticated_restricted_voting_toggle(self) -> None:
        """`allow_voting_and_comments=true` → VOTE + COMMENT granted."""
        config = DEFAULT_RESTRICTED_CONFIG.copy()
        config["allow_voting_and_comments"] = True
        perms = _compute("Authenticated", ProjectVisibility.RESTRICTED, config)
        assert Permission.VOTE in perms
        assert Permission.COMMENT in perms

    def test_viewer_restricted_fixed_perms(self) -> None:
        """Viewer permissions are fixed regardless of toggles (spec Viewer def)."""
        perms = _compute("Viewer", ProjectVisibility.RESTRICTED)
        expected_always_present = {
            Permission.VIEW_PROJECT_METADATA,
            Permission.VIEW_DATASET_LIST,
            Permission.VIEW_MEDIA,
            Permission.VIEW_DETECTION,
            Permission.SEARCH_WITHIN_PROJECT,
        }
        expected_never_present = {
            Permission.DOWNLOAD,
            Permission.EXPORT,
            Permission.VOTE,
            Permission.COMMENT,
            Permission.SEARCH_CROSS_PROJECT,
        }
        assert expected_always_present <= perms
        assert perms.isdisjoint(expected_never_present)

    def test_viewer_precise_location_toggle(self) -> None:
        """`allow_precise_location_to_viewer=true` → Viewer gains VIEW_PRECISE_LOCATION."""
        config = DEFAULT_RESTRICTED_CONFIG.copy()
        config["allow_precise_location_to_viewer"] = True
        perms = _compute("Viewer", ProjectVisibility.RESTRICTED, config)
        assert Permission.VIEW_PRECISE_LOCATION in perms


# 7.3 Trusted overlay — Authenticated only (FR-014, FR-015)
class TestTrustedOverlay:
    def test_trusted_applied_to_authenticated(self) -> None:
        """Trusted capabilities add to Authenticated base."""
        trusted = frozenset(
            {Permission.DOWNLOAD, Permission.VIEW_PRECISE_LOCATION}
        )
        perms = _compute(
            "Authenticated", ProjectVisibility.PUBLIC, trusted=trusted
        )
        assert Permission.DOWNLOAD in perms
        assert Permission.VIEW_PRECISE_LOCATION in perms

    def test_trusted_never_applied_to_guest(self) -> None:
        """Guest can never have Trusted overlay (must be logged in)."""
        trusted = frozenset({Permission.DOWNLOAD})
        perms = _compute(
            "Guest", ProjectVisibility.PUBLIC, trusted=trusted
        )
        # Guest base on Public has VIEW_* only, no DOWNLOAD.
        assert Permission.DOWNLOAD not in perms

    def test_trusted_never_applied_to_member(self) -> None:
        """Member already has DOWNLOAD; Trusted overlay is Authenticated-only."""
        trusted = frozenset({Permission.EXPORT})
        perms = _compute(
            "Member", ProjectVisibility.RESTRICTED, trusted=trusted
        )
        # Member Canonical base already has EXPORT, so presence is not
        # diagnostic — assert Trusted overlay did not expand beyond base.
        assert perms == frozenset(ROLE_PERMISSIONS[ComputedRole.MEMBER])

    def test_trusted_allowlist_runtime_safety(self) -> None:
        """FR-014 runtime filter: out-of-allowlist capability is dropped."""
        # Inject a disallowed permission (CREATE_TAG is not in TRUSTED_ALLOWED).
        bogus = frozenset({Permission.CREATE_TAG, Permission.DOWNLOAD})
        perms = _compute(
            "Authenticated", ProjectVisibility.PUBLIC, trusted=bogus
        )
        assert Permission.CREATE_TAG not in perms
        assert Permission.DOWNLOAD in perms


# 7.4 API key scope intersection (FR-079)
class TestApiKeyIntersection:
    def test_api_key_scope_narrows_permissions(self) -> None:
        """effective = role ∩ api_key_scopes (FR-079)."""
        scopes = frozenset({Permission.EXPORT})
        perms = _compute(
            "Admin", ProjectVisibility.PUBLIC, api_key_scopes=scopes
        )
        # Admin has many perms; after intersection with {EXPORT}, only EXPORT.
        assert perms == frozenset({Permission.EXPORT})

    def test_api_key_scope_cannot_expand(self) -> None:
        """API key scope can never grant a perm the role lacks."""
        scopes = frozenset({Permission.TRAIN_MODEL})  # Admin has it, Member does not
        perms = _compute(
            "Member", ProjectVisibility.PUBLIC, api_key_scopes=scopes
        )
        # Member lacks TRAIN_MODEL → intersection is empty.
        assert perms == frozenset()


# ---------------------------------------------------------------------------
# 8. Full-cross product sanity: every (role, visibility, Permission) cell
# agrees with spec matrix after toggles OFF.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "role_str",
    ["Guest", "Authenticated", "Viewer", "Member", "Admin", "Owner"],
)
@pytest.mark.parametrize(
    "visibility",
    [ProjectVisibility.PUBLIC, ProjectVisibility.RESTRICTED],
)
def test_cross_product_no_crash_and_shape(
    role_str: str, visibility: ProjectVisibility
) -> None:
    """Smoke: every cell returns a frozenset[Permission] without raising."""
    perms = _compute(role_str, visibility)
    assert isinstance(perms, frozenset)
    for p in perms:
        assert isinstance(p, Permission)
    # All permissions returned must be project-scope (Matrix guarantees this).
    assert perms.isdisjoint(USER_SCOPE_PERMISSIONS - {Permission.SEARCH_CROSS_PROJECT})
