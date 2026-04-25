"""Smoke tests for :mod:`echoroo.middleware.csrf` (T072)."""

from __future__ import annotations

import pytest

from echoroo.middleware.csrf import (
    CsrfTokenExpiredError,
    CsrfTokenMalformedError,
    CsrfTokenMismatchError,
    issue_csrf_token,
    verify_csrf_token,
)


def test_csrf_token_round_trip() -> None:
    """A token issued for a session must verify against that session."""
    token = issue_csrf_token(
        "session-abc",
        session_secret="deployment-secret-32-bytes-of-entropy",
        issued_at=10_000,
    )
    # Should not raise.
    verify_csrf_token(
        token,
        session_id="session-abc",
        session_secret="deployment-secret-32-bytes-of-entropy",
        now=10_500,
    )


def test_csrf_rejects_tampered() -> None:
    """A flipped byte in the HMAC half MUST be rejected."""
    token = issue_csrf_token(
        "session-abc",
        session_secret="deployment-secret-32-bytes-of-entropy",
        issued_at=10_000,
    )
    payload, mac = token.split(".", 1)
    # Flip the first character of the mac portion.
    flipped = ("A" if mac[0] != "A" else "B") + mac[1:]
    tampered = f"{payload}.{flipped}"
    with pytest.raises(CsrfTokenMismatchError):
        verify_csrf_token(
            tampered,
            session_id="session-abc",
            session_secret="deployment-secret-32-bytes-of-entropy",
            now=10_500,
        )


def test_csrf_rejects_wrong_session() -> None:
    """Token issued for session A must not verify against session B."""
    token = issue_csrf_token(
        "session-A",
        session_secret="deployment-secret-32-bytes-of-entropy",
        issued_at=10_000,
    )
    with pytest.raises(CsrfTokenMismatchError):
        verify_csrf_token(
            token,
            session_id="session-B",
            session_secret="deployment-secret-32-bytes-of-entropy",
            now=10_500,
        )


def test_csrf_rejects_expired() -> None:
    """Tokens older than the TTL must be rejected even if HMAC matches."""
    token = issue_csrf_token(
        "session-abc",
        session_secret="deployment-secret-32-bytes-of-entropy",
        issued_at=1_000,
    )
    with pytest.raises(CsrfTokenExpiredError):
        verify_csrf_token(
            token,
            session_id="session-abc",
            session_secret="deployment-secret-32-bytes-of-entropy",
            ttl_seconds=60,
            now=2_000,
        )


def test_csrf_rejects_malformed() -> None:
    """Garbage inputs must be flagged malformed, not raise unrelated errors."""
    with pytest.raises(CsrfTokenMalformedError):
        verify_csrf_token(
            "not-a-token",
            session_id="session",
            session_secret="x" * 32,
        )


# ---------------------------------------------------------------------------
# Phase 2.10 #6 — middleware-level path exemption
# ---------------------------------------------------------------------------


def _build_app() -> object:
    """Build a tiny Starlette app wrapped in :class:`CsrfMiddleware`."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    from echoroo.middleware.csrf import CsrfConfig, CsrfMiddleware

    async def _ok(_request):  # type: ignore[no-untyped-def]
        return PlainTextResponse("ok")

    routes = [
        Route("/web-api/v1/auth/login", _ok, methods=["POST"]),
        Route("/web-api/v1/auth/refresh", _ok, methods=["POST"]),
        Route("/web-api/v1/auth/forgot-password", _ok, methods=["POST"]),
        Route("/web-api/v1/projects", _ok, methods=["POST"]),
        Route("/web-api/v1/projects/123/members", _ok, methods=["POST"]),
    ]
    app = Starlette(routes=routes)
    config = CsrfConfig(session_secret="test-secret-32-bytes-of-entropy-padding")
    app.add_middleware(CsrfMiddleware, config=config)
    return app


def test_exempt_login_path_passes_without_csrf_token() -> None:
    """``/web-api/v1/auth/login`` POST must not require a CSRF token."""
    from starlette.testclient import TestClient

    app = _build_app()
    with TestClient(app) as client:
        # No session cookie, no CSRF header — must still succeed.
        resp = client.post("/web-api/v1/auth/login")
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_exempt_refresh_path_passes_without_csrf_token() -> None:
    """The refresh endpoint is exempt by design (token IS the proof)."""
    from starlette.testclient import TestClient

    app = _build_app()
    with TestClient(app) as client:
        resp = client.post("/web-api/v1/auth/refresh")
    assert resp.status_code == 200


def test_exempt_forgot_password_passes_without_csrf_token() -> None:
    """Phase 2.10 #6 added forgot-password to the exemption list."""
    from starlette.testclient import TestClient

    app = _build_app()
    with TestClient(app) as client:
        resp = client.post("/web-api/v1/auth/forgot-password")
    assert resp.status_code == 200


def test_non_exempt_path_is_blocked_without_csrf_credentials() -> None:
    """A POST to a non-allowlisted ``/web-api/v1/*`` path must be 403."""
    from starlette.testclient import TestClient

    app = _build_app()
    with TestClient(app) as client:
        resp = client.post("/web-api/v1/projects")
    assert resp.status_code == 403
    body = resp.json()
    assert body["error_code"] == "csrf_failed"


def test_non_exempt_path_is_blocked_with_invalid_csrf_token() -> None:
    """Even with a session cookie, an invalid CSRF token yields 403."""
    from starlette.testclient import TestClient

    app = _build_app()
    with TestClient(app) as client:
        client.cookies.set("session_id", "session-xyz")
        resp = client.post(
            "/web-api/v1/projects",
            headers={"X-CSRF-Token": "garbage"},
        )
    assert resp.status_code == 403


def test_post_login_session_path_enforces_csrf() -> None:
    """A valid session + valid CSRF token combo passes through."""
    from starlette.testclient import TestClient

    app = _build_app()
    secret = "test-secret-32-bytes-of-entropy-padding"
    token = issue_csrf_token("session-abc", session_secret=secret)

    with TestClient(app) as client:
        client.cookies.set("session_id", "session-abc")
        resp = client.post(
            "/web-api/v1/projects/123/members",
            headers={"X-CSRF-Token": token},
        )
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_csrf_exempt_paths_match_auth_router_allowlist() -> None:
    """Phase 2.10 #6: CSRF and auth-router allowlists must be in sync."""
    from echoroo.middleware.auth_router import AuthRouterConfig
    from echoroo.middleware.csrf import EXEMPT_PATHS

    auth_allowlist = tuple(AuthRouterConfig().public_path_allowlist)
    assert EXEMPT_PATHS == auth_allowlist, (
        "CSRF EXEMPT_PATHS and AuthRouter public_path_allowlist must be "
        "exact-match (sourced from core.auth_paths.PUBLIC_AUTH_PATHS). "
        f"csrf={EXEMPT_PATHS!r} auth={auth_allowlist!r}"
    )


def test_csrf_exempt_paths_includes_2fa_verify() -> None:
    """Sanity: 2FA verify path is in the exemption list."""
    from echoroo.middleware.csrf import EXEMPT_PATHS

    assert "/web-api/v1/auth/2fa/verify" in EXEMPT_PATHS
    assert "/web-api/v1/auth/2fa/challenge" in EXEMPT_PATHS
