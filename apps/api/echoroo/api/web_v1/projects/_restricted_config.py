"""Restricted-config toggle endpoint (T118 skeleton).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module:

* ``PATCH /{project_id}/restricted-config`` — flip the per-project
  restricted-mode flags (FR-014, FR-020, FR-021, FR-022).

The endpoint controls how a Restricted-visibility project gates
detection / tag / vote access for non-members. Only the project Owner
or a Superuser on the platform allowlist may flip these flags, and
every change is recorded in ``project_audit_log`` with both the
before-state and after-state JSON for FR-088 traceability.

T118 deliberately ships only the router scaffold; the handler is
added by T120-T127 in Phase 3.

The router declares **no prefix** here — the parent package
:mod:`echoroo.api.web_v1.projects` mounts every submodule under the
shared ``/projects`` prefix.
"""

from __future__ import annotations

from fastapi import APIRouter

# T118 skeleton — endpoints will be added by T120-T127.
router = APIRouter()


__all__ = ["router"]
