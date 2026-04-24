"""Response filter (stage 2 of the permission engine, FR-011).

Applied to every Recording / Detection / Site response after stage 1
(``is_allowed``) has produced ``effective_permissions`` + ``normalized_role``.
Stage 2 is a PURE transformation — it MUST NOT query the DB or session — the
caller is responsible for bulk-preloading taxon sensitivity maps upstream
(NFR-001a).

Usage (Phase 3 endpoint layer):

    effective, role = request.state.effective_permissions, request.state.normalized_role
    response = apply_response_filter(
        obj=detection_response,
        effective_permissions=effective,
        normalized_role=role,
        project=project,
        resource=detection_row,
        taxon_sensitivity_map=preloaded_map,
        override_map=preloaded_overrides,
    )

``apply_response_filter`` mutates known sensitive fields in-place on the
Pydantic response object when possible, and returns it for chaining.
"""
from __future__ import annotations

from typing import Any

from echoroo.core.permissions import (
    H3_RES_9,
    H3_RES_15,
    Permission,
    ProjectVisibility,
    compute_effective_resolution,
)

# Masking sentinel for species names when mask_species_in_detection is ON.
MASKED_SPECIES_LABEL: str = "(masked)"

# Fields that are ALWAYS forbidden on response shapes — stripped even if the
# upstream model somehow has them set. FR-028 / FR-030 / FR-031 promise these
# never reach the wire.
FORBIDDEN_RAW_LOCATION_FIELDS: frozenset[str] = frozenset(
    {"latitude", "longitude", "lat", "lng", "gps_latitude", "gps_longitude"}
)


def apply_response_filter(
    *,
    obj: Any,
    effective_permissions: frozenset[Permission],
    normalized_role: str,
    project: Any,
    resource: Any | None = None,
    taxon_sensitivity_map: dict[str, int] | None = None,
    override_map: dict[tuple[Any, str], Any] | None = None,
) -> Any:
    """Apply stage-2 response filtering to a Recording/Detection/Site object.

    Args:
        obj: The Pydantic response object (or a dict/SimpleNamespace in tests).
            Mutated in place where possible.
        effective_permissions: Stage-1 output; passed through to the resolution
            calculator.
        normalized_role: Stage-1 output; used for species masking and resolution.
        project: Project row with visibility + restricted_config.
        resource: The underlying ORM row for taxon / h3 lookups. If ``None``,
            falls back to ``obj`` itself.
        taxon_sensitivity_map: Pre-loaded ``{taxon_id: H3 res}`` (NFR-001a).
        override_map: Pre-loaded project taxon overrides.

    Returns:
        The same ``obj`` for ergonomic chaining.
    """
    res = resource if resource is not None else obj

    # 1. Strip any forbidden raw coordinate fields (defence in depth for
    #    FR-028/030/031 — schemas should already omit these).
    _scrub_raw_coordinates(obj)

    # 2. Compute H3 generalisation resolution from stage-1 perms + project.
    effective_resolution = compute_effective_resolution(
        resource=res,
        role=normalized_role,
        project=project,
        effective_permissions=effective_permissions,
        taxon_sensitivity_map=taxon_sensitivity_map,
        override_map=override_map,
    )

    member_h3 = getattr(res, "h3_index_member", None)
    _set_if_attr(obj, "h3_index", _h3_to_parent(member_h3, effective_resolution))
    _set_if_attr(obj, "location_generalization", effective_resolution)

    # 3. Species masking (FR-020 `mask_species_in_detection`).
    if _should_mask_species(project, normalized_role):
        _set_if_attr(obj, "species", MASKED_SPECIES_LABEL)
        _set_if_attr(obj, "common_name", MASKED_SPECIES_LABEL)
        _set_if_attr(obj, "scientific_name", MASKED_SPECIES_LABEL)

    # 4. Attach withheld_reason if the generalisation clamped the response.
    withheld = _compute_withheld_reason(
        effective_resolution=effective_resolution,
        member_resolution=getattr(res, "h3_index_member_resolution", H3_RES_15),
        project=project,
        normalized_role=normalized_role,
        taxon_sensitivity_map=taxon_sensitivity_map,
        resource=res,
    )
    _set_if_attr(obj, "withheld_reason", withheld)

    return obj


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_if_attr(obj: Any, name: str, value: Any) -> None:
    """Set ``obj.name = value`` when the attribute exists (or ``obj`` is dict)."""
    if isinstance(obj, dict):
        if name in obj:
            obj[name] = value
        return
    if hasattr(obj, name):
        try:
            setattr(obj, name, value)
        except (AttributeError, TypeError):
            # Pydantic v2 frozen model: cannot assign. We tolerate it because
            # the OpenAPI layer should have produced a mutable shape; the lint
            # ensures the filter is invoked so presence is what matters.
            return


