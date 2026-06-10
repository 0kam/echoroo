"""Deployment-export location-generalization parity tests.

The CamtrapDP ``deployments.csv`` (``ExportService.generate_deployments_csv``)
emits three trailing columns — ``h3_cell_id`` / ``h3_resolution`` /
``withheld_reason`` — and derives ``latitude`` / ``longitude`` from the
EFFECTIVE (possibly coarsened) H3 cell so an obscured Restricted site never
leaks a precise center.

These tests drive the shared helper
:meth:`DetectionExportService.compute_export_location_cell` directly (no DB),
mirroring the in-memory style of ``test_camtrap_id_consistency.py``. The helper
is the single source of truth the deployment writer calls, so exercising it
covers the column values + lat/long derivation without standing up repositories.
"""

from __future__ import annotations

from types import SimpleNamespace

import h3

from echoroo.models.enums import ProjectVisibility
from echoroo.services.detection_export import DetectionExportService
from echoroo.services.h3_utils import h3_to_center

# A precise member cell at resolution 12 (well below the natural-res ceiling).
_SITE_RES = 12
_SITE_CELL = h3.latlng_to_cell(35.0, 139.0, _SITE_RES)


def _public_project() -> SimpleNamespace:
    return SimpleNamespace(visibility=ProjectVisibility.PUBLIC, restricted_config={})


def _restricted_project(toggle_res: int) -> SimpleNamespace:
    return SimpleNamespace(
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config={"public_location_precision_h3_res": toggle_res},
    )


def test_public_project_keeps_precise_cell() -> None:
    """Public project: effective cell == site cell, natural res, no reason."""
    cell, res, reason = DetectionExportService.compute_export_location_cell(
        project=_public_project(),
        site_h3_index=_SITE_CELL,
        site_resolution=_SITE_RES,
    )

    assert cell == _SITE_CELL
    assert res == _SITE_RES
    assert reason is None

    # lat/long the writer would emit derive from the EFFECTIVE cell and must
    # equal the precise center for a Public project.
    assert h3_to_center(cell) == h3_to_center(_SITE_CELL)


def test_restricted_toggle_below_site_res_coarsens_and_flags() -> None:
    """Restricted toggle < site res: coarsen to toggle, reason='project_toggle'.

    lat/long derive from the COARSENED cell center, NOT the precise center, so
    no precise coordinate leaks and lat/long agrees with the emitted cell id.
    """
    toggle_res = 8
    cell, res, reason = DetectionExportService.compute_export_location_cell(
        project=_restricted_project(toggle_res),
        site_h3_index=_SITE_CELL,
        site_resolution=_SITE_RES,
    )

    expected_cell = h3.cell_to_parent(_SITE_CELL, toggle_res)
    assert cell == expected_cell
    assert res == toggle_res
    assert reason == "project_toggle"

    # The coarsened cell's center differs from the precise center (no leak),
    # and matches the cell the writer would derive lat/long from.
    assert h3_to_center(cell) == h3_to_center(expected_cell)
    assert h3_to_center(cell) != h3_to_center(_SITE_CELL)


def test_restricted_toggle_not_below_site_res_no_clamp() -> None:
    """Restricted toggle >= site res: keep site cell/res, reason=None (no clamp)."""
    toggle_res = _SITE_RES  # equal -> not below -> no clamp
    cell, res, reason = DetectionExportService.compute_export_location_cell(
        project=_restricted_project(toggle_res),
        site_h3_index=_SITE_CELL,
        site_resolution=_SITE_RES,
    )

    assert cell == _SITE_CELL
    assert res == toggle_res
    assert reason is None


def test_no_site_h3_yields_empty_effective_cell() -> None:
    """No H3 index: effective cell is None so the writer emits empty columns."""
    cell, res, reason = DetectionExportService.compute_export_location_cell(
        project=_public_project(),
        site_h3_index=None,
        site_resolution=_SITE_RES,
    )

    assert cell is None
    # The writer emits "" for h3_cell_id (and skips lat/long) when cell is None;
    # resolution/reason are still well-defined but unused by the writer.
    assert reason is None


def test_no_project_keeps_natural_resolution() -> None:
    """No project context: natural resolution, no withheld reason."""
    cell, res, reason = DetectionExportService.compute_export_location_cell(
        project=None,
        site_h3_index=_SITE_CELL,
        site_resolution=_SITE_RES,
    )

    assert cell == _SITE_CELL
    assert res == _SITE_RES
    assert reason is None
