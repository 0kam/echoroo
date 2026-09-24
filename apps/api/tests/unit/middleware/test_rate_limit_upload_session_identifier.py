"""Upload-session create/complete limiters bucket per authenticated user.

Behind the SvelteKit BFF the direct peer is always the frontend container, so
fastapi-limiter's default ``<X-Forwarded-For or peer IP>:<path>`` identifier put
every user into one shared bucket and let the caller pick a bucket via
``X-Forwarded-For``. These tests drive the real limiter dependencies through a
minimal app whose peer IP is fixed, the way it is behind the BFF.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI, Request
from fastapi_limiter import FastAPILimiter, default_identifier, http_default_callback

from echoroo.middleware.rate_limit import (
    _upload_session_complete_bucket_identifier,
    _upload_session_create_bucket_identifier,
    settings,
    upload_session_complete_rate_limiter,
    upload_session_create_rate_limiter,
)

CREATE_PATH = "/web-api/v1/projects/{p}/datasets/{d}/upload-sessions"
COMPLETE_PATH = "/web-api/v1/projects/{p}/datasets/{d}/upload-sessions/{s}/complete"


class _FakeLimiterRedis:
    """In-memory stand-in for the fastapi-limiter Lua script (fixed window count).

    fakeredis has no Lua support without ``lupa``; the limiter only needs
    ``script_load`` + ``evalsha`` returning 0 (allowed) or the remaining TTL.
    """

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def script_load(self, _script: str) -> str:
        return "sha"

    async def evalsha(self, _sha: str, _numkeys: int, key: str, limit: str, window_ms: str) -> int:
        current = self.counts.get(key, 0)
        if current + 1 > int(limit):
            return int(window_ms)
        self.counts[key] = current + 1
        return 0


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeLimiterRedis:
    # Mirror FastAPILimiter.init() with the library defaults, restored afterwards.
    redis = _FakeLimiterRedis()
    monkeypatch.setattr(FastAPILimiter, "redis", redis)
    monkeypatch.setattr(FastAPILimiter, "prefix", "fastapi-limiter")
    monkeypatch.setattr(FastAPILimiter, "lua_sha", "sha")
    monkeypatch.setattr(FastAPILimiter, "identifier", default_identifier)
    monkeypatch.setattr(FastAPILimiter, "http_callback", http_default_callback)
    return redis


def _app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _principal_from_test_header(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        # Stand-in for AuthRouterMiddleware: resolve the caller from a test header.
        user = request.headers.get("X-Test-User")
        request.state.principal = SimpleNamespace(user_id=UUID(user)) if user else None
        return await call_next(request)

    @app.post(CREATE_PATH)
    async def _create(_: None = Depends(upload_session_create_rate_limiter())) -> dict[str, str]:
        return {"ok": "create"}

    @app.post(COMPLETE_PATH)
    async def _complete(
        _: None = Depends(upload_session_complete_rate_limiter()),
    ) -> dict[str, str]:
        return {"ok": "complete"}

    return app


def _client() -> httpx.AsyncClient:
    # Every request arrives from the same peer, as it does behind the BFF.
    transport = httpx.ASGITransport(app=_app(), client=("172.19.0.2", 51234))
    return httpx.AsyncClient(transport=transport, base_url="http://api")


def _create_url(project: UUID, dataset: UUID) -> str:
    return CREATE_PATH.format(p=project, d=dataset)


def _complete_url(project: UUID, dataset: UUID, session: UUID) -> str:
    return COMPLETE_PATH.format(p=project, d=dataset, s=session)


@pytest.mark.asyncio
async def test_create_bucket_is_per_user_not_per_peer(fake_redis: _FakeLimiterRedis) -> None:
    limit = settings.RATE_LIMIT_UPLOAD_SESSION_CREATE_ATTEMPTS
    project, dataset = uuid4(), uuid4()
    alice, bob = str(uuid4()), str(uuid4())
    async with _client() as client:
        for _ in range(limit):
            resp = await client.post(_create_url(project, dataset), headers={"X-Test-User": alice})
            assert resp.status_code == 200
        exhausted = await client.post(_create_url(project, dataset), headers={"X-Test-User": alice})
        assert exhausted.status_code == 429

        # Same peer IP, same dataset — Bob still has his own full budget.
        resp = await client.post(_create_url(project, dataset), headers={"X-Test-User": bob})
        assert resp.status_code == 200

    assert set(fake_redis.counts) == {
        f"fastapi-limiter:upload-session-create:user:{alice}:0:0",
        f"fastapi-limiter:upload-session-create:user:{bob}:0:0",
    }


@pytest.mark.asyncio
async def test_complete_bucket_is_per_user_not_per_peer(fake_redis: _FakeLimiterRedis) -> None:
    limit = settings.RATE_LIMIT_UPLOAD_SESSION_COMPLETE_ATTEMPTS
    project, dataset = uuid4(), uuid4()
    alice, bob = str(uuid4()), str(uuid4())
    async with _client() as client:
        for _ in range(limit):
            resp = await client.post(
                _complete_url(project, dataset, uuid4()), headers={"X-Test-User": alice}
            )
            assert resp.status_code == 200
        exhausted = await client.post(
            _complete_url(project, dataset, uuid4()), headers={"X-Test-User": alice}
        )
        assert exhausted.status_code == 429

        resp = await client.post(
            _complete_url(project, dataset, uuid4()), headers={"X-Test-User": bob}
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_forwarded_for_cannot_change_the_bucket(fake_redis: _FakeLimiterRedis) -> None:
    limit = settings.RATE_LIMIT_UPLOAD_SESSION_CREATE_ATTEMPTS
    project, dataset = uuid4(), uuid4()
    alice = str(uuid4())
    async with _client() as client:
        for i in range(limit):
            resp = await client.post(
                _create_url(project, dataset),
                headers={"X-Test-User": alice, "X-Forwarded-For": f"203.0.113.{i}"},
            )
            assert resp.status_code == 200
        spoofed = await client.post(
            _create_url(project, dataset),
            headers={"X-Test-User": alice, "X-Forwarded-For": "198.51.100.77"},
        )
        assert spoofed.status_code == 429

    assert list(fake_redis.counts) == [f"fastapi-limiter:upload-session-create:user:{alice}:0:0"]


@pytest.mark.asyncio
async def test_other_datasets_and_sessions_share_the_user_bucket(
    fake_redis: _FakeLimiterRedis,
) -> None:
    # Resource ids in the path must not hand out a fresh budget.
    limit = settings.RATE_LIMIT_UPLOAD_SESSION_CREATE_ATTEMPTS
    alice = str(uuid4())
    async with _client() as client:
        for _ in range(limit):
            resp = await client.post(_create_url(uuid4(), uuid4()), headers={"X-Test-User": alice})
            assert resp.status_code == 200
        resp = await client.post(_create_url(uuid4(), uuid4()), headers={"X-Test-User": alice})
        assert resp.status_code == 429

        # Create and complete are separate budgets for the same user.
        resp = await client.post(
            _complete_url(uuid4(), uuid4(), uuid4()), headers={"X-Test-User": alice}
        )
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_identifiers_ignore_forwarded_for_without_principal() -> None:
    # Anonymous callers are rejected by the auth middleware first; the fallback
    # still keys on the direct peer, never on X-Forwarded-For.
    request = SimpleNamespace(
        state=SimpleNamespace(principal=None),
        client=SimpleNamespace(host="172.19.0.2"),
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert (
        await _upload_session_create_bucket_identifier(request)
        == "upload-session-create:anon:172.19.0.2"
    )
    assert (
        await _upload_session_complete_bucket_identifier(request)
        == "upload-session-complete:anon:172.19.0.2"
    )
