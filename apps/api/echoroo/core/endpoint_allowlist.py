"""Structured endpoint allowlist (spec/007 AD-5, Phase 2A.1).

Replaces the legacy ``ALLOWLIST_PATHS: frozenset[str]`` used by
``tests/security/authorization/test_endpoint_coverage.py`` with a list of
structured :class:`AllowlistEntry` records. Each entry carries metadata
(category, reason, owner, spec_ref, expiry, last_reviewed_at) so the audit
lint (Phase 3.2 ``tests/contract/test_allowlist_metadata.py``) can prove
the allowlist is not silently rotting.

Design references:
- spec/007-permission-test-coverage/plan.md § AD-5 (Codex Rev.1 P0-2)
- spec/007 Rev.5.1 / Phase 2A.1

Allowlist policy:
- Pre-authentication endpoints (no project context exists yet).
- Per-user endpoints scoped to ``request.state.principal`` only.
- Infra (health/metrics) and docs (OpenAPI/Swagger).
- Token-authenticated single-shot endpoints where the token itself IS the
  credential (e.g. invitation accept/decline) — these may carry a
  ``{project_id}`` segment and therefore set ``project_scope_allowed=True``
  with an explicit ``reason``.

Admin endpoints (``/api/v1/admin/*`` and ``/web-api/v1/admin/*``) are NOT
listed here — per AD-6 they are registered as :class:`Action` records with
``is_superuser_only=True``. ``AllowlistCategory.SUPERUSER_ONLY`` is reserved
as an escape hatch and is currently unused in :data:`ALLOWLIST`.
"""
from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
from typing import NamedTuple


class AllowlistCategory(str, Enum):
    """Classification of why an endpoint may bypass the ACTIONS registry.

    Categories are stable identifiers consumed by the audit lint; do NOT
    rename without also updating the lint and the Phase 3 coherence tests.
    """

    AUTH_CALLBACK = "auth_callback"
    """OAuth callbacks, login/register/refresh/logout — no principal yet."""

    PUBLIC_STATIC = "public_static"
    """Public static assets (robots.txt, favicon.ico) served by the API."""

    INFRA_HEALTH = "infra_health"
    """Liveness/readiness/metrics endpoints consumed by orchestrators."""

    DOCS_OPENAPI = "docs_openapi"
    """FastAPI built-ins (/docs, /redoc, /openapi.json)."""

    SUPERUSER_ONLY = "superuser_only"
    """Reserved per AD-6. Currently empty — admin endpoints are Actions."""

    TOKEN_AUTH_ONLY = "token_auth_only"
    """Endpoint where a single-shot token (e.g. invitation) IS the credential."""

    EXTERNAL_PROXY = "external_proxy"
    """Global proxy endpoints with no project context (xeno-canto search)."""

    USER_SCOPED_ONLY = "user_scoped_only"
    """Per-user self-service endpoints (``/users/me/*``)."""

    SETUP_BOOTSTRAP = "setup_bootstrap"
    """First-run bootstrap endpoint, callable only when no users exist."""


class AllowlistEntry(NamedTuple):
    """Structured ALLOWLIST record (AD-5).

    All fields are required. ``review_interval_days`` defaults to 180 days
    (quarterly cadence) and ``project_scope_allowed`` defaults to ``False``
    so that any path containing ``{project_id}`` MUST be opted in explicitly.
    """

    path_pattern: str
    methods: frozenset[str]
    category: AllowlistCategory
    reason: str
    owner: str
    spec_ref: str | None
    expiry: date | None
    last_reviewed_at: date
    review_interval_days: int = 180
    project_scope_allowed: bool = False


# ---------------------------------------------------------------------------
# ALLOWLIST contents
# ---------------------------------------------------------------------------
# Path patterns mirror the *as-mounted* routes (with the ``/api/v1`` or
# ``/web-api/v1`` prefix applied by :mod:`echoroo.api.v1` and
# :mod:`echoroo.api.web_v1`). The ``*`` suffix matches zero or more path
# segments (used by :func:`is_allowlisted`).
_TODAY_REVIEWED = date(2026, 5, 12)
_DEFAULT_OWNER = "@okam"
_SPEC_006 = "spec/006-permissions-redesign"

