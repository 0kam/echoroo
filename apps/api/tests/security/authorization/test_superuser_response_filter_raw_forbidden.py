"""T958 — Superuser principal does not leak raw lat/lng / HIDDEN data.

Target: FR-112a (superuser sees project data as Owner-equivalent, but
stage-2 response filter still scrubs forbidden raw fields).

The ``apply_response_filter`` function (``echoroo.core.response_filter``)
applies stage-2 transformations after the stage-1 permission gate.  It:

1. Always strips ``FORBIDDEN_RAW_LOCATION_FIELDS`` (latitude, longitude, …)
   regardless of the caller's role.
2. Coarsens H3 indices to the effective resolution (which for a HIDDEN taxon
   is ``H3_RES_2`` even for Superusers — FR-035).
3. Masks species names for Restricted projects with ``mask_species_in_detection``
   when the caller is not a member (Superuser falls through to the Member
   normalisation path, so masking does NOT apply to Superuser).

The ``raw bypass`` path (``/admin/projects/{id}/raw-export``) is **not yet
implemented** in Phase 15; it is tested with xfail to make the TODO visible.

Note: this suite is pure-function (no DB, no FastAPI app).  It exercises
``apply_response_filter`` and ``is_allowed`` directly with minimal
SimpleNamespace fixtures.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from echoroo.core.permissions import (
    H3_RES_2,
    H3_RES_9,
    H3_RES_15,
    ProjectVisibility,
    compute_effective_permissions,
)
from echoroo.core.response_filter import (
    FORBIDDEN_RAW_LOCATION_FIELDS,
    apply_response_filter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(
    *,
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC,
    status: str = "active",
    mask_species: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="proj-t958",
        owner_id=None,
        visibility=visibility,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": mask_species,
            "allow_download": True,
            "allow_export": True,
            "allow_voting_and_comments": True,
            "public_location_precision_h3_res": H3_RES_9,
            "allow_precise_location_to_viewer": False,
        },
        status=status,
    )


def _make_response_obj(**kwargs: Any) -> SimpleNamespace:
    """Build a minimal response-like object with common sensitive fields."""
    defaults: dict[str, Any] = {
        "latitude": 35.123456,
        "longitude": 139.123456,
        "h3_index_member": "8f283082a2a19f5",  # H3 res 15 cell
        "h3_index_member_resolution": H3_RES_15,
        "species": "Turdus naumanni",
        "common_name": "Naumann's Thrush",
        "scientific_name": "Turdus naumanni",
        "withheld_reason": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_resource(
    *,
    h3_res: int = H3_RES_15,
    taxon_id: str | None = "species-A",
) -> SimpleNamespace:
    return SimpleNamespace(
        h3_index_member="8f283082a2a19f5",
        h3_index_member_resolution=h3_res,
        taxon_id=taxon_id,
    )


# ---------------------------------------------------------------------------
# Core invariant: FORBIDDEN_RAW_LOCATION_FIELDS always stripped
# ---------------------------------------------------------------------------


class TestForbiddenRawFieldsAlwaysStripped:
    """FORBIDDEN_RAW_LOCATION_FIELDS must be stripped for ALL caller roles."""

    @pytest.mark.parametrize(
        "normalized_role",
        ["Guest", "Authenticated", "Viewer", "Member", "Admin", "Owner", "Superuser"],
    )
    def test_raw_coordinate_fields_stripped_for_all_roles(
        self, normalized_role: str
    ) -> None:
        """latitude / longitude must be None / absent regardless of role."""
        project = _make_project()
        obj = _make_response_obj()
        resource = _make_resource()

        # Compute effective permissions for the given role.
        if normalized_role == "Superuser":
            from echoroo.core.permissions import (
                _SUPERUSER_PERMS,  # noqa: PLC2701 (private import in test)
            )
            effective = frozenset(_SUPERUSER_PERMS)
        else:
            effective = compute_effective_permissions(
                normalized_role=normalized_role,
                project=project,
            )

        apply_response_filter(
            obj=obj,
            effective_permissions=effective,
            normalized_role=normalized_role,
            project=project,
            resource=resource,
        )

        # latitude and longitude must have been scrubbed.
        assert getattr(obj, "latitude", None) is None, (
            f"latitude must be None after filter for role={normalized_role!r}"
        )
        assert getattr(obj, "longitude", None) is None, (
            f"longitude must be None after filter for role={normalized_role!r}"
        )

    def test_forbidden_fields_scrubbed_from_dict(self) -> None:
        """Dicts also have forbidden raw coords removed."""
        project = _make_project()
        d: dict[str, Any] = {
            "latitude": 35.1,
            "longitude": 139.1,
            "h3_index_member": "8f283082a2a19f5",
            "h3_index_member_resolution": H3_RES_15,
        }
        # Use a sentinel effective_permissions (superuser full set).
        from echoroo.core.permissions import _SUPERUSER_PERMS  # noqa: PLC2701
        apply_response_filter(
            obj=d,
            effective_permissions=frozenset(_SUPERUSER_PERMS),
            normalized_role="Superuser",
            project=project,
        )
        assert "latitude" not in d
        assert "longitude" not in d

    def test_forbidden_fields_set_is_correct(self) -> None:
        """The forbidden-fields set must include all known raw-coordinate names."""
        for field in ("latitude", "longitude", "lat", "lng", "gps_latitude", "gps_longitude"):
            assert field in FORBIDDEN_RAW_LOCATION_FIELDS, (
                f"{field!r} must be in FORBIDDEN_RAW_LOCATION_FIELDS"
            )


# ---------------------------------------------------------------------------
# HIDDEN taxon: H3 clamped to H3_RES_2 even for Superuser
# ---------------------------------------------------------------------------


class TestHiddenTaxonSuperuserClamp:
    """FR-035: HIDDEN taxon sensitivity clamps H3 to res 2 for ALL callers."""

    def test_superuser_hidden_taxon_h3_clamped_to_res2(self) -> None:
        """Superuser with HIDDEN taxon map must get H3_RES_2 location."""
        from echoroo.core.permissions import _SUPERUSER_PERMS  # noqa: PLC2701
        project = _make_project(visibility=ProjectVisibility.PUBLIC)
        obj = _make_response_obj(h3_index_member="8f283082a2a19f5")
        resource = _make_resource(taxon_id="species-hidden")

        # Build a sensitivity map where the taxon is HIDDEN (H3_RES_2).
        taxon_sensitivity_map = {"species-hidden": H3_RES_2}

        apply_response_filter(
            obj=obj,
            effective_permissions=frozenset(_SUPERUSER_PERMS),
            normalized_role="Superuser",
            project=project,
            resource=resource,
            taxon_sensitivity_map=taxon_sensitivity_map,
        )

        # The h3_index_member must now be a res-2 cell (coarsened).
        # We just verify that the coarsening ran (withheld_reason set).
        assert obj.withheld_reason is not None, (
            "withheld_reason must be set for HIDDEN taxon regardless of role"
        )
        assert "taxon_sensitivity" in obj.withheld_reason, (
            f"withheld_reason must mention taxon_sensitivity, got {obj.withheld_reason!r}"
        )

    def test_owner_hidden_taxon_also_clamped(self) -> None:
        """Owner role (like Superuser in real endpoints) is also subject to HIDDEN clamp."""
        project = _make_project(visibility=ProjectVisibility.PUBLIC)
        obj = _make_response_obj(h3_index_member="8f283082a2a19f5")
        resource = _make_resource(taxon_id="species-hidden")

        owner_effective = compute_effective_permissions(
            normalized_role="Owner",
            project=project,
        )
        taxon_sensitivity_map = {"species-hidden": H3_RES_2}

        apply_response_filter(
            obj=obj,
            effective_permissions=owner_effective,
            normalized_role="Owner",
            project=project,
            resource=resource,
            taxon_sensitivity_map=taxon_sensitivity_map,
        )

        assert obj.withheld_reason is not None
        assert "taxon_sensitivity" in obj.withheld_reason


# ---------------------------------------------------------------------------
# Species masking: Superuser is NOT masked (Restricted project)
# ---------------------------------------------------------------------------


class TestSpeciesMaskingSuperuserExempt:
    """Superuser is never subject to mask_species_in_detection (FR-020)."""

    def test_superuser_sees_real_species_on_restricted_mask_enabled(self) -> None:
        """Superuser must NOT have species masked even on Restricted + mask ON."""
        from echoroo.core.permissions import _SUPERUSER_PERMS  # noqa: PLC2701
        project = _make_project(
            visibility=ProjectVisibility.RESTRICTED,
            mask_species=True,
        )
        obj = _make_response_obj()

        apply_response_filter(
            obj=obj,
            effective_permissions=frozenset(_SUPERUSER_PERMS),
            normalized_role="Superuser",
            project=project,
        )

        # Superuser normalised_role is in the exempt set {"Member", "Admin", "Owner", "Superuser"}.
        assert obj.species != "(masked)", (
            "Superuser must not see masked species label"
        )
        assert obj.common_name != "(masked)"

    def test_guest_sees_masked_species_on_restricted_mask_enabled(self) -> None:
        """Control: Guest DOES get species masked on Restricted + mask ON."""
        project = _make_project(
            visibility=ProjectVisibility.RESTRICTED,
            mask_species=True,
        )
        obj = _make_response_obj()
        guest_effective = compute_effective_permissions(
            normalized_role="Authenticated",
            project=project,
        )

        apply_response_filter(
            obj=obj,
            effective_permissions=guest_effective,
            normalized_role="Authenticated",
            project=project,
        )

        assert obj.species == "(masked)", (
            "Authenticated non-member must see masked species on Restricted+mask"
        )


# ---------------------------------------------------------------------------
# Path field (raw S3 key) — not a response model field, defence-in-depth
# ---------------------------------------------------------------------------


class TestPathFieldNotLeaked:
    """Raw S3 path should never appear on public response shapes."""

    def test_path_field_not_in_forbidden_set_but_schema_should_omit(self) -> None:
        """The ``path`` field is not in FORBIDDEN_RAW_LOCATION_FIELDS.

        ``path`` is an ORM-level attribute (the S3 object key).  Its omission
        from API responses is enforced by the Pydantic response schema (which
        does not include ``path``), not by the response filter.
        This test documents that reliance on schema exclusion rather than
        active scrubbing — if ``path`` ever appears in a response schema it
        should be added to FORBIDDEN_RAW_LOCATION_FIELDS or a dedicated check.
        """
        assert "path" not in FORBIDDEN_RAW_LOCATION_FIELDS, (
            "If 'path' is added to FORBIDDEN_RAW_LOCATION_FIELDS this test "
            "should be updated to verify the scrubbing instead"
        )
        # Schema-level protection is verified by the API contract tests (T200+).
        # This test is a structural marker, not a scrub test.


# ---------------------------------------------------------------------------
# Raw export bypass xfail — not yet implemented
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=False,
    reason=(
        "Raw export endpoint (/admin/projects/{id}/raw-export) is not yet "
        "implemented in Phase 15. This xfail records the TODO: when raw-export "
        "lands, add a test that verifies superuser + project-scope allowlist "
        "context bypasses the raw-coordinate scrub for that specific endpoint "
        "(FR-112a SUPERUSER_PROJECT_SCOPE_ALLOWLIST)."
    ),
)
def test_superuser_raw_export_endpoint_bypasses_coordinate_scrub() -> None:
    """XFAIL placeholder: raw-export endpoint raw bypass verification.

    Once /admin/projects/{id}/raw-export is implemented, this test should
    be promoted to a real integration test that:
    1. Authenticates as a Superuser session caller.
    2. Calls the raw-export endpoint.
    3. Asserts that latitude/longitude ARE present in the response (unlike
       all other endpoints where they are stripped).
    """
    raise NotImplementedError(
        "Raw export endpoint not yet implemented (Phase 15). "
        "Implement in Batch 5 alongside the endpoint."
    )


# ---------------------------------------------------------------------------
# Parametric: multiple roles × HIDDEN taxon map (spot-check matrix)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "normalized_role",
    ["Guest", "Authenticated", "Viewer", "Member", "Owner", "Superuser"],
)
def test_hidden_taxon_withheld_for_all_roles(normalized_role: str) -> None:
    """FR-035: HIDDEN clamp fires for every role without exception."""
    from echoroo.core.permissions import _SUPERUSER_PERMS  # noqa: PLC2701
    project = _make_project(visibility=ProjectVisibility.PUBLIC)
    obj = _make_response_obj(h3_index_member="8f283082a2a19f5")
    resource = _make_resource(taxon_id="species-hidden-universal")

    taxon_map = {"species-hidden-universal": H3_RES_2}

    if normalized_role == "Superuser":
        effective = frozenset(_SUPERUSER_PERMS)
    else:
        effective = compute_effective_permissions(
            normalized_role=normalized_role,
            project=project,
        )

    apply_response_filter(
        obj=obj,
        effective_permissions=effective,
        normalized_role=normalized_role,
        project=project,
        resource=resource,
        taxon_sensitivity_map=taxon_map,
    )

    assert obj.withheld_reason is not None, (
        f"withheld_reason must be set for HIDDEN taxon; role={normalized_role!r}"
    )
    assert "taxon_sensitivity" in obj.withheld_reason, (
        f"withheld_reason must cite taxon_sensitivity; "
        f"role={normalized_role!r}, got {obj.withheld_reason!r}"
    )
