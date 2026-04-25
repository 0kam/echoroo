"""Project dataset license endpoints (T118 skeleton).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module:

* ``PUT /{project_id}/license``         — set or replace the project's
  dataset license metadata (FR-085).
* ``GET /{project_id}/license-history`` — return the immutable history
  of license changes for the project (FR-087).

License changes are append-only: the active row is mirrored to a
history table on every PUT, so FR-087 can render a full audit trail
without joining the audit log. The handlers added by T120-T127 will
also emit a ``project.license.update`` row to ``project_audit_log``
so cross-table chain integrity verification stays straightforward.

T118 deliberately ships only the router scaffold.

The router declares **no prefix** here — the parent package
:mod:`echoroo.api.web_v1.projects` mounts every submodule under the
shared ``/projects`` prefix.
"""

from __future__ import annotations

from fastapi import APIRouter

# T118 skeleton — endpoints will be added by T120-T127.
router = APIRouter()


__all__ = ["router"]
