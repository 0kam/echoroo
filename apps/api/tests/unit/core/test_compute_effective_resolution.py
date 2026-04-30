"""Unit tests for ``compute_effective_resolution`` (T042).

Spec references: FR-027 (H3 discrete resolutions 2/5/7/9/15), FR-034 (looser
override replaces global post-approval), FR-035 (HIDDEN clamp semantics),
SC-017 (Viewer precise location), spec.md §Permission decision algorithm
Step A-E in ``compute_effective_resolution``.

These tests are part of the TDD Red phase — they fail on import until
``core/permissions.py`` exports ``compute_effective_resolution``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from echoroo.core.permissions import (
    H3_RES_2,
    H3_RES_5,
    H3_RES_7,
    H3_RES_9,
    H3_RES_15,
    Permission,
    ProjectVisibility,
    TaxonOverrideApprovalStatus,
    TaxonOverrideDirection,
    compute_effective_resolution,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _project(
    visibility: ProjectVisibility,
    *,
    public_location_precision_h3_res: int = H3_RES_2,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="proj-0001",
        visibility=visibility,
        restricted_config={
            "allow_media_playback": False,
            "allow_detection_view": False,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": public_location_precision_h3_res,
            "allow_precise_location_to_viewer": False,
        },
        status="active",
    )


def _override(
    resolution: int,
    direction: TaxonOverrideDirection,
    approval_status: TaxonOverrideApprovalStatus,
) -> SimpleNamespace:
    # ORM column is ``sensitivity_h3_res`` per
    # ``ProjectTaxonSensitivityOverride.sensitivity_h3_res``. Phase 16 Batch 6a
    # aligned this fixture with the live attribute name (the earlier
    # ``resolution`` was a docstring drift that silently dropped every override
    # in red-phase tests).
    return SimpleNamespace(
        direction=direction,
        approval_status=approval_status,
        sensitivity_h3_res=resolution,
    )


def _call(
    *,
    role: str,
    visibility: ProjectVisibility,
    taxon_global_res: int | None = H3_RES_9,
    override: Any | None = None,
    effective_perms: frozenset[Permission] = frozenset(),
    member_resolution: int = H3_RES_15,
    public_location_precision_h3_res: int = H3_RES_7,
    taxon_id: str = "taxon-001",
) -> int:
    project = _project(
        visibility,
        public_location_precision_h3_res=public_location_precision_h3_res,
    )
    resource = SimpleNamespace(
        taxon_id=taxon_id,
        h3_index_member="abcd",
        h3_index_member_resolution=member_resolution,
    )
    sensitivity_map = {taxon_id: taxon_global_res} if taxon_global_res is not None else {}
    override_map = {(project.id, taxon_id): override} if override is not None else {}
    return compute_effective_resolution(
        resource=resource,
        role=role,
        project=project,
        effective_permissions=effective_perms,
        taxon_sensitivity_map=sensitivity_map,
        override_map=override_map,
    )


# ---------------------------------------------------------------------------
# 1. FR-035: HIDDEN clamp — global H3_RES_2 cannot be relaxed
# ---------------------------------------------------------------------------

class TestHiddenClamp:
    def test_hidden_species_member_cannot_see_precise(self) -> None:
        """Global H3_RES_2 + Member → still H3_RES_2 (HIDDEN)."""
        res = _call(
            role="Member",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_2,
        )
        assert res == H3_RES_2

    def test_hidden_species_trusted_cannot_see_precise(self) -> None:
        """Global H3_RES_2 + VIEW_PRECISE_LOCATION → still H3_RES_2."""
        res = _call(
            role="Authenticated",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_2,
            effective_perms=frozenset({Permission.VIEW_PRECISE_LOCATION}),
        )
        assert res == H3_RES_2

    def test_hidden_species_viewer_cannot_see_precise(self) -> None:
        """Viewer + `allow_precise_location_to_viewer` + HIDDEN → still H3_RES_2 (SC-017)."""
        res = _call(
            role="Viewer",
            visibility=ProjectVisibility.RESTRICTED,
            taxon_global_res=H3_RES_2,
            effective_perms=frozenset({Permission.VIEW_PRECISE_LOCATION}),
        )
        assert res == H3_RES_2

    def test_hidden_species_owner_cannot_see_precise(self) -> None:
        """Even Owner cannot override HIDDEN clamp (FR-035)."""
        res = _call(
            role="Owner",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_2,
        )
        assert res == H3_RES_2


# ---------------------------------------------------------------------------
# 2. FR-034: looser override replaces global post-approval
# ---------------------------------------------------------------------------

class TestLooserOverride:
    def test_looser_pending_has_no_effect(self) -> None:
        """Pending looser override does not relax the global resolution."""
        override = _override(
            H3_RES_9,
            TaxonOverrideDirection.LOOSER,
            TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL,
        )
        res = _call(
            role="Authenticated",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_2,
            override=override,
        )
        # Pending looser does NOT replace → HIDDEN preserved.
        assert res == H3_RES_2

    def test_looser_approved_replaces_global(self) -> None:
        """FR-034: looser APPLIED override replaces global (not min)."""
        override = _override(
            H3_RES_9,
            TaxonOverrideDirection.LOOSER,
            TaxonOverrideApprovalStatus.APPLIED,
        )
        # With replaced global H3_RES_9, Step B HIDDEN-clamp passes.
        # Public non-member precision defaults to H3_RES_7 in fixture → min(9, 7) = 7.
        res = _call(
            role="Authenticated",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_2,  # original HIDDEN
            override=override,
            public_location_precision_h3_res=H3_RES_7,
        )
        # Public always caps at H3_RES_9 for non-members (FR-018) → min(9, 9)=9.
        # After looser override replaces H3_RES_2 → H3_RES_9, Public clamp
        # is H3_RES_9 (FR-018 says Public ignores public_location_precision),
        # so effective_global(9) vs public(9) → 9.
        assert res == H3_RES_9

    def test_looser_approved_unblocks_hidden_for_trusted(self) -> None:
        """Looser approved + VIEW_PRECISE_LOCATION → member resolution (FR-035)."""
        override = _override(
            H3_RES_9,
            TaxonOverrideDirection.LOOSER,
            TaxonOverrideApprovalStatus.APPLIED,
        )
        res = _call(
            role="Authenticated",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_2,
            override=override,
            effective_perms=frozenset({Permission.VIEW_PRECISE_LOCATION}),
            member_resolution=H3_RES_15,
        )
        assert res == H3_RES_15

    def test_stricter_override_applies_immediately(self) -> None:
        """Stricter override never needs approval; min(global, override)."""
        override = _override(
            H3_RES_5,
            TaxonOverrideDirection.STRICTER,
            TaxonOverrideApprovalStatus.APPLIED,
        )
        # Global H3_RES_9, stricter H3_RES_5 → min → H3_RES_5.
        res = _call(
            role="Authenticated",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_9,
            override=override,
        )
        # Public clamp also H3_RES_9 → min(5, 9) = 5.
        assert res == H3_RES_5

    def test_stricter_override_to_hidden(self) -> None:
        """Stricter override to H3_RES_2 forces HIDDEN."""
        override = _override(
            H3_RES_2,
            TaxonOverrideDirection.STRICTER,
            TaxonOverrideApprovalStatus.APPLIED,
        )
        res = _call(
            role="Member",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_9,
            override=override,
        )
        assert res == H3_RES_2


# ---------------------------------------------------------------------------
# 3. Trusted VIEW_PRECISE_LOCATION boost (FR-035 Step D)
# ---------------------------------------------------------------------------

class TestTrustedBoost:
    def test_trusted_boost_returns_member_resolution(self) -> None:
        """Authenticated + VIEW_PRECISE_LOCATION + non-HIDDEN → member resolution."""
        res = _call(
            role="Authenticated",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_7,
            effective_perms=frozenset({Permission.VIEW_PRECISE_LOCATION}),
            member_resolution=H3_RES_15,
        )
        assert res == H3_RES_15

    def test_viewer_with_boost_returns_member_resolution(self) -> None:
        """Viewer with `allow_precise_location_to_viewer` on non-HIDDEN taxon → member."""
        res = _call(
            role="Viewer",
            visibility=ProjectVisibility.RESTRICTED,
            taxon_global_res=H3_RES_5,
            effective_perms=frozenset({Permission.VIEW_PRECISE_LOCATION}),
            member_resolution=H3_RES_15,
        )
        assert res == H3_RES_15


# ---------------------------------------------------------------------------
# 4. Member / Admin / Owner / Superuser resolution (FR-035 Step C)
# ---------------------------------------------------------------------------

class TestMemberResolution:
    @pytest.mark.parametrize("role", ["Member", "Admin", "Owner", "Superuser"])
    def test_members_get_member_resolution(self, role: str) -> None:
        """Privileged roles see member resolution (as long as not HIDDEN)."""
        res = _call(
            role=role,
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_9,
            member_resolution=H3_RES_15,
        )
        assert res == H3_RES_15


# ---------------------------------------------------------------------------
# 5. Public visibility ignores `public_location_precision_h3_res` (FR-018)
# ---------------------------------------------------------------------------

class TestPublicVisibilityClamp:
    def test_public_ignores_restricted_config_clamp(self) -> None:
        """FR-018: Public does NOT apply restricted_config precision (always H3_RES_9)."""
        # If Public respected the config (H3_RES_5), result would be 5.
        # Spec: Public forces H3_RES_9 for non-members.
        res = _call(
            role="Authenticated",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_9,
            public_location_precision_h3_res=H3_RES_5,
        )
        assert res == H3_RES_9

    def test_restricted_uses_config_clamp(self) -> None:
        """Restricted uses `public_location_precision_h3_res` as ceiling."""
        res = _call(
            role="Authenticated",
            visibility=ProjectVisibility.RESTRICTED,
            taxon_global_res=H3_RES_9,
            public_location_precision_h3_res=H3_RES_5,
        )
        # min(global 9, config 5) = 5
        assert res == H3_RES_5


# ---------------------------------------------------------------------------
# 6. Guest + non-member: no precise location
# ---------------------------------------------------------------------------

class TestGuestResolution:
    def test_guest_public_taxon_clamp(self) -> None:
        """Guest on Public: effective = min(global, H3_RES_9)."""
        res = _call(
            role="Guest",
            visibility=ProjectVisibility.PUBLIC,
            taxon_global_res=H3_RES_7,
        )
        assert res == H3_RES_7

    def test_guest_restricted_fallback_default(self) -> None:
        """Guest on Restricted + no precise override: very coarse clamp."""
        res = _call(
            role="Guest",
            visibility=ProjectVisibility.RESTRICTED,
            taxon_global_res=H3_RES_9,
            public_location_precision_h3_res=H3_RES_2,
        )
        # min(9, 2) = 2 (default config is HIDDEN-equivalent for Restricted)
        assert res == H3_RES_2
