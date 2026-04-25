"""Project CRUD endpoints (T118 skeleton — handlers land in T126).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module:

* ``GET    /``               — list projects visible to the caller.
* ``POST   /``               — create a project (Owner becomes the caller).
* ``GET    /{project_id}``   — fetch a single project.
* ``PUT    /{project_id}``   — update mutable project metadata.
* ``DELETE /{project_id}``   — soft-delete a project (Owner only).

T118 deliberately ships only the router scaffold so other Phase 3
tasks can register dependencies (CSRF, auth, audit) once and then
add handlers in parallel. The actual implementations are added in
T126; sibling concerns (members, restricted-config, license) live in
the neighbouring modules so reviews stay small.

The router declares **no prefix** here — the parent package
:mod:`echoroo.api.web_v1.projects` mounts every submodule under the
shared ``/projects`` prefix to keep all FR-006 paths in one place.
"""

from __future__ import annotations

from fastapi import APIRouter

# T118 skeleton — endpoints will be added by T120-T127.
router = APIRouter()


__all__ = ["router"]