ALLOWLIST: list[AllowlistEntry] = [
    # ---- auth_callback: programmatic surface (/api/v1/auth/*) ------------
    AllowlistEntry(
        path_pattern="/api/v1/auth/register",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Pre-authentication endpoint; no principal exists when invoked",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/auth/login",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Pre-authentication endpoint; credentials issue the session",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/auth/logout",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Idempotent session teardown; must work without live session",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/auth/refresh",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Refresh token exchange; runs before access-token re-auth",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/auth/password-reset/request",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Pre-authentication password reset request; rate-limited",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/auth/password-reset/confirm",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Token-authenticated password reset; token is the credential",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/auth/verify-email",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Token-authenticated email verification; runs pre-session",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    # ---- auth_callback: session surface (/web-api/v1/auth/*) -------------
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/register",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Pre-authentication endpoint; no principal exists when invoked",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/login",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Pre-authentication endpoint; credentials issue the session",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/logout",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Idempotent session teardown; must work without live session",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/refresh",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Refresh token exchange; runs before access-token re-auth",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/password-reset/request",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Pre-authentication password reset request; rate-limited",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/password-reset/confirm",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Token-authenticated password reset; token is the credential",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/verify-email",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="Token-authenticated email verification; runs pre-session",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#auth",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/2fa/setup/totp",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="2FA setup runs during the authentication ceremony itself",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#2fa",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/2fa/setup/totp/confirm",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="2FA setup runs during the authentication ceremony itself",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#2fa",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/2fa/challenge",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="2FA challenge step of login; runs before session is established",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#2fa",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/2fa/webauthn/register",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="WebAuthn registration runs during the auth ceremony itself",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#2fa",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/2fa/webauthn/challenge",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="WebAuthn challenge runs before session is established",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#2fa",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/confirm-identity-for-2fa-reset",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="2FA reset identity confirmation; runs out-of-band of session",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#2fa-reset",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/auth/confirm-identity-for-2fa-reset/redeem",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.AUTH_CALLBACK,
        reason="2FA reset token redemption; the token itself is the credential",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#2fa-reset",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    # ---- auth_callback: DSR account endpoints ----------------------------
    AllowlistEntry(
        path_pattern="/web-api/v1/account/dsr/export",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.USER_SCOPED_ONLY,
        reason="GDPR/CCPA DSR data export scoped to the authenticated user",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#dsr",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/account/dsr/delete",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.USER_SCOPED_ONLY,
        reason="GDPR/CCPA DSR account deletion scoped to the authenticated user",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#dsr",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    # ---- user_scoped_only: /api/v1/users/me/* ----------------------------
    AllowlistEntry(
        path_pattern="/api/v1/users/me",
        methods=frozenset({"GET", "PATCH"}),
        category=AllowlistCategory.USER_SCOPED_ONLY,
        reason="Per-user self-service profile; no project context applies",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#user-self",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/users/me/password",
        methods=frozenset({"PUT"}),
        category=AllowlistCategory.USER_SCOPED_ONLY,
        reason="Per-user password change; scoped strictly to the principal",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#user-self",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/users/me/api-tokens",
        methods=frozenset({"GET", "POST"}),
        category=AllowlistCategory.USER_SCOPED_ONLY,
        reason="Per-user API token list/create; scoped to the principal",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#user-self",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/users/me/api-tokens/{token_id}",
        methods=frozenset({"DELETE"}),
        category=AllowlistCategory.USER_SCOPED_ONLY,
        reason="Per-user API token revoke; scoped strictly to the principal",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#user-self",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    # ---- external_proxy: xeno-canto search -------------------------------
    # NOTE: xeno-canto search is mounted under
    #   /api/v1/projects/{project_id}/xeno-canto/search
    # so the path contains {project_id}; per spec/007 Codex Rev.3 重要-3 this
    # endpoint is non-project-scoped in semantics (a global Cornell Lab
    # proxy that simply happens to be namespaced under a project for
    # routing convenience). Hence project_scope_allowed=True with explicit
    # justification.
    AllowlistEntry(
        path_pattern="/api/v1/projects/{project_id}/xeno-canto/search",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.EXTERNAL_PROXY,
        reason=(
            "Global xeno-canto search proxy; the {project_id} segment is "
            "routing-only and the upstream is the Cornell Lab catalogue "
            "(no project-scoped data is exposed). Codex Rev.3 重要-3."
        ),
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#xeno-canto-search",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
        project_scope_allowed=True,
    ),
    # ---- infra_health ----------------------------------------------------
    AllowlistEntry(
        path_pattern="/health",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.INFRA_HEALTH,
        reason="Liveness probe consumed by container orchestrator (k8s/ECS)",
        owner=_DEFAULT_OWNER,
        spec_ref=None,
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/ready",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.INFRA_HEALTH,
        reason="Readiness probe consumed by container orchestrator (k8s/ECS)",
        owner=_DEFAULT_OWNER,
        spec_ref=None,
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/metrics",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.INFRA_HEALTH,
        reason="Prometheus metrics endpoint consumed by the scrape target",
        owner=_DEFAULT_OWNER,
        spec_ref=None,
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    # ---- docs_openapi ----------------------------------------------------
    AllowlistEntry(
        path_pattern="/docs",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.DOCS_OPENAPI,
        reason="FastAPI Swagger UI; built-in static documentation surface",
        owner=_DEFAULT_OWNER,
        spec_ref=None,
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/docs/oauth2-redirect",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.DOCS_OPENAPI,
        reason="FastAPI Swagger UI OAuth2 redirect callback; built-in helper",
        owner=_DEFAULT_OWNER,
        spec_ref=None,
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/redoc",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.DOCS_OPENAPI,
        reason="FastAPI Redoc UI; built-in static documentation surface",
        owner=_DEFAULT_OWNER,
        spec_ref=None,
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/openapi.json",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.DOCS_OPENAPI,
        reason="OpenAPI schema document; built-in static documentation surface",
        owner=_DEFAULT_OWNER,
        spec_ref=None,
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.DOCS_OPENAPI,
        reason="Root index; static landing page or redirect to /docs",
        owner=_DEFAULT_OWNER,
        spec_ref=None,
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    # ---- setup_bootstrap --------------------------------------------------
    AllowlistEntry(
        path_pattern="/api/v1/setup/status",
        methods=frozenset({"GET"}),
        category=AllowlistCategory.SETUP_BOOTSTRAP,
        reason="Bootstrap status probe; runs before any user account exists",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#setup",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    AllowlistEntry(
        path_pattern="/api/v1/setup/initialize",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.SETUP_BOOTSTRAP,
        reason="First-run bootstrap; only callable while no users exist",
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#setup",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
    ),
    # ---- token_auth_only: invitation accept/decline ----------------------
    # The {token} path segment IS the credential. {project_id} is the
    # routing namespace for the invitation. AD-5 mandates explicit
    # project_scope_allowed=True with justification.
    AllowlistEntry(
        path_pattern="/web-api/v1/projects/{project_id}/invitations/{token}/accept",
        methods=frozenset({"POST"}),
        category=AllowlistCategory.TOKEN_AUTH_ONLY,
        reason=(
            "Invitation accept; the single-shot {token} segment IS the "
            "credential. The {project_id} is routing context only and "
            "must match the token's project at handler-resolve time."
        ),
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#invitations",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
        project_scope_allowed=True,
    ),
    AllowlistEntry(
        path_pattern="/web-api/v1/projects/{project_id}/invitations/{token}",
        methods=frozenset({"DELETE"}),
        category=AllowlistCategory.TOKEN_AUTH_ONLY,
        reason=(
            "Invitation decline; the single-shot {token} segment IS the "
            "credential. The {project_id} is routing context only and "
            "must match the token's project at handler-resolve time."
        ),
        owner=_DEFAULT_OWNER,
        spec_ref=f"{_SPEC_006}#invitations",
        expiry=None,
        last_reviewed_at=_TODAY_REVIEWED,
        project_scope_allowed=True,
    ),
]


# ---------------------------------------------------------------------------
# Path-matching helpers
# ---------------------------------------------------------------------------


def _pattern_matches(pattern: str, path: str) -> bool:
    """Return True iff ``path`` matches the allowlist ``pattern``.

    The matcher understands two wildcards:

    * ``{name}`` — matches a single non-slash segment.
    * Trailing ``/*`` — matches one or more trailing segments.

    Otherwise the comparison is segment-wise exact (case-sensitive).
    """
    # Trailing /* — match prefix + at least one more segment.
    if pattern.endswith("/*"):
        prefix = pattern[:-2]
        if not path.startswith(prefix + "/"):
            return False
        tail = path[len(prefix) + 1 :]
        return bool(tail)  # any non-empty tail (one or more segments)
    pattern_parts = pattern.strip("/").split("/")
    path_parts = path.strip("/").split("/")
    if len(pattern_parts) != len(path_parts):
        return False
    for p_part, r_part in zip(pattern_parts, path_parts, strict=True):
        if p_part.startswith("{") and p_part.endswith("}"):
            # Placeholder matches any single non-empty segment.
            if not r_part:
                return False
            continue
        if p_part != r_part:
            return False
    return True


def is_allowlisted(path: str, method: str) -> bool:
    """Return True iff ``(path, method)`` is covered by an :data:`ALLOWLIST` entry.

    ``method`` matching: an entry covers the request if its ``methods`` set
    contains either ``method`` (uppercased) or the wildcard ``"*"``.
    """
    method_upper = method.upper()
    for entry in ALLOWLIST:
        if method_upper not in entry.methods and "*" not in entry.methods:
            continue
        if _pattern_matches(entry.path_pattern, path):
            return True
    return False


# ---------------------------------------------------------------------------
# Module-level structural assertions (cheap smoke check, AD-5 Rev.5.1)
# ---------------------------------------------------------------------------
# These run at import time so a malformed ALLOWLIST cannot ship even if the
# audit lint (``tests/contract/test_allowlist_metadata.py``) is skipped.
# Full lint (AST scan for superuser_only/token_auth_only) lives in Phase 3.2.


def _validate_allowlist(today: date | None = None) -> None:
    """Assert structural invariants on :data:`ALLOWLIST`.

    Invariants enforced:
    - ``reason`` is non-empty and at least 20 characters.
    - ``owner`` is non-empty.
    - ``last_reviewed_at + review_interval_days >= today`` (entry not stale).
    - Entries with ``{project_id}`` in ``path_pattern`` set
      ``project_scope_allowed=True``.
    - ``methods`` is non-empty.
    """
    cmp_today = today or date.today()
    for entry in ALLOWLIST:
        loc = f"{entry.path_pattern} ({entry.category.value})"
        if not entry.reason or len(entry.reason) < 20:
            raise AssertionError(
                f"ALLOWLIST entry {loc}: reason must be >= 20 chars "
                f"(got {len(entry.reason)})"
            )
        if not entry.owner:
            raise AssertionError(f"ALLOWLIST entry {loc}: owner is required")
        if not entry.methods:
            raise AssertionError(f"ALLOWLIST entry {loc}: methods is empty")
        review_deadline = entry.last_reviewed_at + timedelta(
            days=entry.review_interval_days
        )
        if review_deadline < cmp_today:
            raise AssertionError(
                f"ALLOWLIST entry {loc}: past review-by date "
                f"({entry.last_reviewed_at} + {entry.review_interval_days}d "
                f"= {review_deadline} < today {cmp_today})"
            )
        if "{project_id}" in entry.path_pattern and not entry.project_scope_allowed:
            raise AssertionError(
                f"ALLOWLIST entry {loc}: path_pattern contains {{project_id}} "
                f"but project_scope_allowed=False (AD-5 forbids silent "
                f"project-scoped allowlisting)"
            )


_validate_allowlist()


__all__ = [
    "ALLOWLIST",
    "AllowlistCategory",
    "AllowlistEntry",
    "is_allowlisted",
]
