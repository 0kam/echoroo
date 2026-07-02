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
    # W2-3 PR-16 — recording update/delete: the 2 browser-superseded
    # ``/api/v1/projects/{id}/recordings/{rid}`` PATCH/DELETE routes were
    # unmounted in favour of the BFF surface (``_recordings.py`` mutations).
    # The GET detail/audio/playback/spectrogram entries above were already
    # declared for the media/read BFF adapters.
    "/web-api/v1/projects/{project_id}/recordings/{recording_id} PATCH",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id} DELETE",
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
    # W2-2 B+C — self-scoped profile + API-token endpoints (GET /me already
    # migrated; these add the remaining five as transport-only delegators).
    "/web-api/v1/users/me PATCH",
    "/web-api/v1/users/me/password PUT",
    "/web-api/v1/users/me/api-tokens GET",
    "/web-api/v1/users/me/api-tokens POST",
    "/web-api/v1/users/me/api-tokens/{token_id} DELETE",
    # W2-3 PR-1 — public recorder catalog: the ``/api/v1/recorders`` list route
    # was unmounted; the surviving provider is the ``/web-api/v1/recorders`` BFF.
    "/web-api/v1/recorders GET",
    # W2-3 PR-3 — annotation segments: the unscoped ``/api/v1/segments/*`` routes
    # were unmounted in favour of the project-scoped BFF surface.
    "/web-api/v1/projects/{project_id}/segments/{segment_id} GET",
    "/web-api/v1/projects/{project_id}/segments/{segment_id} PATCH",
    "/web-api/v1/projects/{project_id}/segments/{segment_id}/annotations POST",
    "/web-api/v1/projects/{project_id}/segments/{segment_id}/notes POST",
    # W2-3 PR-4 — time-range annotations: the unscoped ``/api/v1/annotations/*``
    # routes were unmounted in favour of the project-scoped BFF surface.
    "/web-api/v1/projects/{project_id}/annotations/{annotation_id} PATCH",
    "/web-api/v1/projects/{project_id}/annotations/{annotation_id} DELETE",
    "/web-api/v1/projects/{project_id}/annotations/{annotation_id}/notes POST",
    # W2-3 PR-5 — cross-model evaluation: the unscoped ``/api/v1/annotation-sets/
    # */evaluate`` + ``/api/v1/evaluation-runs*`` routes were unmounted in favour
    # of the project-scoped BFF surface (the unscoped ``GET /evaluation-runs``
    # alias has no twin and was dropped outright).
    "/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/evaluate POST",
    "/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/evaluation-runs GET",
    "/web-api/v1/projects/{project_id}/evaluation-runs/{run_id} GET",
    "/web-api/v1/projects/{project_id}/evaluation-runs/{run_id} DELETE",
    # W2-3 PR-6 — annotation-set CRUD/palette/nested-segments: the unscoped
    # ``/api/v1/annotation-sets/*`` browser routes were unmounted in favour of the
    # project-scoped BFF surface (``dispatch_sampling`` / ``POST /{set_id}/sample``
    # has no BFF twin yet and stays mounted on v1).
    "/web-api/v1/projects/{project_id}/annotation-sets GET",
    "/web-api/v1/projects/{project_id}/annotation-sets POST",
    "/web-api/v1/projects/{project_id}/annotation-sets/{set_id} GET",
    "/web-api/v1/projects/{project_id}/annotation-sets/{set_id} PATCH",
    "/web-api/v1/projects/{project_id}/annotation-sets/{set_id} DELETE",
    "/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/palette POST",
    "/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/palette/{species_id} DELETE",
    "/web-api/v1/projects/{project_id}/annotation-sets/{set_id}/segments GET",
    # W2-3 PR-7 — generic annotation votes: the ``/api/v1/projects/{project_id}/
    # annotations/{id}/votes`` routes were unmounted in favour of the BFF surface
    # (the W2-1 ``detections/{id}/votes`` entries above are a separate surface).
    "/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes GET",
    "/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes POST",
    "/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes DELETE",
    # W2-3 PR-8 — project sites CRUD: the ``/api/v1/projects/{id}/sites*`` routes
    # were unmounted in favour of the project-scoped BFF surface.
    "/web-api/v1/projects/{project_id}/sites GET",
    "/web-api/v1/projects/{project_id}/sites POST",
    "/web-api/v1/projects/{project_id}/sites/{site_id} GET",
    "/web-api/v1/projects/{project_id}/sites/{site_id} PATCH",
    "/web-api/v1/projects/{project_id}/sites/{site_id} DELETE",
    # W2-3 PR-9 — project tags CRUD + GBIF suggest + statistics: the
    # ``/api/v1/projects/{id}/tags*`` routes were unmounted in favour of the
    # project-scoped BFF surface.
    "/web-api/v1/projects/{project_id}/tags GET",
    "/web-api/v1/projects/{project_id}/tags POST",
    "/web-api/v1/projects/{project_id}/tags/gbif-suggest GET",
    "/web-api/v1/projects/{project_id}/tags/statistics GET",
    "/web-api/v1/projects/{project_id}/tags/{tag_id} GET",
    "/web-api/v1/projects/{project_id}/tags/{tag_id} PATCH",
    "/web-api/v1/projects/{project_id}/tags/{tag_id} DELETE",
    # W2-3 PR-10 — dataset upload sessions: the ``/api/v1/.../datasets/{id}/
    # upload-sessions*`` routes were unmounted in favour of the BFF surface.
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions POST",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id}/complete POST",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/upload-sessions/{session_id} GET",
    # W2-3 PR-11 — admin surface (users / settings / recorders / licenses): the
    # 14 ``/api/v1/admin/*`` routes were unmounted in favour of the
    # ``/web-api/v1/admin/*`` BFF.
    "/web-api/v1/admin/users GET",
    "/web-api/v1/admin/users/{user_id} PATCH",
    "/web-api/v1/admin/settings GET",
    "/web-api/v1/admin/settings PATCH",
    "/web-api/v1/admin/recorders GET",
    "/web-api/v1/admin/recorders POST",
    "/web-api/v1/admin/recorders/{recorder_id} GET",
    "/web-api/v1/admin/recorders/{recorder_id} PATCH",
    "/web-api/v1/admin/recorders/{recorder_id} DELETE",
    "/web-api/v1/admin/licenses GET",
    "/web-api/v1/admin/licenses POST",
    "/web-api/v1/admin/licenses/{license_id} GET",
    "/web-api/v1/admin/licenses/{license_id} PATCH",
    "/web-api/v1/admin/licenses/{license_id} DELETE",
    # W2-3 PR-12 — dataset CRUD + import + datetime-config: the 12
    # browser-superseded ``/api/v1/projects/{id}/datasets*`` routes were
    # unmounted in favour of the BFF surface (export stays on v1). The GET
    # list / detail / statistics / datetime-config paths were already declared
    # by PR D above; only the mutation + lifecycle paths are new here.
    "/web-api/v1/projects/{project_id}/datasets POST",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id} PATCH",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id} DELETE",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/import POST",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/import-status GET",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/auto-detect POST",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/test POST",
    "/web-api/v1/projects/{project_id}/datasets/{dataset_id}/datetime-config/apply POST",
    # W2-3 PR-13 — recording clip CRUD + auto-generate: the 6 browser-superseded
    # ``/api/v1/projects/{id}/recordings/{rid}/clips*`` routes were unmounted in
    # favour of the BFF surface (``_media.py`` GETs + ``_clips.py`` mutations).
    # The audio / spectrogram / download media GETs stay on v1 and are not
    # declared here.
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips GET",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips POST",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/generate POST",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} GET",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} PATCH",
    "/web-api/v1/projects/{project_id}/recordings/{recording_id}/clips/{clip_id} DELETE",
    # W2-3 PR-14 — detection-run lifecycle: the 5 browser-superseded
    # ``/api/v1/.../detection-runs*`` routes (list / create / retry / cancel +
    # unscoped available-models) were unmounted in favour of the BFF surface
    # (get / update stay on v1). The GET list + available-models paths were
    # already declared by PR D above; only the create / retry / cancel mutation
    # paths are new here.
    "/web-api/v1/projects/{project_id}/detection-runs POST",
    "/web-api/v1/projects/{project_id}/detection-runs/{run_id}/retry POST",
    "/web-api/v1/projects/{project_id}/detection-runs/{run_id}/cancel POST",
    # W2-3 PR-15 — custom-model (custom-SVM classifier) surface: the 13
    # ``/api/v1/projects/{id}/custom-models*`` routes (list / create / get /
    # update / delete / train / status / apply / detection-runs / seed-samples /
    # suggest-samples / sampling-rounds list+detail) were unmounted in favour of
    # the ``/web-api/v1/.../custom-models*`` BFF surface.
    "/web-api/v1/projects/{project_id}/custom-models GET",
    "/web-api/v1/projects/{project_id}/custom-models POST",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id} GET",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id} PATCH",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id} DELETE",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id}/train POST",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id}/status GET",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id}/apply POST",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id}/detection-runs GET",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id}/seed-samples POST",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id}/suggest-samples POST",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id}/sampling-rounds GET",
    "/web-api/v1/projects/{project_id}/custom-models/{model_id}/sampling-rounds/{round_id} GET",
    # W2-3 PR-17 — detection mutations + exports: the 10 browser-superseded
    # ``/api/v1/projects/{id}/detections*`` routes (list / species-summary /
    # temporal-data / create / change-species / export-csv / export-ml-dataset +
    # the three vote handlers) were unmounted in favour of the BFF surface. The
    # list / species-summary / temporal-data GET paths (PR D) and the three vote
    # GET/POST/DELETE paths (W2-1) were already declared above; only the create
    # POST, change-species POST, and the two export GETs are new here. The 4
    # single-detection routes (get/confirm/reject/delete) stay on v1.
    "/web-api/v1/projects/{project_id}/detections POST",
    "/web-api/v1/projects/{project_id}/detections/{detection_id}/change-species POST",
    "/web-api/v1/projects/{project_id}/detections/export/csv GET",
    "/web-api/v1/projects/{project_id}/detections/export/ml-dataset GET",
]
