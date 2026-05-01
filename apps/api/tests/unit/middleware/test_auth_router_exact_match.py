"""Phase 2.11 P0-b: auth router public allowlist must use EXACT path match.

The previous behaviour was ``any(path.startswith(p) for p in allowlist)``
which created a silent auth-bypass risk: introducing a new endpoint such
as ``/web-api/v1/auth/login-history`` (or ``/auth/login.json``) would
match the ``/web-api/v1/auth/login`` prefix and skip authentication
altogether. The fix is exact-equality matching, mirroring
:func:`echoroo.core.auth_paths.is_public_auth_path` (already used by
the CSRF middleware). This test pins the contract.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from echoroo.middleware.auth_router import (
    AuthRouterConfig,
    AuthRouterMiddleware,
)


class _DenyAllSessionVerifier:
    """Session verifier that fails every request — proves anonymous bypass."""

    async def verify(self, session_id: str) -> None:
        return None


def _build_app(allowlist: tuple[str, ...]) -> TestClient:
    """Build a Starlette app where every route returns whether auth was skipped."""

    async def echo(request: Request) -> JSONResponse:
        principal = getattr(request.state, "principal", None)
        return JSONResponse({"anonymous": principal is None})

    app = Starlette(
        routes=[
            # Real allowlisted endpoint.
            Route("/web-api/v1/auth/login", echo, methods=["GET", "POST"]),
            # Spoofed sibling that previously inherited the bypass.
            Route(
                "/web-api/v1/auth/login-history", echo, methods=["GET", "POST"]
            ),
            # Yet another sibling with a different suffix.
            Route(
                "/web-api/v1/auth/login.json", echo, methods=["GET", "POST"]
            ),
            # Trailing-slash variant.
            Route("/web-api/v1/auth/login/", echo, methods=["GET", "POST"]),
            # A truly arbitrary protected endpoint.
            Route("/web-api/v1/projects", echo, methods=["GET"]),
        ]
    )
    config = AuthRouterConfig(
        session_verifier=_DenyAllSessionVerifier(),
        public_path_allowlist=allowlist,
    )
    app.add_middleware(AuthRouterMiddleware, config=config)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Positive: exact match still allows anonymous access
# ---------------------------------------------------------------------------


def test_exact_allowlisted_path_skips_auth() -> None:
    """The exact path on the allowlist passes through without credentials."""
    client = _build_app(("/web-api/v1/auth/login",))
    resp = client.post("/web-api/v1/auth/login", json={"email": "x"})
    assert resp.status_code == 200
    assert resp.json() == {"anonymous": True}


# ---------------------------------------------------------------------------
# P0-b: prefix-only matches MUST NOT bypass auth
# ---------------------------------------------------------------------------


def test_login_history_does_not_inherit_login_bypass() -> None:
    """A path that startswith an allowlisted entry must still require auth.

    This is the core P0-b regression test. Before the exact-match fix,
    ``/web-api/v1/auth/login-history`` slipped past auth because it
    startswith ``/web-api/v1/auth/login``. After the fix, anonymous
    access is rejected.
    """
    client = _build_app(("/web-api/v1/auth/login",))
    resp = client.post("/web-api/v1/auth/login-history", json={})
    # Without a valid session cookie + access token, the session
    # verifier returns None and the middleware short-circuits with 401.
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_code"] in {"auth_required", "auth_invalid"}


def test_login_json_does_not_inherit_login_bypass() -> None:
    """An adjacent suffix (.json) must not piggyback on the login bypass."""
    client = _build_app(("/web-api/v1/auth/login",))
    resp = client.post("/web-api/v1/auth/login.json", json={})
    assert resp.status_code == 401


def test_trailing_slash_variant_is_not_implicitly_allowlisted() -> None:
    """Trailing-slash variant requires auth unless explicitly added to the allowlist.

    The allowlist convention is exact-match — adding the trailing-slash
    form is the responsibility of whoever registers a route that uses
    it. The auth router does not normalise paths.
    """
    client = _build_app(("/web-api/v1/auth/login",))
    resp = client.post("/web-api/v1/auth/login/", json={})
    assert resp.status_code == 401


def test_trailing_slash_variant_can_be_explicitly_allowlisted() -> None:
    """Explicitly listing the trailing-slash form makes it bypass auth."""
    client = _build_app(
        (
            "/web-api/v1/auth/login",
            "/web-api/v1/auth/login/",
        )
    )
    resp = client.post("/web-api/v1/auth/login/", json={})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Sanity: non-allowlisted protected endpoint still requires auth
# ---------------------------------------------------------------------------


def test_protected_endpoint_outside_allowlist_requires_auth() -> None:
    """Smoke check — a normal /web-api/v1 endpoint still demands credentials."""
    client = _build_app(("/web-api/v1/auth/login",))
    resp = client.get("/web-api/v1/projects")
    assert resp.status_code == 401
