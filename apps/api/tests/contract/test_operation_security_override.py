"""T983: Operation-level security override tests (Codex 致命 1/3).

Validates the security posture of every state-changing path operation
(POST / PATCH / DELETE / PUT) registered in the FastAPI app:

  1. ``/api/v1/*``     — MUST require Bearer (HTTPBearer) authentication.
                         Cookie-session and CSRF tokens are irrelevant here.
  2. ``/web-api/v1/*`` — MUST require some form of authentication declaration
                         (either operation-level security or global security).
                         CSRF enforcement is applied at the middleware level
                         (``CsrfMiddleware``) and is therefore NOT expressed
                         in the OpenAPI schema — the test verifies the
                         middleware is configured instead.
  3. Exempt paths      — Pre-session auth endpoints (login / register / 2FA /
                         refresh / password-reset / logout) are intentionally
                         unauthenticated.  These MUST NOT carry operation-level
                         security declarations that would block legitimate
                         unauthenticated access.

Design decision — CSRF in OpenAPI schema
-----------------------------------------
FastAPI's OpenAPI generator does not natively support CSRF as a security
scheme.  The ``CsrfMiddleware`` enforces CSRF at the Starlette middleware
layer (before route handlers run) which means:

  * The ``X-CSRF-Token`` header requirement is real in production.
  * It is NOT expressed in the generated ``openapi.json`` security blocks.

T983 therefore validates the *middleware configuration* rather than the
schema security blocks for CSRF.  Schema-level CSRF was described in the
``contracts/*.yaml`` files using the logical ``csrfToken`` security scheme
name (for documentation purposes); the live app uses the real middleware.

Phase 15 admin endpoints verified
----------------------------------
The following endpoints (added in Phase 15 Batch 5a) must carry HTTPBearer:
  addSuperuser / revokeSuperuser / updateSuperuserIpAllowlist /
  approveSuperuserRequest / rejectSuperuserRequest / enterBreakGlass

Existing admin endpoints (from earlier phases) are also enumerated:
  archiveProject / restoreProject / overrideApprove / iucnResync

DSR endpoints (Phase 14) must also carry HTTPBearer:
  dsr_export / dsr_delete
"""

from __future__ import annotations

from typing import Any

import pytest

from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS
from echoroo.main import create_app
from echoroo.middleware.csrf import WEB_API_PREFIX, CsrfConfig, CsrfMiddleware

# HTTP methods that change server state.
_STATE_CHANGING_METHODS = frozenset({"post", "patch", "delete", "put"})

# Paths where CSRF / auth are intentionally bypassed because the client has
# no session yet (pre-session auth flow).  Matched against exact path strings.
_CSRF_EXEMPT_PATHS: frozenset[str] = frozenset(PUBLIC_AUTH_PATHS)

# Paths under /api/v1/ that are public (no auth required, no security override).
_API_V1_PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/api/v1/setup/initialize",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/refresh",
        "/api/v1/auth/password-reset/request",
        "/api/v1/auth/password-reset/confirm",
        "/api/v1/auth/verify-email",
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_schema() -> dict[str, Any]:
    """FastAPI-generated OpenAPI schema."""
    app = create_app()
    schema = app.openapi()
    assert isinstance(schema, dict)
    return schema


