"""Web-API ``/account/*`` surface (Phase 14, FR-105 / FR-109).

Self-service GDPR endpoints for the authenticated user. The router is
mounted under ``/web-api/v1/account`` by
:mod:`echoroo.api.web_v1.__init__`. Concrete handlers live in
:mod:`echoroo.api.web_v1.account.dsr` (Data Subject Request export +
account soft-delete).
"""

from __future__ import annotations

from fastapi import APIRouter

from echoroo.api.web_v1.account import dsr as dsr_module
from echoroo.api.web_v1.account import trusted_devices as trusted_devices_module

router = APIRouter(prefix="/account", tags=["account"])

# Phase 14 / T900 — DSR export + soft-delete (FR-105 / FR-109).
router.include_router(dsr_module.router)
router.include_router(trusted_devices_module.router)


__all__ = ["router"]
