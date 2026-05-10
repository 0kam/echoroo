"""Coverage uplift unit tests for ``echoroo.workers.trusted_auto_expire``.

Phase 17 §C heavy-gap batch: targets the helper functions that
``test_trusted_auto_expire.py`` deliberately monkey-patches away —
``_publish_invalidation`` (lines 117, 121-125), ``_record_audit``
(lines 158-183), ``_uuid_from_str`` (lines 199, 201), and the Celery
task wrapper (lines 236-238, 282) so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from echoroo.workers import trusted_auto_expire as worker


@pytest.mark.asyncio
async def test_publish_invalidation_publishes_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_publish_invalidation() builds JSON payload and calls publish (line 117)."""
    fake_client = MagicMock()
    fake_client.publish = AsyncMock(return_value=1)

    async def fake_get_redis_connection() -> MagicMock:
        return fake_client

    monkeypatch.setattr(worker, "get_redis_connection", fake_get_redis_connection)

    user_id = str(uuid4())
    project_id = str(uuid4())
    await worker._publish_invalidation(user_id=user_id, project_id=project_id)
    fake_client.publish.assert_awaited_once()
    args = fake_client.publish.await_args
    assert args.args[0] == worker.TRUSTED_INVALIDATION_CHANNEL
    payload = args.args[1]
    assert user_id in payload
    assert project_id in payload
    assert "expired" in payload


@pytest.mark.asyncio
async def test_publish_invalidation_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_publish_invalidation() swallows publish errors and logs WARNING (lines 121-131)."""

    async def boom() -> Any:
        raise RuntimeError("redis down")

    monkeypatch.setattr(worker, "get_redis_connection", boom)
    # Must NOT raise — best-effort soft alert.
    await worker._publish_invalidation(
        user_id=str(uuid4()), project_id=str(uuid4()),
    )


@pytest.mark.asyncio
async def test_record_audit_skips_when_count_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_record_audit() short-circuits when expired_count is 0 (lines 158-159)."""
    called = {"n": 0}

    class _Sentinel:
        def __init__(self) -> None:
            called["n"] += 1

    monkeypatch.setattr(worker, "AsyncSessionLocal", _Sentinel)
    await worker._record_audit(
        expired_count=0,
        expired_invitation_ids=[],
        project_ids=[],
    )
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_record_audit_writes_single_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_record_audit() writes one batch audit row via AuditLogService (lines 160-181)."""
    write_mock = AsyncMock(return_value=None)

    class _FakeService:
        def __init__(self, session: object) -> None:
            self._session = session

        async def write_project_event(
            self,
            *,
            actor_user_id: Any,
            project_id: Any,
            action: str,
            request_id: str,
            ip: str,
            user_agent: str,
            detail: dict[str, object],
        ) -> None:
            await write_mock(
                actor_user_id=actor_user_id,
                project_id=project_id,
                action=action,
                detail=detail,
            )

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    def session_factory() -> _FakeSession:
        return _FakeSession()

    monkeypatch.setattr(worker, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(worker, "AuditLogService", _FakeService)

    project_a = str(uuid4())
    project_b = str(uuid4())
    invitation_id = str(uuid4())
    await worker._record_audit(
        expired_count=2,
        expired_invitation_ids=[invitation_id],
        project_ids=[project_b, project_a],
    )
    write_mock.assert_awaited_once()
    kwargs = write_mock.await_args.kwargs
    assert kwargs["action"] == worker._AUDIT_ACTION
    # Anchor project should be the lexicographically smallest.
    assert str(kwargs["project_id"]) == sorted([project_a, project_b])[0]
    assert kwargs["detail"]["expired_count"] == 2
    assert invitation_id in kwargs["detail"]["expired_invitation_ids"]


@pytest.mark.asyncio
async def test_record_audit_swallows_audit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_record_audit() swallows write errors and logs WARNING (lines 182-188)."""

    class _BoomSession:
        async def __aenter__(self) -> _BoomSession:
            raise RuntimeError("DB down")

        async def __aexit__(self, *exc: Any) -> bool:
            return False

    monkeypatch.setattr(worker, "AsyncSessionLocal", _BoomSession)
    # Must NOT raise — best-effort soft alert.
    await worker._record_audit(
        expired_count=1,
        expired_invitation_ids=[str(uuid4())],
        project_ids=[str(uuid4())],
    )


def test_uuid_from_str_passes_through_uuid_instance() -> None:
    """_uuid_from_str() returns the original UUID instance (line 199, 201)."""
    u = uuid4()
    assert worker._uuid_from_str(u) is u


def test_uuid_from_str_parses_string() -> None:
    """_uuid_from_str() parses a string into a UUID instance."""
    u = uuid4()
    out = worker._uuid_from_str(str(u))
    assert isinstance(out, UUID)
    assert out == u


def test_auto_expire_trusted_users_celery_task_invokes_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Celery task wrapper runs ``_run_auto_expire`` via asyncio.run (line 282)."""

    async def fake_runner() -> dict[str, int]:
        return {"expired": 4}

    monkeypatch.setattr(worker, "_run_auto_expire", fake_runner)
    out = worker.auto_expire_trusted_users()
    assert out == {"expired": 4}


@pytest.mark.asyncio
async def test_run_auto_expire_rolls_back_on_execute_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_auto_expire() rolls back when the UPDATE raises (lines 236-238)."""

    class _ExplodingSession:
        def __init__(self) -> None:
            self.rollbacks = 0

        async def __aenter__(self) -> _ExplodingSession:
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def execute(self, *_args: Any, **_kw: Any) -> Any:
            raise RuntimeError("boom")

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            self.rollbacks += 1

    session = _ExplodingSession()

    def factory() -> _ExplodingSession:
        return session

    monkeypatch.setattr(worker, "AsyncSessionLocal", factory)
    with pytest.raises(RuntimeError):
        await worker._run_auto_expire()
    assert session.rollbacks == 1
