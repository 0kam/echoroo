"""First-party session API (Cookie + CSRF) under ``/web-api/v1/*``."""

from fastapi import APIRouter

from echoroo.api.web_v1 import admin as admin_module
from echoroo.api.web_v1 import auth as auth_module
from echoroo.api.web_v1.projects import router as projects_router

web_v1_router = APIRouter(prefix="/web-api/v1")
web_v1_router.include_router(auth_module.router)
# Phase 5 (T200/T201, FR-016): Public-readable project surface. Mutations live
# in :mod:`echoroo.api.v1.projects`; this router currently exposes only the
# Guest-aware ``GET /projects`` and ``GET /projects/{id}`` paths.
web_v1_router.include_router(projects_router)
# Phase 11 / T630: superuser admin surface (looser-override approval +
# IUCN force-resync). Authentication is gated by the AuthRouter / CSRF
# middleware; per-handler ``is_superuser`` checks live in admin.py.
web_v1_router.include_router(admin_module.router)

__all__ = ["web_v1_router"]
