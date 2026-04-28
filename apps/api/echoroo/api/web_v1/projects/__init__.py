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

from . import _core, _license, _members, _restricted_config

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

# Trusted overlay management (Phase 10 / T510) — Owner/Admin enumeration
# under the same ``/projects`` prefix as the rest of the project surface.
router.include_router(trusted_module.router)


__all__ = ["router"]
