"""Web UI v1 ``/projects`` router package (T118, FR-006).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

This package houses the Cookie + CSRF Web UI surface for project CRUD,
membership management, restricted-config toggles, and license metadata.
The router is intentionally split across four submodules so each
concern stays small enough to review in isolation:

* :mod:`._core` — project CRUD
  (``GET /``, ``POST /``, ``GET /{id}``, ``PUT /{id}``, ``DELETE /{id}``;
  T126).
* :mod:`._members` — membership + invitation handling
  (``GET/POST/PATCH/DELETE /{id}/members``,
  ``POST /{id}/invitations/{token}/accept``,
  ``DELETE /{id}/invitations/{token}``).
* :mod:`._restricted_config` — restricted-mode flag toggles
  (``PATCH /{id}/restricted-config``; FR-014, FR-020 .. FR-022).
* :mod:`._license` — dataset license metadata
  (``PUT /{id}/license``, ``GET /{id}/license-history``;
  FR-085, FR-087).

Each submodule defines its own ``router = APIRouter()`` (no prefix) and
this package mounts them under a shared ``/projects`` prefix. Path
operations are intentionally empty in T118 — the actual handlers land
in T120-T127 during Phase 3. The aggregator router is **not** wired
into the FastAPI app yet; that registration (with the ``/web-api/v1``
prefix and CSRF middleware) happens later in Phase 3.
"""

from __future__ import annotations

from fastapi import APIRouter

from echoroo.api.web_v1 import trusted as trusted_module

from . import (
    _annotation_projects,
    _annotation_tasks,
    _annotations,
    _clips,
    _core,
    _datasets,
    _detection_runs,
    _detections,
    _license,
    _media,
    _members,
    _overview,
    _ownership,
    _recordings,
    _restricted_config,
    _sites,
    _tags,
    _uploads,
    _votes,
)

router = APIRouter(prefix="/projects", tags=["projects"])

# Project CRUD — ``GET /``, ``POST /``, ``GET/PUT/DELETE /{project_id}``.
router.include_router(_core.router)

# Restricted-config toggle — ``PATCH /{project_id}/restricted-config``.
router.include_router(_restricted_config.router)

# License metadata — ``PUT /{project_id}/license`` and history.
router.include_router(_license.router)

# Members + invitations — ``/{project_id}/members`` and
# ``/{project_id}/invitations/{token}/...`` paths.
router.include_router(_members.router)

# Overview aggregation — ``GET /{project_id}/overview``.
router.include_router(_overview.router)

# Ownership transfer (Phase 12 / T700) — ``/{project_id}/transfer-ownership``.
router.include_router(_ownership.router)

# Media streams + exports (spec/009 PR D0) — legacy behavior adapters for
# ``/{project_id}/recordings/{recording_id}/...`` and export downloads.
router.include_router(_media.router)

# Recording write mutations (spec/009 PR 2) — PATCH / DELETE on
# ``/{project_id}/recordings/{recording_id}``. Kept separate from
# ``_media`` so the mutation surface is reviewable independently of the
# media streaming surface.
router.include_router(_recordings.router)

# Dataset reads used by the PR D data export screen.
router.include_router(_datasets.router)

# Detection-run reads used by dataset status panels rendered on the export page.
router.include_router(_detection_runs.router)

# Detection reads used by the project detections page.
router.include_router(_detections.router)

# Annotation project/task reads and mutations needed by the PR D annotation
# screen before export and batch-tag interactions can run.
router.include_router(_annotation_projects.router)
router.include_router(_annotation_tasks.router)

# Annotation mutations (spec/009 PR D) — legacy behavior adapter for
# ``/{project_id}/clip-annotations/batch-tag``.
router.include_router(_annotations.router)

# Site CRUD (spec/009 PR 3a) — ``/{project_id}/sites``.
router.include_router(_sites.router)

# Tag CRUD + GBIF helpers + statistics (spec/009 PR 3a) — ``/{project_id}/tags``.
router.include_router(_tags.router)

# Clip write mutations (spec/009 PR 3a) — ``/{project_id}/recordings/{recording_id}/clips``
# POST / PATCH / DELETE / generate. The GET list + GET detail counterparts
# already live in ``_media`` so this module only owns the write surface.
router.include_router(_clips.router)

# Upload-session lifecycle (spec/009 PR 3a) — presigned URL issue +
# completion + status polling under ``/{project_id}/datasets/{dataset_id}/upload-sessions``.
router.include_router(_uploads.router)

# Generic annotation votes (spec/009 PR 3a) — ``/{project_id}/annotations/{annotation_id}/votes``.
# The detection-vote path (``/detections/{id}/votes``) is intentionally not
# in scope here and remains on ``/api/v1`` until the detection BFF is
# extended.
router.include_router(_votes.router)

# Trusted overlay management (Phase 10 / T510) — Owner/Admin enumeration
# under the same ``/projects`` prefix as the rest of the project surface.
router.include_router(trusted_module.router)


__all__ = ["router"]
