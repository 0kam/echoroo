"""First-party session API (Cookie + CSRF) under ``/web-api/v1/*``."""

from fastapi import APIRouter

from echoroo.api.web_v1 import _admin_licenses as admin_licenses_module
from echoroo.api.web_v1 import _admin_recorders as admin_recorders_module
from echoroo.api.web_v1 import _admin_settings as admin_settings_module
from echoroo.api.web_v1 import _admin_users as admin_users_module
from echoroo.api.web_v1 import _recorders as recorders_module
from echoroo.api.web_v1 import admin as admin_module
from echoroo.api.web_v1 import audit as audit_module
from echoroo.api.web_v1 import auth as auth_module
from echoroo.api.web_v1 import auth_confirm_identity as auth_confirm_identity_module
from echoroo.api.web_v1 import detection_runs as detection_runs_module
from echoroo.api.web_v1 import licenses as licenses_module
from echoroo.api.web_v1 import me as me_module
from echoroo.api.web_v1 import setup as setup_module
from echoroo.api.web_v1 import taxa as taxa_module
from echoroo.api.web_v1 import users as users_module
from echoroo.api.web_v1.account import router as account_router
from echoroo.api.web_v1.projects import router as projects_router

web_v1_router = APIRouter(prefix="/web-api/v1")
web_v1_router.include_router(auth_module.router)
# Phase 17 backlog A-11 — magic-link + redeem endpoints powering the
# 4-factor identity proof for the admin 2FA reset workflow (FR-072).
web_v1_router.include_router(auth_confirm_identity_module.router)
# Phase 5 (T200/T201, FR-016): Public-readable project surface. Mutations live
# in :mod:`echoroo.api.v1.projects`; this router currently exposes only the
# Guest-aware ``GET /projects`` and ``GET /projects/{id}`` paths.
web_v1_router.include_router(projects_router)
# Spec/009 PR C — first-party taxa autocomplete mirrors for the Web UI.
web_v1_router.include_router(taxa_module.router)
# Spec/009 PR D — first-party detection model discovery for dataset status panels.
web_v1_router.include_router(detection_runs_module.router)
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
# Auth-regression fix (post-spec/006): cookie + CSRF mirror of
# ``GET /api/v1/users/me``. The browser hydrate path (auth store +
# login / 2fa-setup) needs a session-cookie-friendly endpoint so the
# legacy Bearer-JWT route stops 401-ing the BFF flow and forcing an
# auto-logout. Scope is intentionally read-only — see
# :mod:`echoroo.api.web_v1.users`.
web_v1_router.include_router(users_module.router)
# spec/011 US7 (T600-T602, FR-011-301..310) — in-app banner + activity
# read endpoints under ``/web-api/v1/me/*``. Authenticated-self only
# (resolved via ``CurrentUser``); no project context, so the routes
# carry no ``gate_action`` guard and are classified ``USER_SCOPED_ONLY``
# in :mod:`echoroo.core.endpoint_allowlist`.
web_v1_router.include_router(me_module.router)
# Spec/009 PR 4 — first-party recorders catalog. Mounted at the top
# level of ``/web-api/v1`` (not under ``/projects``) because the legacy
# router is a tenant-wide catalog endpoint (no ``project_id`` in the
# path), consumed by the dataset creation UI.
web_v1_router.include_router(recorders_module.router)
# Spec/009 PR 5 — admin superuser BFF migration (launch blocker fix).
# Mirrors the 14 ``/api/v1/admin/{users,settings,recorders,licenses}``
# endpoints onto ``/web-api/v1/admin/*`` so admin pages stop 401-ing on
# cookie-session admin users after spec/006 restricted the legacy
# programmatic mount to M2M API-key callers. Each sub-router shares
# the same ``/admin`` prefix and is wired alongside the legacy
# ``admin_module`` above (looser-override + archive + 2FA reset etc.).
web_v1_router.include_router(admin_users_module.router)
web_v1_router.include_router(admin_settings_module.router)
web_v1_router.include_router(admin_recorders_module.router)
web_v1_router.include_router(admin_licenses_module.router)
# spec/012 — public license list (FR-001/FR-002/FR-017). Cookie/CSRF
# mirror of ``GET /api/v1/licenses`` consumed by the project-creation
# form. Mounted AFTER ``admin_licenses_module`` so the
# ``/admin/licenses`` paths declared on the admin router keep priority
# over the bare ``/licenses`` prefix declared here.
web_v1_router.include_router(licenses_module.router)
# W2-2-A — first-run setup wizard BFF mirror of ``/api/v1/setup/*``.
# ``GET /setup/status`` + ``POST /setup/initialize`` run *before* any
# user/session/CSRF token exists, so both paths are listed in
# ``core.auth_paths.PUBLIC_AUTH_PATHS`` (auth + CSRF bypass) and
# classified ``SETUP_BOOTSTRAP`` in ``core.endpoint_allowlist`` (no
# ``gate_action``). The adapters delegate verbatim to the legacy
# handlers, which own the 403 already-setup guard and the no-store
# response headers.
web_v1_router.include_router(setup_module.router)

__all__ = ["web_v1_router"]