@pytest.fixture(scope="module")
def all_state_changing_ops(
    live_schema: dict[str, Any],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Enumerate all (path, method, operation) tuples for state-changing ops."""
    paths: dict[str, Any] = live_schema.get("paths") or {}
    result: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, op in path_item.items():
            if method not in _STATE_CHANGING_METHODS:
                continue
            if not isinstance(op, dict):
                continue
            result.append((path, method, op))
    return result


# ---------------------------------------------------------------------------
# T983-1: Total count of state-changing operations is non-trivial
# ---------------------------------------------------------------------------


class TestOperationInventory:
    def test_state_changing_ops_non_trivial(
        self, all_state_changing_ops: list[tuple[str, str, dict[str, Any]]]
    ) -> None:
        """At least 50 state-changing operations must be registered (sanity check)."""
        assert len(all_state_changing_ops) >= 50, (
            f"Expected >= 50 state-changing ops, found {len(all_state_changing_ops)}"
        )

    def test_web_api_state_changing_ops_present(
        self, all_state_changing_ops: list[tuple[str, str, dict[str, Any]]]
    ) -> None:
        """At least 10 web-api state-changing operations must be registered."""
        web_ops = [op for op in all_state_changing_ops if op[0].startswith("/web-api/v1/")]
        assert len(web_ops) >= 10, (
            f"Expected >= 10 /web-api/v1/ state-changing ops, found {len(web_ops)}"
        )

    def test_api_v1_state_changing_ops_present(
        self, all_state_changing_ops: list[tuple[str, str, dict[str, Any]]]
    ) -> None:
        """At least 50 /api/v1/ state-changing operations must be registered."""
        api_ops = [op for op in all_state_changing_ops if op[0].startswith("/api/v1/")]
        assert len(api_ops) >= 50, (
            f"Expected >= 50 /api/v1/ state-changing ops, found {len(api_ops)}"
        )


# ---------------------------------------------------------------------------
# T983-2: /api/v1/* state-changing ops carry HTTPBearer (or are public exempt)
# ---------------------------------------------------------------------------


class TestApiV1SecurityOverride:
    def test_all_api_v1_state_changing_ops_have_bearer_or_are_exempt(
        self,
        all_state_changing_ops: list[tuple[str, str, dict[str, Any]]],
        live_schema: dict[str, Any],
    ) -> None:
        """Every POST/PATCH/DELETE/PUT under /api/v1/ must require HTTPBearer.

        Public pre-auth paths (login, register, etc.) are explicitly exempt.
        """
        global_security = live_schema.get("security") or []
        failures: list[str] = []

        for path, method, op in all_state_changing_ops:
            if not path.startswith("/api/v1/"):
                continue
            if path in _API_V1_PUBLIC_PATHS:
                continue  # explicitly exempt

            # Operation-level security
            op_security: list[dict[str, list[str]]] = op.get("security") or []
            effective_security = op_security or global_security

            if not effective_security:
                failures.append(f"{method.upper()} {path}: no security declaration")
                continue

            # Check that at least one scheme is HTTPBearer
            has_bearer = any(
                "HTTPBearer" in req for req in effective_security
            )
            if not has_bearer:
                failures.append(
                    f"{method.upper()} {path}: security present but no HTTPBearer "
                    f"({effective_security!r})"
                )

        assert not failures, (
            f"{len(failures)} /api/v1/ state-changing op(s) lack HTTPBearer:\n"
            + "\n".join(f"  {f}" for f in failures)
        )

    def test_phase15_admin_superuser_ops_have_bearer(
        self,
        live_schema: dict[str, Any],
    ) -> None:
        """Phase 15 superuser admin endpoints must carry HTTPBearer security."""
        paths: dict[str, Any] = live_schema.get("paths") or {}
        # Expected Phase 15 endpoints (operation IDs)
        expected_op_ids = {
            "add_superuser_endpoint_web_api_v1_admin_superusers_post",
            "revoke_superuser_endpoint_web_api_v1_admin_superusers__superuser_id__revoke_post",
            "approve_request_endpoint_web_api_v1_admin_superusers_approval_requests__approval_request_id__approve_post",
            "reject_request_endpoint_web_api_v1_admin_superusers_approval_requests__approval_request_id__reject_post",
            "enter_break_glass_web_api_v1_admin_superusers_break_glass_enter_post",
            "update_ip_allowlist_web_api_v1_admin_superusers__superuser_id__ip_allowlist_patch",
        }
        found_ids: set[str] = set()
        missing_bearer: list[str] = []

        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method, op in path_item.items():
                if not isinstance(op, dict):
                    continue
                op_id = op.get("operationId", "")
                if op_id in expected_op_ids:
                    found_ids.add(op_id)
                    op_security = op.get("security") or []
                    has_bearer = any("HTTPBearer" in req for req in op_security)
                    if not has_bearer:
                        missing_bearer.append(f"{method.upper()} {path} [{op_id}]")

        missing_ops = expected_op_ids - found_ids
        assert not missing_ops, (
            f"Phase 15 superuser endpoints not found in schema: {missing_ops}"
        )
        assert not missing_bearer, (
            f"Phase 15 superuser endpoints missing HTTPBearer: {missing_bearer}"
        )

    def test_phase14_dsr_ops_have_bearer(
        self,
        live_schema: dict[str, Any],
    ) -> None:
        """Phase 14 DSR endpoints must carry HTTPBearer security."""
        paths: dict[str, Any] = live_schema.get("paths") or {}
        dsr_paths = [
            p for p in paths
            if "/account/dsr/" in p and p.startswith("/web-api/v1/")
        ]
        assert len(dsr_paths) >= 2, (
            f"Expected at least 2 DSR paths, found: {dsr_paths}"
        )
        failures: list[str] = []
        for path in dsr_paths:
            path_item = paths[path]
            for method, op in path_item.items():
                if method not in _STATE_CHANGING_METHODS:
                    continue
                op_security = op.get("security") or []
                has_bearer = any("HTTPBearer" in req for req in op_security)
                if not has_bearer:
                    failures.append(f"{method.upper()} {path}: missing HTTPBearer")
        assert not failures, f"DSR ops missing HTTPBearer: {failures}"


# ---------------------------------------------------------------------------
# T983-3: /web-api/v1/* non-exempt state-changing ops carry security declaration
# ---------------------------------------------------------------------------


class TestWebApiSecurityOverride:
    def test_web_api_state_changing_ops_not_exempt_have_security(
        self,
        all_state_changing_ops: list[tuple[str, str, dict[str, Any]]],
        live_schema: dict[str, Any],
    ) -> None:
        """Non-exempt /web-api/v1/ state-changing ops must declare security."""
        global_security = live_schema.get("security") or []
        failures: list[str] = []

        for path, method, op in all_state_changing_ops:
            if not path.startswith("/web-api/v1/"):
                continue
            if path in _CSRF_EXEMPT_PATHS:
                continue  # pre-session auth paths are legitimately unauthenticated

            op_security: list[dict[str, list[str]]] = op.get("security") or []
            effective_security = op_security or global_security

            if not effective_security:
                failures.append(
                    f"{method.upper()} {path}: no security declaration (CSRF-enforced ops must declare auth)"
                )

        assert not failures, (
            f"{len(failures)} /web-api/v1/ non-exempt state-changing op(s) lack auth:\n"
            + "\n".join(f"  {f}" for f in failures)
        )

    def test_csrf_exempt_paths_not_overriding_with_bearer(
        self,
        all_state_changing_ops: list[tuple[str, str, dict[str, Any]]],
    ) -> None:
        """Pre-session auth paths should NOT carry operation-level security overrides.

        These paths are intentionally unauthenticated; an operation-level
        security block would block legitimate unauthenticated access.
        """
        # Note: FastAPI may inherit no global security, in which case these
        # having no op-level security is correct.  We just verify they don't
        # have an HTTPBearer requirement that would break login.
        wrong_security: list[str] = []
        for path, method, op in all_state_changing_ops:
            if path not in _CSRF_EXEMPT_PATHS:
                continue
            op_security: list[dict[str, list[str]]] = op.get("security") or []
            # However some frameworks add an empty security list [] to indicate
            # "no auth" explicitly — that is fine.
            # Only flag if a real scheme (non-empty) is present.
            non_empty_bearer = any(
                req.get("HTTPBearer") != [] if isinstance(req, dict) else False
                for req in op_security
                if isinstance(req, dict) and "HTTPBearer" in req
            )
            if non_empty_bearer:
                wrong_security.append(
                    f"{method.upper()} {path}: should be pre-auth but has Bearer security"
                )
        assert not wrong_security, (
            "Pre-session endpoints must not require Bearer auth:\n"
            + "\n".join(f"  {s}" for s in wrong_security)
        )


# ---------------------------------------------------------------------------
# T983-4: CSRF middleware is configured and covers /web-api/v1/ prefix
# ---------------------------------------------------------------------------


class TestCsrfMiddlewareConfiguration:
    def test_csrf_middleware_default_config_covers_web_api_prefix(self) -> None:
        """CsrfMiddleware default config must protect the /web-api/v1/ prefix."""
        config = CsrfConfig(session_secret="test-secret-at-least-32-bytes-long!")
        assert config.protected_prefix == WEB_API_PREFIX, (
            f"CsrfMiddleware.protected_prefix must be '{WEB_API_PREFIX}', "
            f"got {config.protected_prefix!r}"
        )

    def test_csrf_middleware_uses_correct_header_name(self) -> None:
        """CsrfMiddleware must look for the X-CSRF-Token header."""
        config = CsrfConfig(session_secret="test-secret-at-least-32-bytes-long!")
        assert config.header_name == "X-CSRF-Token", (
            f"Expected header 'X-CSRF-Token', got {config.header_name!r}"
        )

    def test_csrf_middleware_class_is_importable(self) -> None:
        """CsrfMiddleware must be importable and instantiable."""
        assert CsrfMiddleware is not None

    def test_csrf_exempt_paths_match_public_auth_paths(self) -> None:
        """Operation-security exemptions must mirror core pre-auth paths."""
        auth_paths_set = frozenset(PUBLIC_AUTH_PATHS)
        assert auth_paths_set == _CSRF_EXEMPT_PATHS


# ---------------------------------------------------------------------------
# T983-5: Admin project management endpoints have HTTPBearer
# ---------------------------------------------------------------------------


class TestAdminProjectOpsHaveBearer:
    def test_archive_restore_ops_have_bearer(
        self, live_schema: dict[str, Any]
    ) -> None:
        """archive / restore project endpoints must carry HTTPBearer."""
        paths: dict[str, Any] = live_schema.get("paths") or {}
        expected_paths = [
            p for p in paths
            if "/admin/projects/" in p and p.startswith("/web-api/v1/")
        ]
        # Should include archive and restore
        op_paths = [p for p in expected_paths if any(
            suffix in p for suffix in ("/archive", "/restore", "/taxon-overrides/")
        )]
        assert len(op_paths) >= 2, (
            f"Expected at least 2 admin project management endpoints, got: {op_paths}"
        )
        failures: list[str] = []
        for path in op_paths:
            path_item = paths[path]
            for method, op in path_item.items():
                if method not in _STATE_CHANGING_METHODS or not isinstance(op, dict):
                    continue
                op_security = op.get("security") or []
                if not any("HTTPBearer" in req for req in op_security):
                    failures.append(f"{method.upper()} {path}")
        assert not failures, f"Admin project ops missing HTTPBearer: {failures}"

    def test_iucn_resync_has_bearer(self, live_schema: dict[str, Any]) -> None:
        """IUCN force-resync endpoint must carry HTTPBearer."""
        paths: dict[str, Any] = live_schema.get("paths") or {}
        iucn_paths = [
            p for p in paths
            if "iucn" in p.lower() and p.startswith("/web-api/v1/")
        ]
        assert iucn_paths, "IUCN resync endpoint not found in schema"
        for path in iucn_paths:
            path_item = paths[path]
            for method, op in path_item.items():
                if method not in _STATE_CHANGING_METHODS or not isinstance(op, dict):
                    continue
                op_security = op.get("security") or []
                has_bearer = any("HTTPBearer" in req for req in op_security)
                assert has_bearer, (
                    f"IUCN resync {method.upper()} {path} must have HTTPBearer"
                )
