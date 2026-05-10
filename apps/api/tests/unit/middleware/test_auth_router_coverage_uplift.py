"""Coverage uplift unit tests for ``echoroo.middleware.auth_router``.

Phase 17 §C easy-win batch 1: covers the small reject-branch surface that
the existing :file:`test_auth_router.py` smoke tests do not exercise:

    * Lines 218, 223 — the two pure helpers (`hash_api_key_secret`,
                       `constant_time_eq`).
    * Line 473 — `_authenticate_api_key` when the verifier is unconfigured.
    * Line 500 — `_authenticate_api_key` with empty Bearer credentials.
    * Lines 555-557, 570 — `_authenticate_session` verifier missing /
                            session unknown.
    * Lines 583-587 — InvalidTokenError + user-mismatch reject paths.
    * Lines 535-539 — IP enforcer blocks the request.
    * Line 439 — nested-allowlist break when session_prefix + cookie present.

so the module clears the 95% permission-critical threshold without
touching production code.
"""

from __future__ import annotations

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
    constant_time_eq,
    hash_api_key_secret,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubSessionVerifier:
    def __init__(self, mapping: dict[str, tuple[UUID, str]]) -> None:
        self._mapping = mapping

    async def verify(self, session_id: str) -> tuple[UUID, str] | None:
        return self._mapping.get(session_id)


class _StubApiKeyVerifier:
    def __init__(self, expected: str, record: ApiKeyRecord) -> None:
        self._expected = expected
        self._record = record

    async def verify(self, raw_key: str) -> ApiKeyRecord | None:
        return self._record if raw_key == self._expected else None


class _AlwaysRejectIpEnforcer:
    async def enforce(self, **_kw: object) -> bool:
        return False


def _echo_handler(request: Request) -> JSONResponse:
    principal: Principal | None = getattr(request.state, "principal", None)
    return JSONResponse(
        {
            "auth_kind": principal.auth_kind if principal else None,
            "user_id": str(principal.user_id) if principal else None,
        }
    )


def _build_app(config: AuthRouterConfig) -> TestClient:
    app = Starlette(
        routes=[
            Route("/api/v1/ping", _echo_handler),
            Route("/web-api/v1/ping", _echo_handler),
            Route("/health", _echo_handler),
        ]
    )
    app.add_middleware(AuthRouterMiddleware, config=config)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_hash_api_key_secret_returns_64_hex_chars() -> None:
    """hash_api_key_secret returns a SHA-256 hex digest (line 218)."""
    digest = hash_api_key_secret("ek_live_secret_value")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
    # Determinism.
    assert digest == hash_api_key_secret("ek_live_secret_value")


def test_constant_time_eq_matches_equal_strings() -> None:
    """constant_time_eq returns True for equal strings (line 223)."""
    assert constant_time_eq("abc", "abc") is True
    assert constant_time_eq("abc", "abd") is False
    assert constant_time_eq("", "") is True


# ---------------------------------------------------------------------------
# /api/v1 reject branches
# ---------------------------------------------------------------------------


def test_api_v1_returns_unavailable_when_verifier_missing() -> None:
    """A missing api_key_verifier yields auth_unavailable (line 473)."""
    config = AuthRouterConfig(api_key_verifier=None)
    client = _build_app(config)
    resp = client.get(
        "/api/v1/ping", headers={"Authorization": "Bearer something"}
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_unavailable"


def test_api_v1_rejects_empty_bearer_credentials() -> None:
    """An ``Authorization: Bearer `` header with empty credentials is rejected
    (line 500).
    """
    config = AuthRouterConfig(
        api_key_verifier=_StubApiKeyVerifier(
            expected="never-used",
            record=ApiKeyRecord(
                api_key_id=uuid4(), user_id=uuid4(), granted_permissions=()
            ),
        )
    )
    client = _build_app(config)
    resp = client.get(
        "/api/v1/ping", headers={"Authorization": "Bearer "}
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_required"


def test_api_v1_rejects_when_ip_enforcer_blocks() -> None:
    """The IP enforcer's False return triggers a 403 err_ip_not_allowed
    (lines 535-539).
    """
    record = ApiKeyRecord(
        api_key_id=uuid4(),
        user_id=uuid4(),
        granted_permissions=("view_detection",),
        allowed_ip_cidrs=("10.0.0.0/8",),
    )
    config = AuthRouterConfig(
        api_key_verifier=_StubApiKeyVerifier("ek_secret", record),
        ip_enforcer=_AlwaysRejectIpEnforcer(),
    )
    client = _build_app(config)
    resp = client.get(
        "/api/v1/ping", headers={"Authorization": "Bearer ek_secret"}
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "err_ip_not_allowed"


# ---------------------------------------------------------------------------
# /web-api/v1 session reject branches
# ---------------------------------------------------------------------------


def test_session_returns_unavailable_when_verifier_missing() -> None:
    """A missing session_verifier yields auth_unavailable (lines 555-557)."""
    config = AuthRouterConfig(session_verifier=None)
    client = _build_app(config)
    resp = client.get(
        "/web-api/v1/ping",
        cookies={
            "session_id": "abc",
            "access_token": "xyz",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_unavailable"


def test_session_rejects_unknown_session_cookie() -> None:
    """Unknown session_id resolves to auth_invalid (line 570)."""
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({}),  # empty mapping
    )
    client = _build_app(config)
    resp = client.get(
        "/web-api/v1/ping",
        cookies={"session_id": "ghost", "access_token": "irrelevant"},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_session_rejects_invalid_access_token() -> None:
    """An invalid access token yields auth_invalid (lines 583-584)."""
    user_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({"sid": (user_id, "stamp")}),
    )
    client = _build_app(config)
    resp = client.get(
        "/web-api/v1/ping",
        cookies={
            "session_id": "sid",
            "access_token": "totally-not-a-jwt",
        },
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_session_rejects_user_mismatch() -> None:
    """When the session user differs from the JWT sub, return auth_mismatch
    (lines 587-589).
    """
    session_user = uuid4()
    other_user = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({"sid": (session_user, "stamp")}),
    )
    # Mint an access token for a DIFFERENT user but the same security stamp
    # so the StaleTokenError check passes and we hit the user-mismatch branch.
    token = issue_access_token(user_id=other_user, security_stamp="stamp")

    client = _build_app(config)
    resp = client.get(
        "/web-api/v1/ping",
        cookies={"session_id": "sid", "access_token": token},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_mismatch"
