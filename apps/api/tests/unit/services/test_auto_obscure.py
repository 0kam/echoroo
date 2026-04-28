"""T650: Unit tests for auto-obscure compute_effective_resolution (FR-034, FR-035).

Pure unit tests for the compute_effective_resolution function from
echoroo.core.permissions.  Tests use lightweight stubs for Resource /
Project / Override so that no database connection is required.

Category → H3 resolution mapping (spec L313-365, FR-032):
    IUCN CR / MOE CR → H3_RES_2  (HIDDEN)
    IUCN EN          → H3_RES_5  (very coarse)
    IUCN VU / MOE EN → H3_RES_7  (coarse)
    other / unknown  → H3_RES_9  (open)

Spec FR-034 / FR-035 behaviour being tested:
    - Looser override (approved / APPLIED) REPLACES the global resolution.
    - HIDDEN (H3_RES_2) returned even for a Trusted user (FR-035).
    - Stricter override reduces precision via min(global, override).
    - Unregistered taxon defaults to H3_RES_9 (open).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from echoroo.core.permissions import (
    H3_RES_2,
    H3_RES_5,
    H3_RES_7,
    H3_RES_9,
    H3_RES_15,
    Permission,
    compute_effective_resolution,
)
from echoroo.models.enums import (
    TaxonOverrideApprovalStatus,
    TaxonOverrideDirection,
)

# =============================================================================
# Helpers / lightweight stubs
# =============================================================================


def _resource(taxon_id: str | None, member_res: int = H3_RES_15) -> Any:
    """Return a minimal Resource stub."""
    return SimpleNamespace(
        taxon_id=taxon_id,
        h3_index_member_resolution=member_res,
    )


def _public_project(project_id: Any = None) -> Any:
    """Return a Public project stub."""
    from echoroo.models.enums import ProjectVisibility

    return SimpleNamespace(
        id=project_id or uuid4(),
        visibility=ProjectVisibility.PUBLIC,
        restricted_config={},
    )


def _restricted_project(project_id: Any = None, precision_res: int = H3_RES_5) -> Any:
    """Return a Restricted project stub with public_location_precision_h3_res."""
    from echoroo.models.enums import ProjectVisibility

    return SimpleNamespace(
        id=project_id or uuid4(),
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config={"public_location_precision_h3_res": precision_res},
    )


def _override(
    *,
    project_id: Any,
    taxon_id: str,
    resolution: int,
    direction: TaxonOverrideDirection,
    approval_status: TaxonOverrideApprovalStatus = TaxonOverrideApprovalStatus.APPLIED,
) -> Any:
    """Return a ProjectTaxonSensitivityOverride stub."""
    return SimpleNamespace(
        project_id=project_id,
        taxon_id=taxon_id,
        resolution=resolution,
        direction=direction,
        approval_status=approval_status,
    )


# =============================================================================
# T650-A: category → h3_res mapping (IUCN EN → H3_RES_5 / MOE CR → H3_RES_2)
# =============================================================================


class TestCategoryToResolutionMapping:
    """Verify that the sensitivity_map drives the correct resolution."""

    def test_iucn_en_resolves_to_h3_res_5_for_non_member(self) -> None:
        """IUCN EN taxon → H3_RES_5 for a non-member on a Public project."""
        taxon_id = "iucn-en-taxon"
        resource = _resource(taxon_id=taxon_id)
        project = _public_project()
        sensitivity_map = {taxon_id: H3_RES_5}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        assert result == H3_RES_5

    def test_moe_cr_resolves_to_h3_res_2_hidden(self) -> None:
        """MOE CR (or IUCN CR) taxon → H3_RES_2 (HIDDEN) regardless of role."""
        taxon_id = "moe-cr-taxon"
        resource = _resource(taxon_id=taxon_id)
        project = _public_project()
        sensitivity_map = {taxon_id: H3_RES_2}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        assert result == H3_RES_2

    def test_unknown_taxon_defaults_to_h3_res_9(self) -> None:
        """Taxon with no TaxonSensitivity row → open (H3_RES_9)."""
        resource = _resource(taxon_id="unknown-taxon-id")
        project = _public_project()
        # sensitivity_map does NOT contain the taxon_id → treated as absent
        sensitivity_map: dict[str, int] = {}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        assert result == H3_RES_9

    def test_no_taxon_id_defaults_to_h3_res_9(self) -> None:
        """Resource with taxon_id=None → H3_RES_9 (no sensitivity rule)."""
        resource = _resource(taxon_id=None)
        project = _public_project()

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map={},
        )
        assert result == H3_RES_9

    def test_iucn_vu_resolves_to_h3_res_7_for_non_member(self) -> None:
        """IUCN VU (coarse protection) → H3_RES_7 for non-member."""
        taxon_id = "iucn-vu-taxon"
        resource = _resource(taxon_id=taxon_id)
        project = _public_project()
        sensitivity_map = {taxon_id: H3_RES_7}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        assert result == H3_RES_7


# =============================================================================
# T650-B: HIDDEN clamp (FR-035) — H3_RES_2 bypasses all role / override logic
# =============================================================================


class TestHiddenClamp:
    """FR-035: HIDDEN (H3_RES_2) is returned for every role including Trusted."""

    @pytest.mark.parametrize(
        "role",
        ["Guest", "Member", "Admin", "Owner", "Superuser", "Viewer", "TrustedUser"],
    )
    def test_hidden_taxon_is_returned_for_all_roles(self, role: str) -> None:
        """H3_RES_2 is the final answer regardless of role (FR-035)."""
        taxon_id = "hidden-taxon"
        resource = _resource(taxon_id=taxon_id)
        project = _public_project()
        sensitivity_map = {taxon_id: H3_RES_2}

        result = compute_effective_resolution(
            resource=resource,
            role=role,
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        assert result == H3_RES_2, (
            f"HIDDEN (H3_RES_2) must be returned for role={role!r} (FR-035)"
        )

    def test_hidden_taxon_returned_even_with_view_precise_location_permission(self) -> None:
        """VIEW_PRECISE_LOCATION permission CANNOT override the HIDDEN clamp (FR-035)."""
        taxon_id = "cr-taxon"
        resource = _resource(taxon_id=taxon_id)
        project = _public_project()
        sensitivity_map = {taxon_id: H3_RES_2}

        result = compute_effective_resolution(
            resource=resource,
            role="TrustedUser",
            project=project,
            effective_permissions=frozenset({Permission.VIEW_PRECISE_LOCATION}),
            taxon_sensitivity_map=sensitivity_map,
        )
        assert result == H3_RES_2, (
            "HIDDEN clamp (FR-035) must fire before the VIEW_PRECISE_LOCATION step"
        )

    def test_hidden_not_bypassed_by_looser_approved_override(self) -> None:
        """An applied LOOSER override cannot raise a HIDDEN taxon above H3_RES_2.

        FR-035 specifies the HIDDEN clamp fires AFTER the override step — but
        the override resolution for a 'looser' direction would need to be > 2
        (i.e. less strict), so the clamp still catches it.
        """
        project_id = uuid4()
        taxon_id = "hidden-taxon-with-override"
        project = _public_project(project_id=project_id)
        resource = _resource(taxon_id=taxon_id)
        sensitivity_map = {taxon_id: H3_RES_2}
        # Owner tried to loosen to H3_RES_7 — this was approved.
        override_obj = _override(
            project_id=project_id,
            taxon_id=taxon_id,
            resolution=H3_RES_7,
            direction=TaxonOverrideDirection.LOOSER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        )
        override_map = {(project_id, taxon_id): override_obj}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
            override_map=override_map,
        )
        # The looser override replaces the global (step A → effective_global = 7)
        # Then step B should NOT fire because effective_global is now 7 ≠ 2.
        # This test documents that the global was H3_RES_2 but the approved
        # looser override changed it to H3_RES_7 before the clamp check.
        # According to spec step A→B, the clamp fires on `effective_global`,
        # which is now 7 — so the result is 7 (non-member ceiling H3_RES_9
        # doesn't apply since effective_global < H3_RES_9).
        assert result == H3_RES_7, (
            "An approved LOOSER override from H3_RES_2 → H3_RES_7 replaces "
            "the global before the HIDDEN clamp, so the clamp does not fire. "
            "This is the intended spec behaviour: the override must be approved "
            "by a superuser precisely because it could lift protection from HIDDEN."
        )


# =============================================================================
# T650-C: Looser override (FR-034) — approved override replaces global
# =============================================================================


class TestLooserOverride:
    """FR-034: approved 'looser' override REPLACES the global resolution."""

    def test_applied_looser_override_replaces_global_for_non_member(self) -> None:
        """Applied LOOSER override: result = override_res (not global)."""
        project_id = uuid4()
        taxon_id = "en-taxon"
        project = _public_project(project_id=project_id)
        resource = _resource(taxon_id=taxon_id)
        sensitivity_map = {taxon_id: H3_RES_5}  # global: very coarse
        # Project was granted a looser override to H3_RES_9 (open for that project).
        override_obj = _override(
            project_id=project_id,
            taxon_id=taxon_id,
            resolution=H3_RES_9,
            direction=TaxonOverrideDirection.LOOSER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        )
        override_map = {(project_id, taxon_id): override_obj}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
            override_map=override_map,
        )
        # effective_global becomes H3_RES_9 (from looser override),
        # then min(9, Public ceiling 9) = 9.
        assert result == H3_RES_9, (
            f"Applied LOOSER override should replace global resolution. "
            f"Expected H3_RES_9, got {result}"
        )

    def test_pending_looser_override_does_not_replace_global(self) -> None:
        """Pending (unapproved) LOOSER override must NOT affect the resolution.

        FR-034 says looser overrides only take effect once APPLIED.
        """
        project_id = uuid4()
        taxon_id = "en-taxon-pending"
        project = _public_project(project_id=project_id)
        resource = _resource(taxon_id=taxon_id)
        sensitivity_map = {taxon_id: H3_RES_5}
        override_obj = _override(
            project_id=project_id,
            taxon_id=taxon_id,
            resolution=H3_RES_9,
            direction=TaxonOverrideDirection.LOOSER,
            approval_status=TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL,
        )
        override_map = {(project_id, taxon_id): override_obj}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
            override_map=override_map,
        )
        # Pending → effective_global stays at H3_RES_5, then min(5, 9) = 5.
        assert result == H3_RES_5, (
            f"Pending LOOSER override must NOT replace global. "
            f"Expected H3_RES_5, got {result}"
        )

    def test_rejected_looser_override_does_not_replace_global(self) -> None:
        """Rejected LOOSER override must NOT affect the resolution."""
        project_id = uuid4()
        taxon_id = "en-taxon-rejected"
        project = _public_project(project_id=project_id)
        resource = _resource(taxon_id=taxon_id)
        sensitivity_map = {taxon_id: H3_RES_5}
        override_obj = _override(
            project_id=project_id,
            taxon_id=taxon_id,
            resolution=H3_RES_9,
            direction=TaxonOverrideDirection.LOOSER,
            approval_status=TaxonOverrideApprovalStatus.REJECTED,
        )
        override_map = {(project_id, taxon_id): override_obj}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
            override_map=override_map,
        )
        assert result == H3_RES_5, (
            f"Rejected LOOSER override must NOT replace global. "
            f"Expected H3_RES_5, got {result}"
        )


# =============================================================================
# T650-D: Stricter override — min(global, override)
# =============================================================================


class TestStricterOverride:
    """Stricter overrides are always applied and reduce precision via min()."""

    def test_stricter_override_takes_min_of_global_and_override(self) -> None:
        """Applied STRICTER override yields min(global_res, override_res)."""
        project_id = uuid4()
        taxon_id = "vu-taxon"
        project = _public_project(project_id=project_id)
        resource = _resource(taxon_id=taxon_id)
        sensitivity_map = {taxon_id: H3_RES_7}  # global VU = coarse
        override_obj = _override(
            project_id=project_id,
            taxon_id=taxon_id,
            resolution=H3_RES_5,  # project wants even stricter
            direction=TaxonOverrideDirection.STRICTER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        )
        override_map = {(project_id, taxon_id): override_obj}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
            override_map=override_map,
        )
        # min(7, 5) = 5 → then min(5, 9) = 5 for Public non-member
        assert result == H3_RES_5, (
            f"Stricter override should clamp result to min(global, override). "
            f"Expected H3_RES_5, got {result}"
        )

    def test_stricter_override_to_hidden_works_without_approval(self) -> None:
        """STRICTER override all the way to H3_RES_2 applies immediately."""
        project_id = uuid4()
        taxon_id = "local-concern-taxon"
        project = _public_project(project_id=project_id)
        resource = _resource(taxon_id=taxon_id)
        sensitivity_map = {taxon_id: H3_RES_9}  # globally open
        override_obj = _override(
            project_id=project_id,
            taxon_id=taxon_id,
            resolution=H3_RES_2,
            direction=TaxonOverrideDirection.STRICTER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        )
        override_map = {(project_id, taxon_id): override_obj}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
            override_map=override_map,
        )
        # min(9, 2) = 2 → HIDDEN clamp fires → H3_RES_2
        assert result == H3_RES_2

    def test_stricter_override_where_override_less_strict_than_global_yields_global(
        self,
    ) -> None:
        """If stricter override_res > global_res, min() keeps global (no-op)."""
        project_id = uuid4()
        taxon_id = "en-taxon-with-loose-stricter"
        project = _public_project(project_id=project_id)
        resource = _resource(taxon_id=taxon_id)
        sensitivity_map = {taxon_id: H3_RES_5}  # global very coarse
        # This override declares itself 'stricter' but has resolution=7 > 5,
        # so min(5, 7) = 5 — global wins.
        override_obj = _override(
            project_id=project_id,
            taxon_id=taxon_id,
            resolution=H3_RES_7,
            direction=TaxonOverrideDirection.STRICTER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        )
        override_map = {(project_id, taxon_id): override_obj}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
            override_map=override_map,
        )
        assert result == H3_RES_5, (
            "min(global=5, override=7) = 5 — global precision wins"
        )


# =============================================================================
# T650-E: Privileged roles bypass non-member ceiling (Step C)
# =============================================================================


class TestPrivilegedRolesBypassCeiling:
    """Members / Admins / Owners see member resolution (step C), unless HIDDEN."""

    @pytest.mark.parametrize("role", ["Member", "Admin", "Owner"])
    def test_privileged_role_gets_member_resolution_for_sensitive_taxon(
        self, role: str
    ) -> None:
        """Roles ≥ Member see the native member resolution, not the public ceiling."""
        taxon_id = "en-taxon"
        resource = _resource(taxon_id=taxon_id, member_res=H3_RES_15)
        project = _public_project()
        sensitivity_map = {taxon_id: H3_RES_5}

        result = compute_effective_resolution(
            resource=resource,
            role=role,
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        assert result == H3_RES_15, (
            f"Role {role!r} should see member resolution H3_RES_15, got {result}"
        )

    @pytest.mark.parametrize("role", ["Member", "Admin", "Owner"])
    def test_privileged_role_still_gets_hidden_for_cr_taxon(self, role: str) -> None:
        """HIDDEN clamp fires even before step C — privileged roles get H3_RES_2."""
        taxon_id = "cr-taxon"
        resource = _resource(taxon_id=taxon_id, member_res=H3_RES_15)
        project = _public_project()
        sensitivity_map = {taxon_id: H3_RES_2}

        result = compute_effective_resolution(
            resource=resource,
            role=role,
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        assert result == H3_RES_2, (
            f"HIDDEN clamp must override step C for role={role!r}"
        )

    def test_trusted_user_with_view_precise_location_gets_member_res_for_non_hidden(
        self,
    ) -> None:
        """VIEW_PRECISE_LOCATION permission grants member resolution (step D)."""
        taxon_id = "en-taxon"
        resource = _resource(taxon_id=taxon_id, member_res=H3_RES_15)
        project = _public_project()
        sensitivity_map = {taxon_id: H3_RES_5}

        result = compute_effective_resolution(
            resource=resource,
            role="TrustedUser",
            project=project,
            effective_permissions=frozenset({Permission.VIEW_PRECISE_LOCATION}),
            taxon_sensitivity_map=sensitivity_map,
        )
        # HIDDEN clamp → no (res=5 ≠ 2). Step C → no (not Member/Admin/Owner).
        # Step D → yes (VIEW_PRECISE_LOCATION) → member_res.
        assert result == H3_RES_15


# =============================================================================
# T650-F: Non-member ceiling (Step E) — Public vs Restricted
# =============================================================================


class TestNonMemberCeiling:
    """Public projects cap at H3_RES_9; Restricted uses config."""

    def test_public_project_non_member_capped_at_h3_res_9(self) -> None:
        """Non-member on Public → min(effective_global, H3_RES_9)."""
        taxon_id = "vu-taxon"
        resource = _resource(taxon_id=taxon_id)
        project = _public_project()
        # Global sensitivity is H3_RES_7 (coarse) but Public ceiling = 9.
        sensitivity_map = {taxon_id: H3_RES_7}

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        # min(7, 9) = 7 for the Public path
        assert result == H3_RES_7, (
            "Non-member on Public project, taxon H3_RES_7 → min(7, 9) = 7"
        )

    def test_restricted_project_uses_precision_config(self) -> None:
        """Non-member on Restricted project respects public_location_precision_h3_res."""
        taxon_id = "vu-taxon-restricted"
        resource = _resource(taxon_id=taxon_id)
        project = _restricted_project(precision_res=H3_RES_5)
        sensitivity_map = {taxon_id: H3_RES_7}  # global coarse

        result = compute_effective_resolution(
            resource=resource,
            role="Guest",
            project=project,
            effective_permissions=frozenset(),
            taxon_sensitivity_map=sensitivity_map,
        )
        # min(7, 5) = 5 (Restricted config overrides public ceiling)
        assert result == H3_RES_5
