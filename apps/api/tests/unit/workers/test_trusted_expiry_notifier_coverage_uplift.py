"""Coverage uplift unit tests for ``echoroo.workers.trusted_expiry_notifier``.

Phase 17 §C easy-win batch 1: covers the FR-088 soft-alert branch in
``_record_notice_audit`` (lines 210-232) and the rollback-on-error path
in ``_run_notify_expiring`` (lines 308-310) plus the Celery-task entry
point (line 347) so the module clears the 85% threshold without touching
production code.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.workers import trusted_expiry_notifier as notifier

pytestmark = pytest.mark.asyncio


class _BoomCtx:
    """Async-context manager whose ``__aenter__`` raises immediately."""

    async def __aenter__(self) -> object:
        raise RuntimeError("session-init failed")

    async def __aexit__(self, *_args: object) -> None:
        return None


class _RecordingSession:
    """Async-session double used to verify rollback() is called."""

    def __init__(self) -> None:
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def execute(self, *_a: Any, **_kw: Any) -> Any:  # pragma: no cover - never used
        raise RuntimeError("unexpected")


async def test_record_notice_audit_swallows_session_init_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The audit helper logs a soft alert when AsyncSessionLocal blows up
    (lines 210-232 outer try/except).
    """
    monkeypatch.setattr(notifier, "AsyncSessionLocal", lambda: _BoomCtx())
    # Should NOT raise — the warning swallows the soft-alert.
    await notifier._record_notice_audit(
        project_id=uuid4(),
        invitation_id=uuid4(),
        user_id=uuid4(),
        expires_at=datetime.now(UTC),
    )


async def test_record_notice_audit_rolls_back_on_inner_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``write_project_event`` raises, the inner try/except issues
    rollback() before the outer except logs the soft alert (lines 227-230).
    """
    inner_session = _RecordingSession()

    class _Ctx:
        async def __aenter__(self) -> _RecordingSession:
            return inner_session

        async def __aexit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(notifier, "AsyncSessionLocal", lambda: _Ctx())
    fake_service = MagicMock()
    fake_service.write_project_event = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(notifier, "AuditLogService", lambda _s: fake_service)

    await notifier._record_notice_audit(
        project_id=uuid4(),
        invitation_id=uuid4(),
        user_id=uuid4(),
        expires_at=datetime.now(UTC),
    )

    inner_session.rollback.assert_awaited_once()


async def test_run_notify_expiring_rolls_back_when_enqueue_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the inner enqueue raises, the session.rollback() path runs
    (lines 308-310).
    """
    in_window_row = {
        "trusted_user_id": uuid4(),
        "invitation_id": uuid4(),
        "project_id": uuid4(),
        "user_id": uuid4(),
        "expires_at": datetime.now(UTC),
        "user_email": "u@example.com",
        "owner_email": "o@example.com",
        "owner_id": uuid4(),
        "project_name": "P",
    }

    class _Result:
        def mappings(self) -> _Result:
            return self

        def all(self) -> list[dict[str, Any]]:
            return [in_window_row]

    class _Session:
        def __init__(self) -> None:
            self.commit = AsyncMock()
            self.rollback = AsyncMock()

        async def execute(self, *_a: Any, **_kw: Any) -> _Result:
            return _Result()

    session = _Session()

    class _Ctx:
        async def __aenter__(self) -> _Session:
            return session

        async def __aexit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(notifier, "AsyncSessionLocal", lambda: _Ctx())
    monkeypatch.setattr(
        notifier.outbox_service,
        "enqueue",
        AsyncMock(side_effect=RuntimeError("enqueue boom")),
    )

    with pytest.raises(RuntimeError):
        await notifier._run_notify_expiring()
    session.rollback.assert_awaited_once()


def test_notify_expiring_trusted_users_invokes_async_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Celery-task entry point delegates to ``asyncio.run(_run_notify_expiring())``
    (line 347).
    """

    async def _fake_runner() -> dict[str, int]:
        return {"notified": 5, "skipped": 1}

    monkeypatch.setattr(notifier, "_run_notify_expiring", _fake_runner)
    # asyncio.run forwards through the real event loop; result must round-trip.
    summary = notifier.notify_expiring_trusted_users()
    assert summary == {"notified": 5, "skipped": 1}
