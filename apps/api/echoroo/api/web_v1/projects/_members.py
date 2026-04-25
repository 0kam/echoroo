"""Project membership + invitation endpoints (T118 skeleton).

Contract: ``specs/006-permissions-redesign/contracts/projects.yaml``.

Path operations owned by this module:

* ``GET    /{project_id}/members``                     — list members.
* ``POST   /{project_id}/members``                     — invite a member.
* ``PATCH  /{project_id}/members/{user_id}``           — change role.
* ``DELETE /{project_id}/members/{user_id}``           — remove a member.
* ``POST   /{project_id}/invitations/{token}/accept``  — accept invite.
* ``DELETE /{project_id}/invitations/{token}``         — decline / revoke.

T118 deliberately ships only the router scaffold. Actual handlers,
permission checks (Owner / Admin gating), audit emission, and
notification side-effects are added by T120-T127 in Phase 3.

The router declares **no prefix** here — the parent package
:mod:`echoroo.api.web_v1.projects` mounts every submodule under the
shared ``/projects`` prefix.
"""

from __future__ import annotations

from fastapi import APIRouter

# T118 skeleton — endpoints will be added by T120-T127.
router = APIRouter()


__all__ = ["router"]