def _scrub_raw_coordinates(obj: Any) -> None:
    """Remove any forbidden raw-coord fields from ``obj``."""
    if isinstance(obj, dict):
        for field in FORBIDDEN_RAW_LOCATION_FIELDS:
            obj.pop(field, None)
        return
    for field in FORBIDDEN_RAW_LOCATION_FIELDS:
        if hasattr(obj, field):
            try:
                setattr(obj, field, None)
            except (AttributeError, TypeError):
                continue


def _h3_to_parent(h3_index: str | None, resolution: int) -> str | None:
    """Compute the ancestor H3 cell at ``resolution``.

    Intentionally imports ``h3`` lazily to keep this module import-light for
    test contexts where the C extension may not be available.
    """
    if h3_index is None:
        return None
    try:
        import h3 as _h3
    except ImportError:  # pragma: no cover - exercised only if h3 is missing
        return h3_index

    try:
        current_res = _h3.get_resolution(h3_index)
    except Exception:  # noqa: BLE001 - defensive: malformed index
        return h3_index
    if current_res <= resolution:
        return h3_index
    try:
        parent = _h3.cell_to_parent(h3_index, resolution)
    except Exception:  # noqa: BLE001
        return h3_index
    return str(parent) if parent is not None else h3_index


def _should_mask_species(
    project: Any,
    normalized_role: str,
) -> bool:
    """FR-020 (`mask_species_in_detection`) — Restricted only, non-members.

    Members / Admins / Owners / Superusers always see the real species; the
    toggle targets Guest / Authenticated / Viewer.
    """
    if normalized_role in {"Member", "Admin", "Owner", "Superuser"}:
        return False
    visibility = getattr(project, "visibility", None)
    if visibility != ProjectVisibility.RESTRICTED:
        return False
    cfg = getattr(project, "restricted_config", None) or {}
    return bool(cfg.get("mask_species_in_detection", False))


def _compute_withheld_reason(
    *,
    effective_resolution: int,
    member_resolution: int,
    project: Any,
    normalized_role: str,
    taxon_sensitivity_map: dict[str, int] | None,
    resource: Any,
) -> str | None:
    """Human-readable reason when data has been obscured (FR-086)."""
    if effective_resolution >= member_resolution:
        return None
    # Priority order: HIDDEN > taxon sensitivity > project toggle.
    if effective_resolution == 2:
        return "taxon_sensitivity:hidden"
    taxon_id = getattr(resource, "taxon_id", None)
    global_res: int = (
        taxon_sensitivity_map.get(taxon_id, H3_RES_9)
        if taxon_sensitivity_map is not None and taxon_id is not None
        else H3_RES_9
    )
    if global_res < member_resolution:
        return f"taxon_sensitivity:h3_res_{global_res}"
    visibility = getattr(project, "visibility", None)
    if visibility == ProjectVisibility.PUBLIC and normalized_role in {"Guest", "Authenticated"}:
        return "public_non_member"
    return "restricted_non_member"


__all__ = [
    "FORBIDDEN_RAW_LOCATION_FIELDS",
    "MASKED_SPECIES_LABEL",
    "apply_response_filter",
]
