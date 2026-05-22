"""Integration coverage for :class:`ForcedPasswordChangeMiddleware`.

spec/011 §FR-011-204 / §NFR-011-007 / §R8
-----------------------------------------
The middleware is the atomic-swap replacement for
:class:`EmailVerificationEnforcementMiddleware`. This suite locks in
the allowlist matrix, the 423 ``ERR_PASSWORD_CHANGE_REQUIRED`` short
circuit, the anonymous / verified pass-through paths, the WebSocket
1011 close future-proofing, the ``/api/v1`` cookie-session bypass
closure (Codex R1 NO-GO fix), and the middleware-stack atomic-swap
invariant (R8 / NFR-011-007).

The tests build a fast in-memory FastAPI application that wires a
stand-in :class:`_PrincipalStateMiddleware` (mirroring
:class:`AuthRouterMiddleware`) plus
:class:`ForcedPasswordChangeMiddleware` configured with a synchronous
in-memory user resolver. We DO NOT spin up Postgres here — that path
is already exercised by the spec/006 + spec/010 integration suites
that resolve users via the real session factory.

The ``test_middleware_chain_order_and_atomic_swap`` test goes a step
further and spins up the real :func:`echoroo.main.create_app` so the
production middleware stack ordering can be inspected in-process.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from echoroo.middleware.auth_router import Principal
from echoroo.middleware.forced_password_change import (
    DEFAULT_ALLOWLIST_METHOD_PATHS,
    ERROR_CODE_PASSWORD_CHANGE_REQUIRED,
    LOCATION_CHANGE_PASSWORD,
    ForcedPasswordChangeMiddleware,
)

_TEST_SESSION_COOKIE = "echoroo_session"


@dataclass
class _User:
    """Minimal user stand-in matching ``users.must_change_password``."""

    id: UUID
    must_change_password: bool = False


class _PrincipalStateMiddleware(BaseHTTPMiddleware):
    """Stand-in for :class:`AuthRouterMiddleware`.

    Populates ``request.state.principal`` so the middleware under test
    can resolve a caller. Passing ``user=None`` simulates an anonymous
    request (e.g. the ``/api/v1/*`` cookie-only legacy fallback path
    where :class:`AuthRouterMiddleware` leaves
    ``request.state.principal = None``).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        user: _User | None,
        attach_principal: bool = True,
    ) -> None:
        super().__init__(app)
        self.user = user
        self.attach_principal = attach_principal

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self.attach_principal:
            # Mirror ``AuthRouterMiddleware``'s legacy-fallback branch
            # for ``/api/v1/*``: principal stays unset so the downstream
            # ``Depends`` chain owns identity resolution. The gate must
            # still resolve the session cookie itself (FR-011-204).
            request.state.principal = None
            return await call_next(request)
        if self.user is None:
            request.state.principal = None
        else:
            request.state.principal = Principal.for_session(
                user_id=self.user.id,
                security_stamp="s" * 64,
            )
        return await call_next(request)


def _build_client(
    user: _User | None,
    *,
    user_resolver_override: Callable[[UUID], Awaitable[_User | None]] | None = None,
    lookup_calls: list[UUID] | None = None,
    attach_principal: bool = True,
    session_to_user_resolver: Callable[[str], Awaitable[_User | None]] | None = None,
) -> TestClient:
    """Build a fast in-memory FastAPI client wired with the gate."""
    app = FastAPI()

    # Catch-all routes for every method the test matrix exercises.
    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def catch_all(full_path: str) -> dict[str, str]:  # noqa: ARG001
        return {"ok": "true"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response("# metrics\n", media_type="text/plain")

    captured_user = user
    captured_calls = lookup_calls

    async def _default_resolver(user_id: UUID) -> _User | None:
        if captured_calls is not None:
            captured_calls.append(user_id)
        if captured_user is not None and captured_user.id == user_id:
            return captured_user  # type: ignore[return-value]
        return None

    resolver: Callable[[UUID], Awaitable[Any]] = (
        user_resolver_override if user_resolver_override is not None else _default_resolver
    )

    app.add_middleware(
        ForcedPasswordChangeMiddleware,
        user_resolver=resolver,
        session_cookie_name=_TEST_SESSION_COOKIE,
        session_to_user_resolver=session_to_user_resolver,
    )
    app.add_middleware(
        _PrincipalStateMiddleware, user=user, attach_principal=attach_principal
    )
    return TestClient(app)


def _must_change_user() -> _User:
    return _User(id=uuid.uuid4(), must_change_password=True)


def _ok_user() -> _User:
    return _User(id=uuid.uuid4(), must_change_password=False)


# --------------------------------------------------------------------------
# Allowlist matrix — every entry MUST pass through (not 423).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/web-api/v1/auth/change-password"),
        ("POST", "/api/v1/auth/change-password"),
        ("POST", "/web-api/v1/auth/logout"),
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/health"),
        ("GET", "/metrics"),
        ("GET", "/favicon.ico"),
        ("GET", "/static/app.css"),
        ("GET", "/static/img/logo.png"),
    ],
)
def test_allowlist_passes_for_must_change_user(method: str, path: str) -> None:
    """Allowlisted ``(method, path)`` pairs MUST NOT return 423."""
    response = _build_client(_must_change_user()).request(method, path)

    # The exact status depends on whether the route is mounted in the
    # stub app — what we MUST assert is that the gate did NOT short
    # circuit with 423 + ERR_PASSWORD_CHANGE_REQUIRED.
    assert response.status_code != 423, (
        f"{method} {path} unexpectedly blocked by gate: {response.text!r}"
    )
    if response.headers.get("location") is not None:
        assert response.headers["location"] != LOCATION_CHANGE_PASSWORD


@pytest.mark.parametrize(
    "path",
    [
        "/web-api/v1/projects",
        "/web-api/v1/projects/abc/recordings",
        "/api/v1/projects",
        "/api/v1/users/me",
        "/web-api/v1/admin/users",
    ],
)
def test_options_preflight_always_passes(path: str) -> None:
    """OPTIONS on any path bypasses the gate (CORS preflight)."""
    response = _build_client(_must_change_user()).request("OPTIONS", path)

    assert response.status_code != 423


# --------------------------------------------------------------------------
# Allowlist negative tests — method-aware allowlist (Codex R1 重要 #1).
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        # Wrong method on allowlisted paths MUST still 423.
        ("POST", "/health"),
        ("POST", "/metrics"),
        ("GET", "/web-api/v1/auth/logout"),
        ("GET", "/api/v1/auth/logout"),
        ("PUT", "/api/v1/auth/change-password"),
        # Allowed method but URL not in allowlist.
        ("POST", "/web-api/v1/auth/change-pasword"),  # typo: not allowed
        ("POST", "/web-api/v1/auth/change-passwordX"),
    ],
)
def test_method_aware_allowlist_blocks_wrong_method(method: str, path: str) -> None:
    """Wrong-method / typo-path requests do NOT bypass the gate."""
    response = _build_client(_must_change_user()).request(method, path)
    assert response.status_code == 423
    body = response.json()
    assert body["code"] == ERROR_CODE_PASSWORD_CHANGE_REQUIRED


# --------------------------------------------------------------------------
# Blocked paths — every non-allowlist request returns 423 +
# ERR_PASSWORD_CHANGE_REQUIRED + Location header.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/web-api/v1/projects"),
        ("POST", "/web-api/v1/projects"),
        ("PUT", "/web-api/v1/projects/abc"),
        ("DELETE", "/web-api/v1/projects/abc"),
        ("GET", "/api/v1/projects"),
        ("POST", "/api/v1/projects"),
        ("GET", "/web-api/v1/me/banners"),
        ("POST", "/web-api/v1/me/banners/dismiss"),
        ("GET", "/web-api/v1/admin/users"),
    ],
)
def test_blocked_path_returns_423(method: str, path: str) -> None:
    response = _build_client(_must_change_user()).request(method, path)

    assert response.status_code == 423
    body = response.json()
    assert body["code"] == ERROR_CODE_PASSWORD_CHANGE_REQUIRED
    assert response.headers["location"] == LOCATION_CHANGE_PASSWORD


def test_blocked_response_body_shape() -> None:
    """Lock the JSON envelope shape for the frontend route guard."""
    response = _build_client(_must_change_user()).get("/web-api/v1/projects")

    assert response.status_code == 423
    body = response.json()
    assert body == {
        "code": ERROR_CODE_PASSWORD_CHANGE_REQUIRED,
        "detail": "Password change required",
    }


# --------------------------------------------------------------------------
# Anonymous / pass-through behaviour.
# --------------------------------------------------------------------------


def test_anonymous_request_passes_through_without_user_lookup() -> None:
    """Requests without a principal MUST NOT touch the user resolver.

    The ``/web-api/v1`` surface stays anonymous when no principal is
    attached — the gate has no opinion on unauthenticated traffic on
    that prefix (the router's hard cookie-required check fires
    upstream).
    """
    lookup_calls: list[UUID] = []
    response = _build_client(None, lookup_calls=lookup_calls).get(
        "/web-api/v1/projects"
    )

    assert response.status_code == 200
    assert lookup_calls == [], (
        "Anonymous requests must not trigger a DB user lookup — gate must "
        "short-circuit before _load_user."
    )


def test_principal_without_user_id_passes_through_without_user_lookup() -> None:
    """``principal.user_id is None`` MUST also short-circuit."""
    lookup_calls: list[UUID] = []

    class _PrincipalLikeNoUserId:
        user_id = None

    app = FastAPI()

    @app.get("/web-api/v1/projects")
    async def projects() -> dict[str, str]:
        return {"ok": "true"}

    async def _resolver(user_id: UUID) -> _User | None:
        lookup_calls.append(user_id)
        return None

    class _StubMiddleware(BaseHTTPMiddleware):
        async def dispatch(
            self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            request.state.principal = _PrincipalLikeNoUserId()
            return await call_next(request)

    app.add_middleware(
        ForcedPasswordChangeMiddleware,
        user_resolver=_resolver,
        session_cookie_name=_TEST_SESSION_COOKIE,
    )
    app.add_middleware(_StubMiddleware)
    response = TestClient(app).get("/web-api/v1/projects")

    assert response.status_code == 200
    assert lookup_calls == []


def test_user_without_must_change_password_passes_through() -> None:
    """A user with ``must_change_password=False`` is never blocked."""
    response = _build_client(_ok_user()).get("/web-api/v1/projects")

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/web-api/v1/projects"),
        ("POST", "/web-api/v1/projects"),
        ("DELETE", "/web-api/v1/projects/abc"),
        ("GET", "/web-api/v1/me/banners"),
        ("GET", "/health"),
        ("GET", "/static/app.css"),
        ("OPTIONS", "/web-api/v1/projects"),
    ],
)
def test_user_without_must_change_password_unblocked_on_all_paths(
    method: str, path: str
) -> None:
    response = _build_client(_ok_user()).request(method, path)
    assert response.status_code != 423


def test_user_lookup_returning_none_falls_through() -> None:
    """If the user row vanished mid-flight, the gate falls through.

    The auth router already accepted the session; surfacing a 423 here
    would leak a misleading error code for what is in fact a stale
    principal. The downstream handler will surface the natural 401/404.
    """
    phantom = _User(id=uuid.uuid4(), must_change_password=True)

    async def _resolver_returning_none(_user_id: UUID) -> _User | None:
        return None

    response = _build_client(
        phantom, user_resolver_override=_resolver_returning_none
    ).get("/web-api/v1/projects")

    assert response.status_code == 200


# --------------------------------------------------------------------------
# v1 vs web-v1 mirror coverage — explicit pair assertions per FR-011-204.
# --------------------------------------------------------------------------


def test_both_v1_mirrors_of_change_password_allowlisted() -> None:
    """Both ``/web-api/v1`` and ``/api/v1`` change-password are allowlisted."""
    client = _build_client(_must_change_user())

    web_response = client.post("/web-api/v1/auth/change-password")
    api_response = client.post("/api/v1/auth/change-password")

    assert web_response.status_code != 423
    assert api_response.status_code != 423


def test_both_v1_mirrors_of_logout_allowlisted() -> None:
    """Both ``/web-api/v1`` and ``/api/v1`` logout are allowlisted."""
    client = _build_client(_must_change_user())

    web_response = client.post("/web-api/v1/auth/logout")
    api_response = client.post("/api/v1/auth/logout")

    assert web_response.status_code != 423
    assert api_response.status_code != 423


# --------------------------------------------------------------------------
# Allowlist negative tests — make sure the right things ARE blocked.
# --------------------------------------------------------------------------


def test_get_change_password_is_blocked() -> None:
    """GET on the change-password URL is NOT allowlisted → 423.

    Codex R1 重要 #1: the allowlist is method-aware. Only
    ``POST /web-api/v1/auth/change-password`` and the ``/api/v1``
    mirror are exempt. GET on the same URL must 423 like any other
    blocked request — the route handler never gets a chance to return
    a 405.
    """
    response = _build_client(_must_change_user()).get(
        "/web-api/v1/auth/change-password"
    )

    assert response.status_code == 423
    body = response.json()
    assert body["code"] == ERROR_CODE_PASSWORD_CHANGE_REQUIRED


def test_non_static_prefix_is_blocked() -> None:
    """``/static-extra/...`` is NOT covered by the ``/static/`` prefix."""
    response = _build_client(_must_change_user()).get("/static-extra/x.css")

    assert response.status_code == 423


# --------------------------------------------------------------------------
# /api/v1 cookie-only bypass closure (Codex R1 NO-GO 致命).
# --------------------------------------------------------------------------


def test_api_v1_cookie_only_must_change_user_blocked_on_post() -> None:
    """``POST /api/v1/projects`` + session cookie + must-change → 423.

    Reproduces the Codex R1 NO-GO 致命: the auth router's
    ``allow_legacy_session_fallback=True`` branch leaves ``principal``
    empty for cookie-only ``/api/v1/*`` calls; the gate must resolve the
    cookie itself so the must-change user does not silently bypass.
    """
    user = _must_change_user()
    cookie_value = str(uuid.uuid4())

    async def _session_resolver(value: str) -> _User | None:
        return user if value == cookie_value else None

    client = _build_client(
        None,
        attach_principal=False,
        session_to_user_resolver=_session_resolver,
    )
    response = client.post(
        "/api/v1/projects",
        cookies={_TEST_SESSION_COOKIE: cookie_value},
    )

    assert response.status_code == 423
    body = response.json()
    assert body["code"] == ERROR_CODE_PASSWORD_CHANGE_REQUIRED
    assert response.headers["location"] == LOCATION_CHANGE_PASSWORD


def test_api_v1_cookie_only_must_change_user_blocked_on_get() -> None:
    """``GET /api/v1/projects`` + session cookie + must-change → 423."""
    user = _must_change_user()
    cookie_value = str(uuid.uuid4())

    async def _session_resolver(value: str) -> _User | None:
        return user if value == cookie_value else None

    client = _build_client(
        None,
        attach_principal=False,
        session_to_user_resolver=_session_resolver,
    )
    response = client.get(
        "/api/v1/projects",
        cookies={_TEST_SESSION_COOKIE: cookie_value},
    )

    assert response.status_code == 423


def test_api_v1_cookie_only_ok_user_passes_through() -> None:
    """An OK user with ``must_change_password=false`` is never blocked."""
    user = _ok_user()
    cookie_value = str(uuid.uuid4())

    async def _session_resolver(value: str) -> _User | None:
        return user if value == cookie_value else None

    client = _build_client(
        None,
        attach_principal=False,
        session_to_user_resolver=_session_resolver,
    )
    response = client.post(
        "/api/v1/projects",
        cookies={_TEST_SESSION_COOKIE: cookie_value},
    )

    assert response.status_code == 200


def test_api_v1_cookie_only_no_cookie_passes_through() -> None:
    """No cookie → the downstream ``Depends`` chain owns the 401."""
    client = _build_client(
        None,
        attach_principal=False,
    )
    response = client.post("/api/v1/projects")
    assert response.status_code == 200  # catch-all returns 200; gate does not 423


def test_api_v1_cookie_only_unresolvable_cookie_passes_through() -> None:
    """Unknown cookie value → no 423 leak, downstream handles 401."""
    cookie_value = str(uuid.uuid4())

    async def _session_resolver(value: str) -> _User | None:  # noqa: ARG001
        return None

    client = _build_client(
        None,
        attach_principal=False,
        session_to_user_resolver=_session_resolver,
    )
    response = client.post(
        "/api/v1/projects",
        cookies={_TEST_SESSION_COOKIE: cookie_value},
    )

    assert response.status_code == 200


def test_cookie_session_resolver_sql_rejects_revoked_family() -> None:
    """The default cookie→user resolver SQL must filter out revoked sessions.

    Codex R2 finding: without an explicit ``tf.revoked_at IS NULL`` clause,
    a logged-out / rotated session cookie would still resolve a live user
    here and the middleware would emit ``423 ERR_PASSWORD_CHANGE_REQUIRED``
    for an already-invalidated session — contradicting
    :class:`JwtSessionVerifier.verify` (services/session_verification.py)
    which rejects revoked families with 401. Pin the SQL fragment so a
    future refactor cannot silently drop the clause.
    """
    import inspect

    from echoroo.middleware.forced_password_change import (
        ForcedPasswordChangeMiddleware,
    )

    # Inspect the helper that actually issues the SQL — both the HTTP
    # and WebSocket entry points delegate to this one private method.
    source = inspect.getsource(
        ForcedPasswordChangeMiddleware._resolve_user_from_session_cookie_value
    )
    # Match the clause regardless of whitespace / line-wrapping differences
    # introduced by formatters; key requirement is that the filter exists
    # adjacent to the ``tf.family_id`` lookup.
    normalised = " ".join(source.split())
    assert "tf.revoked_at IS NULL" in normalised, (
        "ForcedPasswordChangeMiddleware._resolve_user_from_session_cookie "
        "must filter revoked token families to keep parity with "
        "JwtSessionVerifier.verify; the cookie fallback would otherwise "
        "upgrade a revoked-session 401 into a misleading 423."
    )


def test_web_api_v1_cookie_only_must_change_user_blocked() -> None:
    """Closing the bypass on ``/web-api/v1`` too via principal path.

    ``AuthRouterMiddleware`` always attaches a principal for
    ``/web-api/v1`` callers, so this branch exercises the standard
    principal-resolution path (not the cookie-fallback added for
    ``/api/v1``).
    """
    user = _must_change_user()
    client = _build_client(user)
    response = client.post("/web-api/v1/projects")
    assert response.status_code == 423


# --------------------------------------------------------------------------
# WebSocket scope close 1011 — FR-011-204 future-proofing.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_websocket_scope_closes_with_1011_for_must_change_user() -> None:
    """WebSocket connections for must-change users close with 1011."""
    user = _must_change_user()

    async def _resolver(user_id: UUID) -> _User | None:
        if user_id == user.id:
            return user
        return None

    sent_messages: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    async def _receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def _dummy_app(
        scope: Any, receive: Any, send: Any  # noqa: ARG001
    ) -> None:
        sent_messages.append({"type": "downstream.called"})

    middleware = ForcedPasswordChangeMiddleware(
        app=_dummy_app,
        user_resolver=_resolver,
        session_cookie_name=_TEST_SESSION_COOKIE,
    )

    # Carry the principal in scope["state"] — the WebSocket path reads
    # the principal via that mapping.
    scope = {
        "type": "websocket",
        "path": "/ws/anything",
        "headers": [],
        "state": {
            "principal": Principal.for_session(
                user_id=user.id, security_stamp="s" * 64
            ),
        },
    }
    await middleware(scope, _receive, _send)

    close_messages = [m for m in sent_messages if m.get("type") == "websocket.close"]
    assert close_messages, f"expected websocket.close, got {sent_messages!r}"
    assert close_messages[0]["code"] == 1011

    downstream_calls = [m for m in sent_messages if m.get("type") == "downstream.called"]
    assert downstream_calls == [], (
        "downstream WebSocket app must not be called when the user must "
        "change password"
    )


@pytest.mark.asyncio
async def test_websocket_scope_passes_through_for_anonymous() -> None:
    """Anonymous WebSocket scopes fall through to the downstream app."""
    sent_messages: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    async def _receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def _dummy_app(
        scope: Any, receive: Any, send: Any  # noqa: ARG001
    ) -> None:
        sent_messages.append({"type": "downstream.called"})

    middleware = ForcedPasswordChangeMiddleware(
        app=_dummy_app, session_cookie_name=_TEST_SESSION_COOKIE
    )
    scope = {
        "type": "websocket",
        "path": "/ws/anything",
        "headers": [],
        "state": {"principal": None},
    }
    await middleware(scope, _receive, _send)

    downstream_calls = [m for m in sent_messages if m.get("type") == "downstream.called"]
    assert downstream_calls, "downstream WebSocket app MUST be called for anonymous"


@pytest.mark.asyncio
async def test_websocket_scope_passes_through_for_ok_user() -> None:
    """WebSocket users without ``must_change_password`` flow through."""
    user = _ok_user()

    async def _resolver(user_id: UUID) -> _User | None:
        return user if user_id == user.id else None

    sent_messages: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    async def _receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def _dummy_app(
        scope: Any, receive: Any, send: Any  # noqa: ARG001
    ) -> None:
        sent_messages.append({"type": "downstream.called"})

    middleware = ForcedPasswordChangeMiddleware(
        app=_dummy_app,
        user_resolver=_resolver,
        session_cookie_name=_TEST_SESSION_COOKIE,
    )
    scope = {
        "type": "websocket",
        "path": "/ws/anything",
        "headers": [],
        "state": {
            "principal": Principal.for_session(
                user_id=user.id, security_stamp="s" * 64
            ),
        },
    }
    await middleware(scope, _receive, _send)

    downstream_calls = [m for m in sent_messages if m.get("type") == "downstream.called"]
    assert downstream_calls, "downstream WebSocket app MUST be called for ok user"
    close_messages = [m for m in sent_messages if m.get("type") == "websocket.close"]
    assert close_messages == []


@pytest.mark.asyncio
async def test_websocket_scope_resolves_session_cookie_for_must_change_user() -> None:
    """WebSocket without a pre-attached principal falls back to cookie.

    Codex R1 重要 #2: the production WebSocket scope is NOT decorated
    by :class:`AuthRouterMiddleware` (it is a
    :class:`BaseHTTPMiddleware`, which only sees HTTP scopes). The gate
    must therefore parse the ``Cookie:`` header out of the raw ASGI
    scope and resolve the session itself, mirroring the ``/api/v1``
    HTTP branch. This test covers that path through the same code with
    a pluggable session resolver.
    """
    user = _must_change_user()
    cookie_value = str(uuid.uuid4())

    async def _session_resolver(value: str) -> _User | None:
        return user if value == cookie_value else None

    sent_messages: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    async def _receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    async def _dummy_app(
        scope: Any, receive: Any, send: Any  # noqa: ARG001
    ) -> None:
        sent_messages.append({"type": "downstream.called"})

    middleware = ForcedPasswordChangeMiddleware(
        app=_dummy_app,
        session_cookie_name=_TEST_SESSION_COOKIE,
        session_to_user_resolver=_session_resolver,
    )
    cookie_header = f"{_TEST_SESSION_COOKIE}={cookie_value}".encode("latin-1")
    scope = {
        "type": "websocket",
        "path": "/ws/anything",
        "headers": [(b"cookie", cookie_header)],
        # No state.principal — exercises the cookie fallback.
        "state": {},
    }
    await middleware(scope, _receive, _send)

    close_messages = [m for m in sent_messages if m.get("type") == "websocket.close"]
    assert close_messages, f"expected websocket.close, got {sent_messages!r}"
    assert close_messages[0]["code"] == 1011


# --------------------------------------------------------------------------
# Module-level invariants.
# --------------------------------------------------------------------------


def test_change_password_path_not_in_public_auth_paths() -> None:
    """Per security review M7, change-password is NOT in PUBLIC_AUTH_PATHS.

    The endpoint is authenticated (session + CSRF) — the gate lets it
    through because the caller is authenticated and being routed to the
    only screen they may reach. Adding it to ``PUBLIC_AUTH_PATHS``
    would skip both auth and CSRF, which is unsafe.
    """
    from echoroo.core.auth_paths import PUBLIC_AUTH_PATHS

    assert "/web-api/v1/auth/change-password" not in PUBLIC_AUTH_PATHS
    assert "/api/v1/auth/change-password" not in PUBLIC_AUTH_PATHS


def test_v1_mirrors_present_in_default_allowlist() -> None:
    """Both v1 and web-v1 change-password + logout are in the allowlist."""
    from echoroo.middleware.forced_password_change import DEFAULT_ALLOWLIST_PATHS

    assert "/web-api/v1/auth/change-password" in DEFAULT_ALLOWLIST_PATHS
    assert "/api/v1/auth/change-password" in DEFAULT_ALLOWLIST_PATHS
    assert "/web-api/v1/auth/logout" in DEFAULT_ALLOWLIST_PATHS
    assert "/api/v1/auth/logout" in DEFAULT_ALLOWLIST_PATHS


def test_method_aware_allowlist_carries_post_pairs() -> None:
    """Locked-in: spec's method tags are on the canonical allowlist."""
    assert (
        "POST",
        "/web-api/v1/auth/change-password",
    ) in DEFAULT_ALLOWLIST_METHOD_PATHS
    assert (
        "POST",
        "/api/v1/auth/change-password",
    ) in DEFAULT_ALLOWLIST_METHOD_PATHS
    assert ("POST", "/web-api/v1/auth/logout") in DEFAULT_ALLOWLIST_METHOD_PATHS
    assert ("POST", "/api/v1/auth/logout") in DEFAULT_ALLOWLIST_METHOD_PATHS
    assert ("GET", "/health") in DEFAULT_ALLOWLIST_METHOD_PATHS
    assert ("GET", "/metrics") in DEFAULT_ALLOWLIST_METHOD_PATHS
    # GET counterparts MUST NOT be on the canonical allowlist — they
    # are blocked so the gate fires before the route handler returns
    # a 405.
    assert ("GET", "/web-api/v1/auth/change-password") not in DEFAULT_ALLOWLIST_METHOD_PATHS
    assert ("GET", "/api/v1/auth/change-password") not in DEFAULT_ALLOWLIST_METHOD_PATHS


# --------------------------------------------------------------------------
# spec/011 §R8 / NFR-011-007 — middleware chain atomic swap invariant.
# --------------------------------------------------------------------------


def test_middleware_chain_order_and_atomic_swap() -> None:
    """Lock in the production middleware-stack ordering invariants.

    Codex R1 重要 #3 fix: ``ForcedPasswordChangeMiddleware`` is the
    atomic-swap replacement for
    :class:`EmailVerificationEnforcementMiddleware`. We assert that:

    * The new middleware is registered.
    * The old middleware is NOT registered (atomic swap, NFR-011-007).
    * The new middleware sits between :class:`AuthRouterMiddleware`
      (upstream — populates the principal) and
      :class:`TwoFactorEnforcementMiddleware` (downstream — needs the
      principal too) in the LIFO execution order.

    Any future re-ordering or accidental dual-registration of the old
    + new middlewares will fail this test in CI before reaching prod.
    """
    # Import lazily so the heavy ``echoroo.main`` import does not run
    # at collection time for the rest of the suite.
    from echoroo.main import create_app
    from echoroo.middleware.auth_router import AuthRouterMiddleware
    from echoroo.middleware.two_factor_enforcement import (
        TwoFactorEnforcementMiddleware,
    )

    app = create_app()
    cls_names = [m.cls.__name__ for m in app.user_middleware]

    assert "ForcedPasswordChangeMiddleware" in cls_names, (
        "ForcedPasswordChangeMiddleware must be registered (FR-011-204)"
    )
    assert "EmailVerificationEnforcementMiddleware" not in cls_names, (
        "EmailVerificationEnforcementMiddleware must NOT be registered "
        "(spec/011 R8 atomic-swap invariant)"
    )

    forced_idx = next(
        i
        for i, m in enumerate(app.user_middleware)
        if m.cls is ForcedPasswordChangeMiddleware
    )
    auth_router_idx = next(
        i
        for i, m in enumerate(app.user_middleware)
        if m.cls is AuthRouterMiddleware
    )
    two_factor_idx = next(
        i
        for i, m in enumerate(app.user_middleware)
        if m.cls is TwoFactorEnforcementMiddleware
    )

    # Starlette stores middleware via ``user_middleware.insert(0, ...)``
    # so the LAST ``add_middleware`` call lives at index 0 — the
    # OUTERMOST wrapper that executes FIRST per request. Lower index =
    # outer = runs earlier. We need:
    #
    #   AuthRouter (outer / runs first) → ForcedPasswordChange (middle)
    #   → TwoFactorEnforcement (inner / runs last)
    #
    # which means:
    #
    #   auth_router_idx < forced_idx < two_factor_idx
    assert auth_router_idx < forced_idx < two_factor_idx, (
        f"middleware order broken: AuthRouter={auth_router_idx}, "
        f"ForcedPasswordChange={forced_idx}, "
        f"TwoFactorEnforcement={two_factor_idx}; expected "
        "auth_router_idx < forced_idx < two_factor_idx so that "
        "AuthRouter runs first (populates principal), then "
        "ForcedPasswordChange, then TwoFactorEnforcement"
    )
