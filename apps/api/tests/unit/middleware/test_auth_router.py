"""Smoke tests for :mod:`echoroo.middleware.auth_router` (T070)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from echoroo.core.auth import issue_access_token
from echoroo.middleware.auth_router import (
    ApiKeyRecord,
    AuthRouterConfig,
    AuthRouterMiddleware,
    Principal,
)

# ---------------------------------------------------------------------------
# Stubs for the verifier protocols
# ---------------------------------------------------------------------------


class _StubApiKeyVerifier:
    def __init__(self, expected: str, record: ApiKeyRecord) -> None:
        self._expected = expected
        self._record = record

    async def verify(self, raw_key: str) -> ApiKeyRecord | None:
        if raw_key == self._expected:
            return self._record
        return None


class _StubSessionVerifier:
    def __init__(self, mapping: dict[str, tuple[UUID, str]]) -> None:
        self._mapping = mapping

    async def verify(self, session_id: str) -> tuple[UUID, str] | None:
        return self._mapping.get(session_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app(config: AuthRouterConfig) -> TestClient:
    async def echo(request: Request) -> JSONResponse:
        principal: Principal | None = getattr(request.state, "principal", None)
        return JSONResponse(
            {
                "auth_kind": principal.auth_kind if principal else None,
                "user_id": str(principal.user_id) if principal else None,
            }
        )

    app = Starlette(
        routes=[
            Route("/api/v1/ping", echo),
            Route("/web-api/v1/ping", echo),
            Route("/health", echo),
        ]
    )
    app.add_middleware(AuthRouterMiddleware, config=config)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_passes_through_without_principal() -> None:
    """Paths outside both prefixes must not require auth."""
    config = AuthRouterConfig()
    client = _build_app(config)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"auth_kind": None, "user_id": None}


def test_api_v1_requires_bearer_api_key() -> None:
    """Missing Authorization header returns 401 with the right error code."""
    config = AuthRouterConfig(
        api_key_verifier=_StubApiKeyVerifier(
            expected="never-used",
            record=ApiKeyRecord(
                api_key_id=uuid4(),
                user_id=uuid4(),
                granted_permissions=(),
            ),
        )
    )
    client = _build_app(config)
    resp = client.get("/api/v1/ping")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_code"] in {"auth_required", "auth_invalid"}


def test_api_v1_accepts_valid_api_key() -> None:
    """A valid Bearer key resolves a Principal with auth_kind=api_key."""
    user_id = uuid4()
    api_key_id = uuid4()
    record = ApiKeyRecord(
        api_key_id=api_key_id,
        user_id=user_id,
        granted_permissions=("read", "vote"),
    )
    config = AuthRouterConfig(
        api_key_verifier=_StubApiKeyVerifier("ek_live_secret", record)
    )
    client = _build_app(config)
    resp = client.get(
        "/api/v1/ping",
        headers={"Authorization": "Bearer ek_live_secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_kind"] == "api_key"
    assert body["user_id"] == str(user_id)


def test_web_api_v1_requires_session_cookie() -> None:
    """Missing session cookie returns 401."""
    config = AuthRouterConfig(session_verifier=_StubSessionVerifier({}))
    client = _build_app(config)
    resp = client.get("/web-api/v1/ping")
    assert resp.status_code == 401


def test_web_api_v1_accepts_session_with_matching_stamp() -> None:
    """Session cookie + JWT (matching live stamp) yields auth_kind=session."""
    user_id = uuid4()
    stamp = "a" * 64
    session_id = "sess-1"
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_access_token(
        user_id=user_id,
        security_stamp=stamp,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        "/web-api/v1/ping",
        cookies={"session_id": session_id, "access_token": token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_kind"] == "session"
    assert body["user_id"] == str(user_id)


def test_web_api_v1_rejects_stale_security_stamp() -> None:
    """A revoked session (stamp rotated) yields 419."""
    user_id = uuid4()
    issuance_stamp = "a" * 64
    live_stamp = "b" * 64
    session_id = "sess-2"
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, live_stamp)})
    )
    token = issue_access_token(
        user_id=user_id,
        security_stamp=issuance_stamp,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        "/web-api/v1/ping",
        cookies={"session_id": session_id, "access_token": token},
    )
    assert resp.status_code == 419
    assert resp.json()["error_code"] == "session_revoked"


def test_public_path_allowlist_skips_auth() -> None:
    """Login MUST be reachable without credentials."""
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({}),
        public_path_allowlist=("/web-api/v1/auth/login",),
    )

    async def login(request: Request) -> JSONResponse:
        return JSONResponse({"principal": None})

    app = Starlette(
        routes=[Route("/web-api/v1/auth/login", login, methods=["POST"])]
    )
    app.add_middleware(AuthRouterMiddleware, config=config)
    client = TestClient(app)
    resp = client.post("/web-api/v1/auth/login", json={"email": "x", "password": "y"})
    assert resp.status_code == 200
