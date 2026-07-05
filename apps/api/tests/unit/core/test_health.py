"""Unit tests for the readiness probes (``echoroo.core.health``) and the
``/health/ready`` endpoint wiring.

The three dependency probes (DB, Redis, S3) are stubbed so no live
infrastructure is required. The endpoint tests drive the FastAPI app via
``ASGITransport`` with ``check_readiness`` patched, asserting the 200 / 503
contract and that the body never leaks anything beyond component names and
``ok`` / ``fail``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from echoroo.core import health
from echoroo.main import create_app


class _FakeRedisOk:
    async def ping(self) -> bool:
        return True


class _FakeRedisFail:
    async def ping(self) -> bool:
        raise ConnectionError("boom")


class _FakeSession:
    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def execute(self, _stmt: Any) -> None:
        if self._fail:
            raise ConnectionError("db down")


def _session_factory(*, fail: bool = False) -> Any:
    def _factory() -> _FakeSession:
        return _FakeSession(fail=fail)

    return _factory


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_database_ok() -> None:
    assert await health._check_database(_session_factory()) is True


@pytest.mark.asyncio
async def test_check_database_failure_returns_false() -> None:
    assert await health._check_database(_session_factory(fail=True)) is False


@pytest.mark.asyncio
async def test_check_redis_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_conn() -> _FakeRedisOk:
        return _FakeRedisOk()

    monkeypatch.setattr(health, "get_redis_connection", _fake_conn)
    assert await health._check_redis() is True


@pytest.mark.asyncio
async def test_check_redis_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_conn() -> _FakeRedisFail:
        return _FakeRedisFail()

    monkeypatch.setattr(health, "get_redis_connection", _fake_conn)
    assert await health._check_redis() is False


@pytest.mark.asyncio
async def test_check_s3_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(health, "_head_bucket_sync", lambda: None)
    assert await health._check_s3() is True


@pytest.mark.asyncio
async def test_check_s3_failure_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> None:
        raise RuntimeError("no bucket")

    monkeypatch.setattr(health, "_head_bucket_sync", _boom)
    assert await health._check_s3() is False


@pytest.mark.asyncio
async def test_probe_timeout_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """A probe that hangs past the timeout is reported as failed, not raised."""

    class _HangRedis:
        async def ping(self) -> bool:
            await asyncio.sleep(health.READINESS_PROBE_TIMEOUT_S + 5)
            return True

    async def _fake_conn() -> _HangRedis:
        return _HangRedis()

    monkeypatch.setattr(health, "get_redis_connection", _fake_conn)
    monkeypatch.setattr(health, "READINESS_PROBE_TIMEOUT_S", 0.01)
    assert await health._check_redis() is False


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_readiness_all_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _true() -> bool:
        return True

    monkeypatch.setattr(health, "_check_database", lambda _f: _true())
    monkeypatch.setattr(health, "_check_redis", _true)
    monkeypatch.setattr(health, "_check_s3", _true)

    ready, checks = await health.check_readiness(session_factory=_session_factory())
    assert ready is True
    assert checks == {"database": "ok", "redis": "ok", "s3": "ok"}


@pytest.mark.asyncio
async def test_check_readiness_names_failing_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _true() -> bool:
        return True

    async def _false() -> bool:
        return False

    monkeypatch.setattr(health, "_check_database", lambda _f: _true())
    monkeypatch.setattr(health, "_check_redis", _false)  # redis is the failure
    monkeypatch.setattr(health, "_check_s3", _true)

    ready, checks = await health.check_readiness(session_factory=_session_factory())
    assert ready is False
    assert checks["redis"] == "fail"
    assert checks["database"] == "ok"
    assert checks["s3"] == "ok"


# ---------------------------------------------------------------------------
# Endpoint wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_200_when_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _ready(session_factory: Any = None) -> tuple[bool, dict[str, str]]:
        return True, {"database": "ok", "redis": "ok", "s3": "ok"}

    monkeypatch.setattr("echoroo.main.check_readiness", _ready)
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok", "s3": "ok"},
    }


@pytest.mark.asyncio
async def test_readiness_endpoint_returns_503_when_not_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _not_ready(session_factory: Any = None) -> tuple[bool, dict[str, str]]:
        return False, {"database": "ok", "redis": "fail", "s3": "ok"}

    monkeypatch.setattr("echoroo.main.check_readiness", _not_ready)
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["redis"] == "fail"
    # No config detail leaks: only the three component keys, values in {ok, fail}.
    assert set(body["checks"]) == {"database", "redis", "s3"}
    assert set(body["checks"].values()) <= {"ok", "fail"}


@pytest.mark.asyncio
async def test_liveness_endpoint_stays_static() -> None:
    """The cheap liveness probe must not gain dependency checks."""
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}
