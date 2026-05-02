"""First-party session API (Cookie + CSRF) under ``/web-api/v1/*``."""

from fastapi import APIRouter

from echoroo.api.web_v1 import admin as admin_module
from echoroo.api.web_v1 import audit as audit_module
from echoroo.api.web_v1 import auth as auth_module
from echoroo.api.web_v1.account import router as account_router
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
# Phase 14 / T900: self-service GDPR DSR (export + soft-delete) under
# ``/web-api/v1/account/dsr/*``. FR-105 / FR-109.
web_v1_router.include_router(account_router)
# Phase 17 follow-up — audit log read endpoints (FR-088 / FR-089 /
# FR-096). The router was defined in Phase 2.11 P0-c but its module
# docstring still flagged "the router is defined here but NOT
# registered with the FastAPI app". Without this line
# contracts/audit.yaml's three paths (/projects/{id}/audit-log,
# /admin/audit-log, /admin/audit-log/chain-verify) drift from the
# live OpenAPI surface (Codex Round X follow-up #4).
web_v1_router.include_router(audit_module.router)

__all__ = ["web_v1_router"]
