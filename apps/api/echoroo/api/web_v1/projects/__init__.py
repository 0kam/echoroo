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
  (``GET/PATCH/DELETE /{id}/members`` — direct add removed 2026-06-03,
  invitation-only per preview feedback #7,
  ``POST /{id}/invitations`` issue,
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
    _annotation_set_export,
    _annotation_sets,
    _clips,
    _core,
    _custom_models,
    _datasets,
    _detection_export,
    _detection_runs,
    _detections,
    _license,
    _media,
    _members,
    _overview,
    _ownership,
    _recordings,
    _restricted_config,
    _search,
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

# Custom-model ML lifecycle (spec/009 PR 3b) — ``/{project_id}/custom-models/...``.
# 13 endpoints covering CRUD, training, status polling, dataset apply,
# detection-run listing, and seed/active-learning sampling rounds. All
# routes are centrally gated through ``gate_action`` (no allowlist
# entries required).
router.include_router(_custom_models.router)

# Detection export (spec/009 PR 4) — ``/{project_id}/detections/export/...``.
# Two streaming endpoints (CSV row-by-row + ZIP archive) delegated to the
# legacy ``detections.py`` handlers. Mounted BEFORE ``_search.router`` so
# the literal ``/detections/export/*`` segments win deterministically over
# any future ``/detections/{id}/...`` adapter additions.
router.include_router(_detection_export.router)

# Annotation-set CSV export (CamtrapDP + FR-086 + offset columns) — mounted BEFORE
# ``_annotation_sets.router`` so the literal
# ``/annotation-sets/{set_id}/export/csv`` path is declared adjacent to (and
# ahead of) the broader annotation-set surface, mirroring how
# ``_detection_export`` is mounted ahead of ``_search``. Fires ``gate_action``
# with the same set-view Action as the annotation-set GET endpoint.
router.include_router(_annotation_set_export.router)

# Annotation-set ground-truth + segment + evaluation surface (spec/009 PR 4).
# 18 endpoints covering AnnotationSet CRUD, Palette, Segment lifecycle,
# TimeRangeAnnotation lifecycle, notes, and EvaluationRun lifecycle. Each
# BFF adapter project-scopes a legacy path that originally lived under the
# tenant-wide ``/api/v1/annotation-sets`` / ``/segments`` / ``/annotations``
# / ``/evaluation-runs`` mounts (no allowlist entries required — every BFF
# handler fires ``gate_action`` even though the legacy handlers do not).
router.include_router(_annotation_sets.router)

# Search surface (spec/009 PR 4) — ``/{project_id}/search/...``,
# ``/{project_id}/xeno-canto/...``, ``/{project_id}/annotations``.
# 16 endpoints covering session CRUD, distribution / sample, batch
# submission + polling, embedding stats, Xeno-canto proxy, and search
# annotation creation (plus 2 streaming CSV exports). Each route fires a
# per-endpoint Action gate at the BFF layer before delegating to the
# legacy handler (whose own ``AuthorizedSearchSessionServiceDep`` re-fires
# ``SEARCH_SESSION_LIST_ACTION`` idempotently).
router.include_router(_search.router)

# Trusted overlay management (Phase 10 / T510) — Owner/Admin enumeration
# under the same ``/projects`` prefix as the rest of the project surface.
router.include_router(trusted_module.router)


__all__ = ["router"]
