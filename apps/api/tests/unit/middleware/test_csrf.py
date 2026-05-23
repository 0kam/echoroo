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
# Regression: cookie / middleware / settings TTL must stay in lock-step.
#
# Previously the csrf cookie pinned to ``web_access_token_ttl_seconds`` (15min)
# and the middleware fell back to a hard-coded 24h default while the session
# / refresh cookies lived for 30 days. Result: 15 min after login the cookie
# disappeared client-side and any unsafe request started failing with 403
# csrf_failed even though the session was still valid — visible to users as
# random auto-logout. The setting below pins all three to the same source.
# ---------------------------------------------------------------------------


def test_csrf_ttl_setting_matches_refresh_window() -> None:
    """Default CSRF TTL must equal the refresh-token window.

    If these drift, the cookie or middleware token expires before the
    session does and the user gets surprise 403 csrf_failed responses.
    """
    from echoroo.core.settings import get_settings

    settings = get_settings()
    assert settings.web_csrf_ttl_seconds == settings.web_refresh_token_ttl_seconds


def test_session_cookies_use_csrf_ttl_setting() -> None:
    """``_set_session_cookies`` must stamp the csrf cookie's Max-Age with
    ``web_csrf_ttl_seconds`` (not the access-token TTL) AND must keep the
    other security attributes (``SameSite=Strict``, the dev/prod-conditional
    ``Secure``, and ``HttpOnly`` absent so JS can read the double-submit
    value). Locking these down in one place catches the case where a future
    edit fixes the TTL but accidentally widens or narrows another attribute.
    """
    from starlette.responses import Response

    from echoroo.api.web_v1.auth import _set_session_cookies
    from echoroo.core.settings import get_settings

    settings = get_settings()
    response = Response()
    _set_session_cookies(
        response,
        refresh_token="dummy.refresh.token",
        family_id="family-abc",
    )

    csrf_header = next(
        (
            raw
            for key, raw in response.raw_headers
            if key == b"set-cookie"
            and raw.split(b"=", 1)[0] == settings.web_csrf_cookie_name.encode()
        ),
        None,
    )
    assert csrf_header is not None, "csrf cookie must be set"
    cookie_str = csrf_header.decode("ascii").lower()
    assert f"max-age={settings.web_csrf_ttl_seconds}" in cookie_str, cookie_str
    assert "samesite=strict" in cookie_str, cookie_str
    # CSRF cookie is the public half of a double-submit pattern — JS must
    # be able to read it, so HttpOnly must NOT be set on this cookie.
    assert "httponly" not in cookie_str, cookie_str
    # Dev runs over plain HTTP; staging/production cookies must be Secure.
    if settings.ENVIRONMENT == "development":
        assert "secure" not in cookie_str, cookie_str
    else:
        assert "secure" in cookie_str, cookie_str


def test_csrf_ttl_inherits_refresh_when_env_unset(monkeypatch) -> None:
    """Operators who only override the refresh TTL must see the CSRF
    window follow automatically — otherwise the drift this hotfix removes
    silently returns. The settings validator is the enforcement point;
    this test pins that behaviour.

    Settings uses ``case_sensitive=True`` so the env var names must match
    the lowercase field names exactly (see ``SettingsConfigDict`` in
    ``core/settings.py``).
    """
    from echoroo.core.settings import Settings

    monkeypatch.delenv("web_csrf_ttl_seconds", raising=False)
    monkeypatch.setenv("web_refresh_token_ttl_seconds", str(7 * 24 * 3600))

    s = Settings()
    assert s.web_refresh_token_ttl_seconds == 7 * 24 * 3600
    assert s.web_csrf_ttl_seconds == 7 * 24 * 3600


def test_csrf_ttl_respects_explicit_env_override(monkeypatch) -> None:
    """An explicit ``web_csrf_ttl_seconds`` env value must win over the
    inherit default so operators retain a knob for shorter rotation
    policies."""
    from echoroo.core.settings import Settings

    monkeypatch.setenv("web_csrf_ttl_seconds", "3600")
    monkeypatch.setenv("web_refresh_token_ttl_seconds", str(30 * 24 * 3600))

    s = Settings()
    assert s.web_csrf_ttl_seconds == 3600


def test_app_wires_csrf_middleware_with_csrf_ttl_setting() -> None:
    """The app-level :class:`CsrfMiddleware` must read its TTL from the
    ``web_csrf_ttl_seconds`` setting so cookie and verifier agree."""
    from echoroo.core.settings import get_settings
    from echoroo.main import create_app
    from echoroo.middleware.csrf import CsrfMiddleware

    settings = get_settings()
    app = create_app()
    csrf_layer = next(
        (m for m in app.user_middleware if m.cls is CsrfMiddleware),
        None,
    )
    assert csrf_layer is not None, "CsrfMiddleware must be registered"
    config = csrf_layer.kwargs["config"]
    assert config.ttl_seconds == settings.web_csrf_ttl_seconds


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


# spec/011 §FR-011-005 / Step 10 — the legacy ``/web-api/v1/auth/forgot-password``
# CSRF-exemption case was removed alongside the deleted self-service
# password-reset route.


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
    assert auth_allowlist == EXEMPT_PATHS, (
        "CSRF EXEMPT_PATHS and AuthRouter public_path_allowlist must be "
        "exact-match (sourced from core.auth_paths.PUBLIC_AUTH_PATHS). "
        f"csrf={EXEMPT_PATHS!r} auth={auth_allowlist!r}"
    )


def test_csrf_exempt_paths_includes_2fa_verify() -> None:
    """Sanity: 2FA verify path is in the exemption list."""
    from echoroo.middleware.csrf import EXEMPT_PATHS

    assert "/web-api/v1/auth/2fa/verify" in EXEMPT_PATHS
    assert "/web-api/v1/auth/2fa/challenge" in EXEMPT_PATHS
