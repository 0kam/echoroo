"""Coverage uplift unit tests for ``echoroo.core.database``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers the ``get_db`` async generator
body including the rollback branch on exception (lines 51-59), so the module
clears the 85% threshold without touching production code.
"""

from __future__ import annotations

import contextlib
from unittest.mock import patch

import pytest

from echoroo.core import database as mod


class _FakeSession:
    """Instrumented fake AsyncSession for get_db tests."""

    def __init__(self) -> None:
        self.commit_called = False
        self.rollback_called = False
        self.close_called = False

    async def commit(self) -> None:
        self.commit_called = True

    async def rollback(self) -> None:
        self.rollback_called = True

    async def close(self) -> None:
        self.close_called = True


class _FakeAsyncCtx:
    """Fake async context manager that yields a _FakeSession."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *args: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_get_db_yields_session_and_commits() -> None:
    """get_db() yields a session and commits on the happy path (lines 53-54, 59).

    Strategy: patch AsyncSessionLocal so it returns a fake async-context-manager.
    Drive the generator with __anext__() to reach the yield, then asend(None)
    to resume past the yield — that executes ``await session.commit()`` and
    the ``finally`` block's ``await session.close()``.
    """
    session = _FakeSession()
    fake_ctx = _FakeAsyncCtx(session)

    def fake_session_local() -> _FakeAsyncCtx:
        return fake_ctx

    with patch.object(mod, "AsyncSessionLocal", side_effect=fake_session_local):
        gen = mod.get_db()
        yielded = await gen.__anext__()  # runs up to `yield session`
        assert yielded is session

        # Resume the generator: this covers line 54 (commit) + finally (close).
        with contextlib.suppress(StopAsyncIteration):
            await gen.asend(None)  # type: ignore[arg-type]

    assert session.commit_called is True
    assert session.close_called is True
    assert session.rollback_called is False


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_exception() -> None:
    """get_db() rollback path: throwing into the generator covers lines 55-57.

    Strategy: drive to the yield with __anext__(), then use athrow() to inject
    an exception into the generator — this exercises the ``except Exception:``
    branch (rollback) and the ``finally`` block (close).
    """
    session = _FakeSession()
    fake_ctx = _FakeAsyncCtx(session)

    def fake_session_local() -> _FakeAsyncCtx:
        return fake_ctx

    with (
        patch.object(mod, "AsyncSessionLocal", side_effect=fake_session_local),
        pytest.raises(ValueError, match="db error"),
    ):
        gen = mod.get_db()
        await gen.__anext__()  # advance to yield
        # Inject exception — covers except + finally
        await gen.athrow(ValueError("db error"))

    assert session.rollback_called is True
    assert session.close_called is True
    assert session.commit_called is False


def test_db_session_annotation_is_annotated() -> None:
    """DbSession is defined (module-level constant coverage)."""
    assert mod.DbSession is not None


def test_engine_is_created() -> None:
    """engine module-level attribute exists."""
    assert mod.engine is not None


def test_async_session_local_exists() -> None:
    """AsyncSessionLocal module-level attribute exists."""
    assert mod.AsyncSessionLocal is not None
