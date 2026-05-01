"""Unit-level check for FR-092 / FR-093 chain integrity guards.

This test does NOT exercise a real PostgreSQL instance — the full parallel
scale test is staged for T993 (`tests/security/race_conditions/`). What it
enforces here is the *contract* of the writer:

    1. A ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` statement is
       issued BEFORE any SELECT that reads ``prev_hash``.
    2. A ``pg_advisory_xact_lock(<stable 63-bit key>)`` is acquired
       BEFORE the ``prev_hash`` read.
    3. The advisory lock key is deterministic — two independent imports
       of :mod:`echoroo.services.audit_service` yield the same value.

The AsyncSession is fully mocked: we capture every ``execute`` call, then
inspect the rendered SQL text + bound params. KMS is stubbed by
monkeypatching :mod:`echoroo.core.kms` functions so the test stays
hermetic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from echoroo.services import audit_service
from echoroo.services.audit_service import (
    _AUDIT_CHAIN_LOCK_KEY,
    AuditLogService,
)


class _FakeResult:
    """Minimal stand-in for SQLAlchemy ``Result`` returning a single row."""

    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def first(self) -> tuple[Any, ...] | None:
        return self._row


def _stub_kms(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the KMS-dependent helpers with deterministic stubs."""
    monkeypatch.setattr(
        audit_service, "compute_pii_hash", lambda _v: "a" * 64, raising=True
    )
    monkeypatch.setattr(
        audit_service, "compute_audit_chain_hash", lambda _p, _c: "b" * 64, raising=True
    )


def _make_session(inserted_id: UUID) -> tuple[MagicMock, list[Any]]:
    """Return a mock AsyncSession + the list that captures execute calls."""
    calls: list[Any] = []
    session = MagicMock()

    async def execute(stmt: Any, params: Any = None) -> _FakeResult:
        calls.append((stmt, params))
        text = str(stmt).lower()
        # SELECT row_hash branch → return genesis prev_hash
        if "row_hash from" in text and "order by" in text:
            return _FakeResult(("0" * 64,))
        # RETURNING id branch → return a fresh UUID row
        if "insert into" in text:
            return _FakeResult((inserted_id,))
        # advisory lock / set transaction → no row expected
        return _FakeResult(None)

    session.execute = AsyncMock(side_effect=execute)
    return session, calls


@pytest.mark.asyncio
async def test_write_project_event_sets_serializable_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_kms(monkeypatch)
    expected_id = uuid4()
    session, calls = _make_session(expected_id)
    service = AuditLogService(session)

    project_id = uuid4()
    returned_id = await service.write_project_event(
        actor_user_id=uuid4(),
        project_id=project_id,
        action="project.member_added",
        request_id="req-123",
        ip="203.0.113.9",
        user_agent="pytest",
        detail={"role": "member"},
    )
    assert returned_id == expected_id

    rendered = [str(stmt).lower() for stmt, _ in calls]
    # First call must be the isolation level statement.
    assert any("isolation level serializable" in sql for sql in rendered), rendered
    # The isolation statement must come BEFORE any row_hash SELECT or INSERT.
    iso_idx = next(
        i for i, sql in enumerate(rendered) if "isolation level serializable" in sql
    )
    read_idx = next(i for i, sql in enumerate(rendered) if "row_hash from" in sql)
    insert_idx = next(i for i, sql in enumerate(rendered) if "insert into project_audit_log" in sql)
    assert iso_idx < read_idx < insert_idx


@pytest.mark.asyncio
async def test_write_project_event_takes_advisory_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_kms(monkeypatch)
    session, calls = _make_session(uuid4())
    service = AuditLogService(session)

    await service.write_project_event(
        actor_user_id=uuid4(),
        project_id=uuid4(),
        action="project.toggle_changed",
        request_id="req-xyz",
        ip="203.0.113.9",
        user_agent="pytest",
    )

    # The advisory-lock SELECT must be present and must use the canonical key.
    lock_calls = [
        (stmt, params)
        for stmt, params in calls
        if "pg_advisory_xact_lock" in str(stmt).lower()
    ]
    assert len(lock_calls) == 1, "expected exactly one advisory lock"
    lock_stmt, explicit_params = lock_calls[0]
    # ``bindparams(key=...)`` embeds the value onto the TextClause; the
    # service does not pass a separate ``params`` kwarg. We therefore
    # inspect either source of the value.
    bound = {bp.key: bp.value for bp in getattr(lock_stmt, "_bindparams", {}).values()}
    key_value = bound.get("key") if not explicit_params else explicit_params.get("key")
    assert key_value == _AUDIT_CHAIN_LOCK_KEY

    # Lock must come BEFORE the prev_hash read.
    rendered = [str(stmt).lower() for stmt, _ in calls]
    lock_idx = next(i for i, sql in enumerate(rendered) if "pg_advisory_xact_lock" in sql)
    read_idx = next(i for i, sql in enumerate(rendered) if "row_hash from" in sql)
    assert lock_idx < read_idx


@pytest.mark.asyncio
async def test_write_platform_event_uses_platform_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_kms(monkeypatch)
    session, calls = _make_session(uuid4())
    service = AuditLogService(session)

    await service.write_platform_event(
        actor_user_id=uuid4(),
        action="auth.login",
        request_id="req-login",
        ip="198.51.100.4",
        user_agent="pytest",
        detail={"outcome": "success"},
    )
    rendered = [str(stmt).lower() for stmt, _ in calls]
    assert any("insert into platform_audit_log" in sql for sql in rendered)
    # platform_audit_log has no project_id column — ensure we never emit one.
    for sql in rendered:
        if "insert into platform_audit_log" in sql:
            assert "project_id" not in sql


def test_advisory_lock_key_is_stable_and_in_signed_bigint_range() -> None:
    # 63-bit max (signed bigint positive half).
    assert 0 <= _AUDIT_CHAIN_LOCK_KEY <= 0x7FFFFFFFFFFFFFFF

    # Re-importing the module must produce the same constant; the folding
    # is deterministic (SHA-256 truncation).
    import importlib

    reloaded = importlib.reload(audit_service)
    assert reloaded._AUDIT_CHAIN_LOCK_KEY == _AUDIT_CHAIN_LOCK_KEY
