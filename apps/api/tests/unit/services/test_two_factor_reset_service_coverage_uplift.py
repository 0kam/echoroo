"""Phase 17 §C PR-D coverage uplift — ``echoroo.services.two_factor_reset_service``.

The existing 2FA reset suite exercises the happy path through the
admin endpoints + integration suite. This uplift fills the defensive
branches that are otherwise unreachable from those higher-level
suites:

* :func:`_write_platform_audit` — outer ``except`` swallows
  ``AsyncSessionLocal`` failures and emits the FR-088 soft-alert
  warning. Inner ``rollback`` branch is also exercised.
* :func:`redeem_magic_link` — invalid/expired/used tokens raise
  :class:`MagicLinkInvalidError`.
* :func:`create_request` — duplicate active request raises
  :class:`ActiveResetRequestExistsError`.
* :func:`mark_approved_after_quorum` — no-op when the row is already
  past ``pending_approval``; hard-error when the paired domain row
  is missing entirely.
* :func:`mark_cancelled_after_rejection` — orphaned reject ticket /
  no-op already-past-pending paths both return ``None``.
* :func:`cancel_request` — terminal-row miss returns ``False``;
  successful path returns ``True`` and writes the audit row.

Pure unit tests; the AsyncSession is replaced by an in-process stub.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from echoroo.services import two_factor_reset_service as svc
from echoroo.services.two_factor_reset_service import (
    ActiveResetRequestExistsError,
    MagicLinkInvalidError,
    TwoFactorResetServiceError,
    _write_platform_audit,
    cancel_request,
    mark_approved_after_quorum,
    mark_cancelled_after_rejection,
    redeem_magic_link,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _StubResult:
    """Mirror of SQLAlchemy ``Result`` capturing both ``first`` and
    ``scalar_one_or_none`` paths."""

    def __init__(
        self,
        *,
        first_value: Any = None,
        scalar_value: Any = None,
    ) -> None:
        self._first = first_value
        self._scalar = scalar_value

    def first(self) -> Any:
        return self._first

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _ScriptedSession:
    """Returns a sequence of canned ``_StubResult`` rows from ``execute``.

    Each call to ``execute`` consumes the next entry in ``responses``;
    if exhausted the test fails loudly so unintended SQL is caught.
    """

    def __init__(self, responses: list[_StubResult]) -> None:
        self._responses = list(responses)
        self.commits: int = 0
        self.rollbacks: int = 0
        self.executed_count: int = 0

    async def execute(self, _stmt: Any, _params: Any = None) -> _StubResult:
        self.executed_count += 1
        if not self._responses:
            raise AssertionError("unexpected execute() call beyond scripted responses")
        return self._responses.pop(0)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


# ---------------------------------------------------------------------------
# _write_platform_audit — soft-alert on session-open failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_platform_audit_swallows_session_open_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @asynccontextmanager
    async def _failing_factory() -> Any:
        raise RuntimeError("audit DB unreachable")
        yield None  # pragma: no cover

    with patch.object(svc, "AsyncSessionLocal", _failing_factory), caplog.at_level("WARNING"):
        # MUST NOT raise — soft-alert posture (FR-088).
        await _write_platform_audit(
            actor_user_id=uuid4(),
            action=svc.AUDIT_ACTION_CANCELLED,
            detail={"request_id": str(uuid4())},
        )

    assert any(
        "audit write failed" in record.getMessage() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_write_platform_audit_swallows_inner_failure_via_rollback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rollbacks: list[None] = []

    class _BoomSession:
        async def commit(self) -> None:  # pragma: no cover
            return None

        async def rollback(self) -> None:
            rollbacks.append(None)

        async def __aenter__(self) -> _BoomSession:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

    @asynccontextmanager
    async def _factory() -> Any:
        async with _BoomSession() as s:
            yield s

    class _BoomService:
        def __init__(self, session: Any) -> None:
            self._session = session

        async def write_platform_event(self, **_kwargs: Any) -> None:
            raise RuntimeError("hash-chain prev row missing")

    with (
        patch.object(svc, "AsyncSessionLocal", _factory),
        patch.object(svc, "AuditLogService", _BoomService),
        caplog.at_level("WARNING"),
    ):
        await _write_platform_audit(
            actor_user_id=uuid4(),
            action=svc.AUDIT_ACTION_CANCELLED,
            detail={"request_id": str(uuid4())},
        )

    assert rollbacks == [None]
    assert any(
        "audit write failed" in record.getMessage() for record in caplog.records
    )


# ---------------------------------------------------------------------------
# redeem_magic_link — invalid / expired / used token paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redeem_magic_link_raises_for_unknown_token() -> None:
    """Unknown token hash → atomic UPDATE returns no row → raise."""
    session = _ScriptedSession([_StubResult(first_value=None)])
    with pytest.raises(MagicLinkInvalidError):
        await redeem_magic_link(
            session,  # type: ignore[arg-type]
            raw_token="not-a-real-token",
            now=datetime.now(UTC),
        )


# ---------------------------------------------------------------------------
# mark_approved_after_quorum — no-op + hard-error branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_approved_after_quorum_raises_when_no_paired_row() -> None:
    """No paired domain row at all is a contract violation → raise.

    Drives the path: first execute (UPDATE) returns no row, second
    execute (probe SELECT) also returns no row → raise
    :class:`TwoFactorResetServiceError`.
    """
    session = _ScriptedSession(
        [
            _StubResult(first_value=None),  # UPDATE missed
            _StubResult(scalar_value=None),  # probe SELECT missed
        ]
    )
    with pytest.raises(TwoFactorResetServiceError, match="quorum hook"):
        await mark_approved_after_quorum(
            session,  # type: ignore[arg-type]
            approval_request_id=uuid4(),
            now=datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_mark_approved_after_quorum_logs_noop_when_already_past_pending(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Already past ``pending_approval`` → no-op + warning log + return."""
    existing_row = type(
        "_ExistingRow",
        (),
        {"id": uuid4(), "status": "approved"},
    )()
    session = _ScriptedSession(
        [
            _StubResult(first_value=None),  # UPDATE missed
            _StubResult(scalar_value=existing_row),  # probe SELECT hit
        ]
    )
    with caplog.at_level("WARNING"):
        await mark_approved_after_quorum(
            session,  # type: ignore[arg-type]
            approval_request_id=uuid4(),
            now=datetime.now(UTC),
        )
    assert any(
        "mark_approved_after_quorum no-op" in record.getMessage()
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# mark_cancelled_after_rejection — orphan + no-op return-None paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_cancelled_after_rejection_returns_none_for_orphan(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Orphaned reject ticket (no paired domain row) → log + return ``None``."""
    session = _ScriptedSession(
        [
            _StubResult(first_value=None),  # UPDATE missed
            _StubResult(scalar_value=None),  # probe SELECT missed
        ]
    )
    with caplog.at_level("WARNING"):
        result = await mark_cancelled_after_rejection(
            session,  # type: ignore[arg-type]
            approval_request_id=uuid4(),
            rejector_superuser_id=uuid4(),
            reason="duplicate",
            now=datetime.now(UTC),
        )
    assert result is None
    assert any(
        "orphaned reject ticket" in record.getMessage() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_mark_cancelled_after_rejection_returns_none_for_already_past_pending(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Already past ``pending_approval`` → log + return ``None``."""
    existing_row = type(
        "_ExistingRow",
        (),
        {"id": uuid4(), "status": "cancelled"},
    )()
    session = _ScriptedSession(
        [
            _StubResult(first_value=None),  # UPDATE missed
            _StubResult(scalar_value=existing_row),  # probe SELECT hit
        ]
    )
    with caplog.at_level("INFO"):
        result = await mark_cancelled_after_rejection(
            session,  # type: ignore[arg-type]
            approval_request_id=uuid4(),
            rejector_superuser_id=uuid4(),
            reason="late retry",
            now=datetime.now(UTC),
        )
    assert result is None
    assert any(
        "mark_cancelled_after_rejection no-op" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_mark_cancelled_after_rejection_returns_payload_when_cancelled() -> None:
    """Successful cancel path returns the audit payload dataclass."""
    request_id = uuid4()
    user_id = uuid4()
    superuser_id = uuid4()
    approval_id = uuid4()
    session = _ScriptedSession(
        [
            _StubResult(first_value=(request_id, user_id, superuser_id)),
        ]
    )
    payload = await mark_cancelled_after_rejection(
        session,  # type: ignore[arg-type]
        approval_request_id=approval_id,
        rejector_superuser_id=superuser_id,
        reason="not granted",
        now=datetime.now(UTC),
    )
    assert payload is not None
    assert payload.request_id == request_id
    assert payload.target_user_id == user_id
    assert payload.approval_request_id == approval_id
    assert payload.rejector_superuser_id == superuser_id
    assert payload.rejected_reason_excerpt == "not granted"


# ---------------------------------------------------------------------------
# cancel_request — terminal miss + happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_request_returns_false_when_row_already_terminal() -> None:
    """``UPDATE ... WHERE status IN (...)`` misses → returns ``False``."""
    session = _ScriptedSession([_StubResult(first_value=None)])
    out = await cancel_request(
        session,  # type: ignore[arg-type]
        request_id=uuid4(),
        actor_user_id=uuid4(),
        reason="too late",
    )
    assert out is False
    assert session.commits == 0


@pytest.mark.asyncio
async def test_cancel_request_returns_true_and_writes_audit_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful cancel returns ``True``, commits, and writes a soft-alert audit."""
    request_id = uuid4()
    user_id = uuid4()
    session = _ScriptedSession(
        [_StubResult(first_value=(request_id, user_id))]
    )

    audit_calls: list[dict[str, Any]] = []

    async def _fake_audit(**kwargs: Any) -> None:
        audit_calls.append(kwargs)

    monkeypatch.setattr(svc, "_write_platform_audit", _fake_audit)

    out = await cancel_request(
        session,  # type: ignore[arg-type]
        request_id=request_id,
        actor_user_id=uuid4(),
        reason="superuser asked",
        now=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert out is True
    assert session.commits == 1
    assert len(audit_calls) == 1
    assert audit_calls[0]["action"] == svc.AUDIT_ACTION_CANCELLED
    assert audit_calls[0]["detail"]["request_id"] == str(request_id)
    assert audit_calls[0]["detail"]["target_user_id"] == str(user_id)


# ---------------------------------------------------------------------------
# create_request — duplicate active request raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_request_raises_when_active_request_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An in-flight request → :class:`ActiveResetRequestExistsError`.

    We monkey-patch :func:`consume_confirmation_token` to avoid driving
    the HMAC machinery and :func:`_get_active_request` to return a
    sentinel row directly.
    """
    target_user_id = uuid4()
    target_user = type("U", (), {"id": target_user_id, "email": "x@example.com"})()

    existing = type(
        "_Existing",
        (),
        {"id": uuid4(), "status": "pending_delay"},
    )()

    async def _fake_consume(*_args: Any, **_kwargs: Any) -> Any:
        return type("Payload", (), {"nonce": "nonce-deadbeef"})()

    async def _fake_active(*_args: Any, **_kwargs: Any) -> Any:
        return existing

    monkeypatch.setattr(svc, "consume_confirmation_token", _fake_consume)
    monkeypatch.setattr(svc, "_get_active_request", _fake_active)

    # The execute / commit calls here would belong to the consume / get
    # paths; we've stubbed those out so the session needs no scripted
    # responses.
    session = _ScriptedSession([])
    with pytest.raises(ActiveResetRequestExistsError):
        await svc.create_request(
            session,  # type: ignore[arg-type]
            target_user=target_user,  # type: ignore[arg-type]
            requested_by_superuser_id=uuid4(),
            confirmation_token="opaque-token",
            support_ticket_id="SUP-1",
            reason="lost device",
            skip_delay=False,
        )
