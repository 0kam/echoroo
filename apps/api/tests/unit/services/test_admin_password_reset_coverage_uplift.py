"""Phase 17 §C / spec/011 coverage uplift — ``echoroo.services.admin_password_reset``.

The integration suite (tests/integration/test_admin_password_reset.py)
exercises the happy path through the HTTP layer and covers most of this
module, but four sets of lines remain uncovered in the full-suite run:

* **Lines 173-178**: ``_write_audit_row`` inner ``except`` block — the
  ``AuditLogService.write_platform_event`` call raises, causing the inner
  ``except`` to roll back the audit session and re-raise; the outer
  ``except`` (line 177) then swallows it and emits the FR-088 soft-alert
  warning.
* **Line 212**: ``_generate_security_stamp`` defensive RuntimeError guard —
  fires when ``secrets.token_urlsafe(48)`` produces a string whose length
  is not 64 (monkeypatched to simulate the impossible case).
* **Line 272**: ``reset_password`` early-exit ``LookupError`` when the
  target user is not found (``session.get`` returns ``None``) or has been
  soft-deleted (``deleted_at`` is not None).
* **Lines 326-331**: ``td_reason`` ternary — the ``_TD_REVOKE_REASON_SELF``
  branch (``actor_id == target_user_id``). Although an integration test for
  self-reset exists, it runs through the full HTTP stack and the coverage
  for this specific branch is missed in the full-suite union.

All tests here are pure unit tests; AsyncSession and external services are
replaced by lightweight stubs so the suite runs without a real DB.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from echoroo.services import admin_password_reset as svc
from echoroo.services.admin_password_reset import (
    _TD_REVOKE_REASON_OPERATOR,  # noqa: PLC2701
    _TD_REVOKE_REASON_SELF,  # noqa: PLC2701
    AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF,
    _generate_security_stamp,  # noqa: PLC2701
    _write_audit_row,  # noqa: PLC2701
    reset_password,
)


# ---------------------------------------------------------------------------
# Helpers / test doubles
# ---------------------------------------------------------------------------


class _FakeUser:
    """Minimal User stand-in for service calls that only read/write fields."""

    def __init__(self, *, user_id: Any, deleted_at: datetime | None = None) -> None:
        self.id = user_id
        self.deleted_at = deleted_at
        self.password_hash: str = "old_hash"
        self.must_change_password: bool = False
        self.temp_password_expires_at: datetime | None = None
        self.updated_at: datetime | None = None
        self.security_stamp: str = "s" * 64


class _StubSession:
    """Minimal AsyncSession stub supporting get / add / flush."""

    def __init__(self, *, get_return: Any = None) -> None:
        self._get_return = get_return
        self.added: list[Any] = []
        self.flushed: int = 0

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._get_return

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1


# ---------------------------------------------------------------------------
# 1. _write_audit_row — inner failure triggers rollback + outer soft-alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_audit_row_swallows_inner_write_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AuditLogService.write_platform_event raising triggers rollback and
    emits the FR-088 soft-alert warning; the exception MUST NOT propagate.

    Covers lines 173-178: the inner ``except`` rollback + re-raise path,
    then the outer ``except`` swallow + logger.warning.
    """
    rollbacks: list[None] = []

    class _FailingAuditSession:
        async def rollback(self) -> None:
            rollbacks.append(None)

        async def __aenter__(self) -> _FailingAuditSession:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

    @asynccontextmanager
    async def _factory() -> Any:
        async with _FailingAuditSession() as s:
            yield s

    class _FailingAuditService:
        def __init__(self, session: Any) -> None:
            pass

        async def write_platform_event(self, **_kw: Any) -> None:
            raise RuntimeError("intentional audit write failure")

    with (
        patch.object(svc, "AsyncSessionLocal", _factory),
        patch.object(svc, "AuditLogService", _FailingAuditService),
        caplog.at_level("WARNING"),
    ):
        # Must NOT raise — soft-alert posture (FR-088).
        await _write_audit_row(
            actor_id=uuid4(),
            action="platform.user.password_reset_by_superuser",
            detail={"target_user_id": str(uuid4()), "reason": None, "self_reset": False},
            request_id="req-123",
            ip="10.0.0.1",
            user_agent="pytest",
        )

    # Rollback was called inside the inner except block (line 175).
    assert rollbacks == [None]
    # Outer except emitted the soft-alert warning (line 178).
    assert any("audit write failed" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# 2. _generate_security_stamp — RuntimeError guard (line 212)
# ---------------------------------------------------------------------------


def test_generate_security_stamp_raises_on_wrong_length() -> None:
    """Simulates the (impossible in practice) case where token_urlsafe(48)
    returns a string of unexpected length; the guard at line 212 must fire.
    """
    with (
        patch("secrets.token_urlsafe", return_value="tooshort"),
        pytest.raises(RuntimeError, match="does not fit users.security_stamp"),
    ):
        _generate_security_stamp()


# ---------------------------------------------------------------------------
# 3. reset_password — LookupError when user not found (line 272)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_password_raises_lookup_error_when_user_not_found() -> None:
    """``session.get`` returns None → LookupError is raised (line 272)."""
    session = _StubSession(get_return=None)
    target_id = uuid4()

    with pytest.raises(LookupError, match=str(target_id)):
        await reset_password(
            session,  # type: ignore[arg-type]
            actor_id=uuid4(),
            target_user_id=target_id,
            reason=None,
        )


@pytest.mark.asyncio
async def test_reset_password_raises_lookup_error_when_user_soft_deleted() -> None:
    """A user with ``deleted_at`` set is treated as not found (line 272)."""
    deleted_user = _FakeUser(
        user_id=uuid4(),
        deleted_at=datetime.now(UTC) - timedelta(days=1),
    )
    session = _StubSession(get_return=deleted_user)

    with pytest.raises(LookupError, match=str(deleted_user.id)):
        await reset_password(
            session,  # type: ignore[arg-type]
            actor_id=uuid4(),
            target_user_id=deleted_user.id,
            reason=None,
        )


# ---------------------------------------------------------------------------
# 4. reset_password — self-reset td_reason branch (lines 326-331)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_password_self_reset_uses_self_td_reason() -> None:
    """When actor_id == target_user_id, td_reason is _TD_REVOKE_REASON_SELF
    and the self-reset audit action is emitted (lines 326-331 + audit action).

    TrustedDeviceService and _write_audit_row are both stubbed so no DB
    is required.
    """
    shared_id = uuid4()
    user = _FakeUser(user_id=shared_id)
    session = _StubSession(get_return=user)

    captured_td_reason: list[str] = []
    captured_audit_action: list[str] = []

    class _StubTrustedDeviceService:
        def __init__(self, _session: Any) -> None:
            pass

        async def revoke_all_for_user(
            self, *, user: Any, reason: str, actor_user_id: Any
        ) -> int:
            captured_td_reason.append(reason)
            return 0

    async def _fake_write_audit_row(**kwargs: Any) -> None:
        captured_audit_action.append(kwargs["action"])

    with (
        patch.object(svc, "TrustedDeviceService", _StubTrustedDeviceService),
        patch.object(svc, "_write_audit_row", _fake_write_audit_row),
    ):
        temp_pw = await reset_password(
            session,  # type: ignore[arg-type]
            actor_id=shared_id,
            target_user_id=shared_id,
            reason="self-test",
        )

    # The temporary password is a non-trivial URL-safe string.
    assert len(temp_pw) >= 20

    # The self-reset branch selected _TD_REVOKE_REASON_SELF (line 327).
    assert captured_td_reason == [_TD_REVOKE_REASON_SELF]
    assert _TD_REVOKE_REASON_OPERATOR not in captured_td_reason

    # The self-reset audit action was chosen (FR-011-210).
    assert captured_audit_action == [AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF]


@pytest.mark.asyncio
async def test_reset_password_operator_reset_uses_operator_td_reason() -> None:
    """When actor_id != target_user_id, td_reason is _TD_REVOKE_REASON_OPERATOR
    (lines 329-330) and the by-superuser audit action is emitted.
    """
    actor_id = uuid4()
    target_id = uuid4()
    user = _FakeUser(user_id=target_id)
    session = _StubSession(get_return=user)

    captured_td_reason: list[str] = []

    class _StubTrustedDeviceService:
        def __init__(self, _session: Any) -> None:
            pass

        async def revoke_all_for_user(
            self, *, user: Any, reason: str, actor_user_id: Any
        ) -> int:
            captured_td_reason.append(reason)
            return 0

    async def _fake_write_audit_row(**kwargs: Any) -> None:
        pass

    with (
        patch.object(svc, "TrustedDeviceService", _StubTrustedDeviceService),
        patch.object(svc, "_write_audit_row", _fake_write_audit_row),
    ):
        await reset_password(
            session,  # type: ignore[arg-type]
            actor_id=actor_id,
            target_user_id=target_id,
            reason=None,
        )

    assert captured_td_reason == [_TD_REVOKE_REASON_OPERATOR]
