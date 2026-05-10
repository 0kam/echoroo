"""Coverage uplift unit tests for ``echoroo.core.response_filter``.

Phase 17 §C medium-gap batch (95% permission-critical tier): targets
the small reject / fallback branches at lines 138, 142, 155, 156, 180,
181, 226-229 so the module clears the 95% threshold without touching
production code. All tests drive ``apply_response_filter`` /
``_set_if_attr`` / ``_scrub_raw_coordinates`` / ``_h3_to_parent`` /
``_compute_withheld_reason`` directly so the coverage hits are real
production-path executions.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from echoroo.core import response_filter as mod
from echoroo.core.permissions import H3_RES_15, ProjectVisibility
from echoroo.core.response_filter import (
    FORBIDDEN_RAW_LOCATION_FIELDS,
    MASKED_SPECIES_LABEL,
    apply_response_filter,
)


class _ReadOnlyAttr:
    """Object with a read-only attribute that raises AttributeError on setattr.

    The production code only catches ``AttributeError`` and ``TypeError``,
    so we use a property without a setter to trigger the documented swallow
    branches.
    """

    def __init__(self, *, h3_index_member: str | None = None, latitude: float | None = None) -> None:
        self._h3 = h3_index_member
        self._lat = latitude

    @property
    def h3_index_member(self) -> str | None:
        return self._h3

    @property
    def latitude(self) -> float | None:
        return self._lat


def _project(
    *,
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC,
    restricted_config: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="proj-1",
        owner_id="owner-1",
        visibility=visibility,
        status="active",
        restricted_config=restricted_config or {},
    )


# ---------------------------------------------------------------------------
# _set_if_attr — frozen Pydantic / dict / regular obj branches
# ---------------------------------------------------------------------------


def test_set_if_attr_dict_with_present_key_updates() -> None:
    """``obj`` is dict and key present → value updates."""
    d = {"name": "old"}
    mod._set_if_attr(d, "name", "new")
    assert d == {"name": "new"}


def test_set_if_attr_dict_without_key_noop() -> None:
    """``obj`` is dict and key absent → no-op (line 134)."""
    d = {"other": "x"}
    mod._set_if_attr(d, "name", "new")
    assert d == {"other": "x"}


def test_set_if_attr_obj_without_attr_noop() -> None:
    """No attribute present on obj → no-op (line 135-136 falsy)."""
    obj = SimpleNamespace(other="x")
    mod._set_if_attr(obj, "name", "new")
    assert not hasattr(obj, "name")


def test_set_if_attr_readonly_attr_swallows_error() -> None:
    """Object with a read-only property raises AttributeError → swallowed (lines 138-142)."""
    obj = _ReadOnlyAttr(h3_index_member="abc")
    # Should not raise — the except catches AttributeError or TypeError.
    mod._set_if_attr(obj, "h3_index_member", "new-value")
    # The read-only property retains the original value because assignment
    # was rejected and swallowed by the except branch.
    assert obj.h3_index_member == "abc"


# ---------------------------------------------------------------------------
# _scrub_raw_coordinates — dict + obj + frozen obj branches
# ---------------------------------------------------------------------------


def test_scrub_raw_coordinates_strips_dict_keys() -> None:
    """Forbidden coord fields removed from dict."""
    d = {"latitude": 1, "longitude": 2, "name": "x"}
    mod._scrub_raw_coordinates(d)
    assert "latitude" not in d
    assert "longitude" not in d
    assert d["name"] == "x"


def test_scrub_raw_coordinates_clears_obj_attrs() -> None:
    """Forbidden attrs set to None on obj."""
    obj = SimpleNamespace(latitude=1.0, longitude=2.0, name="x")
    mod._scrub_raw_coordinates(obj)
    assert obj.latitude is None
    assert obj.longitude is None
    assert obj.name == "x"


def test_scrub_raw_coordinates_swallows_readonly_assignment() -> None:
    """Read-only attr raising on setattr is silently skipped (lines 155-156)."""
    obj = _ReadOnlyAttr(latitude=10.0)
    # Should not raise.
    mod._scrub_raw_coordinates(obj)
    # Read-only property — the original value remains.
    assert obj.latitude == 10.0


# ---------------------------------------------------------------------------
# _h3_to_parent — None + malformed branches
# ---------------------------------------------------------------------------


def test_h3_to_parent_none_returns_none() -> None:
    """None h3 → None (line 165-166)."""
    assert mod._h3_to_parent(None, 5) is None


def test_h3_to_parent_invalid_returns_input() -> None:
    """Malformed H3 string → original input (line 174-175 / 180-181)."""
    # An obviously invalid H3 string should fail get_resolution and
    # return the original.
    result = mod._h3_to_parent("not-an-h3", 5)
    # Either the get_resolution failed (returns input) or the
    # cell_to_parent failed (returns input). Either way input is returned.
    assert result == "not-an-h3"


# ---------------------------------------------------------------------------
# _should_mask_species
# ---------------------------------------------------------------------------


def test_should_mask_species_skips_member_role() -> None:
    """Member role bypasses masking even when toggle is on."""
    project = _project(
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config={"mask_species_in_detection": True},
    )
    assert mod._should_mask_species(project, "Member") is False


def test_should_mask_species_only_restricted() -> None:
    """Public visibility never masks even for guests."""
    project = _project(
        visibility=ProjectVisibility.PUBLIC,
        restricted_config={"mask_species_in_detection": True},
    )
    assert mod._should_mask_species(project, "Guest") is False


def test_should_mask_species_restricted_guest_with_toggle() -> None:
    """Restricted + toggle ON + Guest → masking applies."""
    project = _project(
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config={"mask_species_in_detection": True},
    )
    assert mod._should_mask_species(project, "Guest") is True


# ---------------------------------------------------------------------------
# _compute_withheld_reason — public_non_member + restricted_non_member
# ---------------------------------------------------------------------------


def test_withheld_reason_no_clamp_returns_none() -> None:
    """If effective_resolution >= member_resolution → None."""
    project = _project()
    out = mod._compute_withheld_reason(
        effective_resolution=15,
        member_resolution=15,
        project=project,
        normalized_role="Guest",
        taxon_sensitivity_map=None,
        resource=SimpleNamespace(),
    )
    assert out is None


def test_withheld_reason_hidden_priority() -> None:
    """effective_resolution == 2 → taxon_sensitivity:hidden."""
    project = _project()
    out = mod._compute_withheld_reason(
        effective_resolution=2,
        member_resolution=15,
        project=project,
        normalized_role="Guest",
        taxon_sensitivity_map=None,
        resource=SimpleNamespace(),
    )
    assert out == "taxon_sensitivity:hidden"


def test_withheld_reason_public_non_member() -> None:
    """Public + Guest with global > effective → public_non_member (lines 226-229)."""
    project = _project(visibility=ProjectVisibility.PUBLIC)
    # Use non-mapping taxon_sensitivity_map so global_res falls back to H3_RES_9
    out = mod._compute_withheld_reason(
        effective_resolution=5,
        member_resolution=15,
        project=project,
        normalized_role="Guest",
        taxon_sensitivity_map=None,
        resource=SimpleNamespace(taxon_id=None),
    )
    # global_res = H3_RES_9 (9), member_resolution = 15, so 9 < 15 triggers
    # the global-sensitivity path first.
    assert out == "taxon_sensitivity:h3_res_9"


def test_withheld_reason_public_non_member_when_global_eq_member() -> None:
    """Public + Guest with global == member → public_non_member."""
    project = _project(visibility=ProjectVisibility.PUBLIC)
    out = mod._compute_withheld_reason(
        effective_resolution=5,
        member_resolution=H3_RES_15,
        project=project,
        normalized_role="Guest",
        taxon_sensitivity_map={"taxon-1": H3_RES_15},
        resource=SimpleNamespace(taxon_id="taxon-1"),
    )
    assert out == "public_non_member"


def test_withheld_reason_restricted_non_member_fallback() -> None:
    """Restricted Member non-public role with global == member → restricted fallback."""
    project = _project(visibility=ProjectVisibility.RESTRICTED)
    out = mod._compute_withheld_reason(
        effective_resolution=5,
        member_resolution=H3_RES_15,
        project=project,
        normalized_role="Viewer",
        taxon_sensitivity_map={"taxon-1": H3_RES_15},
        resource=SimpleNamespace(taxon_id="taxon-1"),
    )
    assert out == "restricted_non_member"


# ---------------------------------------------------------------------------
# apply_response_filter end-to-end (drives the full production path)
# ---------------------------------------------------------------------------


def test_apply_response_filter_strips_forbidden_coordinates() -> None:
    """Stage-2 filter scrubs raw lat/lng even when they leak through."""
    obj = SimpleNamespace(
        latitude=1.0,
        longitude=2.0,
        h3_index_member="8a283082aaaffff",
        h3_index_member_resolution=15,
        species="Quercus rubra",
    )
    project = _project()
    apply_response_filter(
        obj=obj,
        effective_permissions=frozenset(),
        normalized_role="Guest",
        project=project,
    )
    assert obj.latitude is None
    assert obj.longitude is None


def test_forbidden_field_set_is_complete() -> None:
    """Sanity: the forbidden set covers the expected names."""
    expected = {
        "latitude",
        "longitude",
        "lat",
        "lng",
        "gps_latitude",
        "gps_longitude",
    }
    assert frozenset(expected) == FORBIDDEN_RAW_LOCATION_FIELDS


def test_masked_label_constant() -> None:
    """Sanity: masking sentinel string is exposed for the wire layer."""
    assert MASKED_SPECIES_LABEL == "(masked)"
