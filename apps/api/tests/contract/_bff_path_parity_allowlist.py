"""BFF path parity allowlist consumed by PR J's test_bff_path_parity.py.

Spec/009 (browser API → BFF migration) — each per-resource PR (A2 / B /
C / D / E / F / G / H) appends the `/web-api/v1/*` paths it adds to the
list below. PR J's test then asserts each entry is present in the live
OpenAPI surface.

This file is intentionally a Python module (not YAML) so it can be
imported directly by the test and edits track as code changes.
"""

from __future__ import annotations

# Live-form BFF paths declared by this migration. Each per-PR appends
# its paths here (e.g. "/web-api/v1/projects" GET, "/web-api/v1/projects"
# POST, "/web-api/v1/projects/{project_id}" PATCH, etc.).
#
# Entry format: a string in the live OpenAPI form (i.e. with the
# `/web-api/v1` prefix), suffixed by " " + the uppercase HTTP method
# (e.g. "/web-api/v1/projects POST"). PR J's test parses these on the
# space and looks each up in the live FastAPI OpenAPI dict.
BFF_PATHS_DECLARED_BY_SPEC_009: list[str] = [
    # PR B — residual auth follow-up (frontend-only rewire, 2026-05-13)
    #
    # The frontend now targets these BFF paths for register / login /
    # logout / refresh / password-reset / verify-email, all of which
    # exist on the BFF auth router (`apps/api/echoroo/api/web_v1/auth.py`).
    #
    # Deviation note (resolved 2026-05-13 PR B follow-up): spec/009
    # research.md D-3 understated the inventory — the BFF surface
    # previously lacked a `/verify-email` mirror, so the frontend rewire
    # would have 404'd in production. PR B's backend in-scope fix added
    # the `POST /web-api/v1/auth/verify-email` handler (mirrors the
    # legacy `/api/v1/auth/verify-email` handler byte-for-byte: same
    # `EmailVerifyRequest` schema, same `AuthService.verify_email`
    # service call, same `UserResponse`; PUBLIC auth posture — added
    # to `core.auth_paths.PUBLIC_AUTH_PATHS` so both the auth-router
    # and CSRF middlewares bypass the request, identical to the
    # sibling `/password-reset/confirm` handler). It is now listed
    # below and PR J's path-parity gate will assert it.
    #
    # The `/verify-email/resend` endpoint exists on neither surface —
    # it has been broken at runtime since before spec/009 (the legacy
    # v1 never implemented it either). PR B intentionally does NOT add
    # a resend mirror; tracking that fix is out of scope.
    "/web-api/v1/auth/register POST",
    "/web-api/v1/auth/password-reset/request POST",
    "/web-api/v1/auth/password-reset/confirm POST",
    "/web-api/v1/auth/verify-email POST",
    # PR A — projects read subset (frontend-only rewire, 2026-05-13)
    "/web-api/v1/projects GET",
    "/web-api/v1/projects/{project_id} GET",
    "/web-api/v1/projects/{project_id}/recordings GET",
]
