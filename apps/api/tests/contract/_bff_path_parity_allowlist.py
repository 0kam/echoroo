"""BFF path parity allowlist consumed by PR J's test_bff_path_parity.py.

Spec/009 (browser API → BFF migration) — each per-resource PR (A2 / B /
C / D / E / F / G / H) appends the `/web-api/v1/*` paths it adds to the
list below. PR J's test then asserts each entry is present in the live
OpenAPI surface.

This file is intentionally a Python module (not YAML) so it can be
imported directly by the test and edits track as code changes.
"""

from __future__ import annotations

# Live-form BFF paths declared by this migration. Each per-PR appends
# its paths here (e.g. "/web-api/v1/projects" GET, "/web-api/v1/projects"
# POST, "/web-api/v1/projects/{project_id}" PATCH, etc.).
#
# Entry format: a string in the live OpenAPI form (i.e. with the
# `/web-api/v1` prefix), suffixed by " " + the uppercase HTTP method
# (e.g. "/web-api/v1/projects POST"). PR J's test parses these on the
# space and looks each up in the live FastAPI OpenAPI dict.
BFF_PATHS_DECLARED_BY_SPEC_009: list[str] = [
    # PR B — residual auth follow-up (frontend-only rewire, 2026-05-13)
    #
    # spec/011 §FR-011-005 / Step 10 removed the
    # ``/web-api/v1/auth/password-reset/{request,confirm}`` and
    # ``/web-api/v1/auth/verify-email`` BFF mirrors; only the
    # ``/web-api/v1/auth/register`` entry survives. The deleted entries
    # were removed alongside the underlying route handlers in T119.
    "/web-api/v1/auth/register POST",
    # PR A — projects read subset (frontend-only rewire, 2026-05-13)
    "/web-api/v1/projects GET",
    "/web-api/v1/projects/{project_id} GET",
    "/web-api/v1/projects/{project_id}/recordings GET",
    # PR D0 — media streams + exports
    "/web-api/v1/projects/{project_id}/recordings/{recording_id} GET",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/audio GET",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/playback GET",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/spectrogram GET",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/export GET",
    # PR D — annotation mutations
    "/web-api/v1/projects/{project_id}/datasets GET",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id} GET",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/statistics GET",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config GET",
    "/web-api/v1/projects/{project_id}/detection-runs GET",
    "/web-api/v1/projects/{project_id}/detections GET",
    "/web-api/v1/projects/{project_id}/detections/species-summary GET",
    "/web-api/v1/projects/{project_id}/detections/temporal-data GET",
    # PR A2 — projects mutations + missing read adapters
    "/web-api/v1/projects POST",
    "/web-api/v1/projects/{project_id} PATCH",
    "/web-api/v1/projects/{project_id} DELETE",
    "/web-api/v1/projects/{project_id}/members GET",
    # NOTE (2026-06-03, preview feedback #7): the direct member-add route
    # ("/web-api/v1/projects/{project_id}/members POST") was removed —
    # adding a user to a project is invitation-only.
    "/web-api/v1/projects/{project_id}/members/{user_id} PATCH",
    "/web-api/v1/projects/{project_id}/members/{user_id} DELETE",
    "/web-api/v1/projects/{project_id}/overview GET",
    # PR C — taxa search + GBIF lookup
    "/web-api/v1/taxa/search GET",
    "/web-api/v1/taxa/gbif-search GET",
    # WS-A PR3a — materialise a GBIF pick into a local taxon (preview #2)
    "/web-api/v1/taxa/from-gbif POST",
    # PR D — detection model discovery used by dataset export/status pages
    "/web-api/v1/detection-runs/available-models GET",
    # Admin maintenance surface — Celery task triggers (replaces shell access)
    "/web-api/v1/admin/taxon/seed-birdnet POST",
    "/web-api/v1/admin/taxon/sync-vernacular POST",
    # W2-1 — detection votes (detection review grid)
    "/web-api/v1/projects/{project_id}/detections/{detection_id}/votes GET",
    "/web-api/v1/projects/{project_id}/detections/{detection_id}/votes POST",
    "/web-api/v1/projects/{project_id}/detections/{detection_id}/votes DELETE",
    # W2-2-A — first-run setup wizard (unauth + CSRF-exempt bootstrap)
    "/web-api/v1/setup/status GET",
    "/web-api/v1/setup/initialize POST",
]
