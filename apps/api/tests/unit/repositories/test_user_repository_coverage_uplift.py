"""Coverage uplift unit tests for ``echoroo.repositories.user``.

Phase 17 §C easy-win batch 1: targets the email-lookup result branch
(line 40) plus the create/update flush+refresh paths (lines 76, 87-89)
so the module clears the 85% threshold without touching production code.

Uses :class:`unittest.mock.AsyncMock` for the SQLAlchemy session — the
production code only calls ``execute`` / ``add`` / ``flush`` / ``refresh``
so a thin async-mock surface is sufficient.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.models.user import User
from echoroo.repositories.user import UserRepository


def _make_user(*, email: str = "u@example.com") -> User:
    """Build a minimal User instance suitable for a unit-level repo test."""
    user = User(
        email=email,
        password_hash="$argon2id$dummy",
        display_name="Unit Tester",
        security_stamp="ss-" + email,
    )
    user.id = uuid4()  # type: ignore[assignment]
    return user


@pytest.mark.asyncio
async def test_get_by_email_returns_user_when_present() -> None:
    """get_by_email() returns the User scalar from the SQL result (line 40)."""
    user = _make_user(email="present@example.com")

    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=result)

    repo = UserRepository(db)
    found = await repo.get_by_email("present@example.com")
    assert found is user
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_by_email_returns_none_when_absent() -> None:
    """get_by_email() returns None when no row matches (line 40, falsy branch)."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    repo = UserRepository(db)
    assert await repo.get_by_email("missing@example.com") is None


@pytest.mark.asyncio
async def test_create_calls_add_flush_refresh_and_returns_user() -> None:
    """create() persists the user and returns it (line 76)."""
    user = _make_user()
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = UserRepository(db)
    result = await repo.create(user)
    assert result is user
    db.add.assert_called_once_with(user)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(user)


@pytest.mark.asyncio
async def test_update_flushes_refreshes_and_returns_user() -> None:
    """update() flushes + refreshes + returns the same user (lines 87-89)."""
    user = _make_user()
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()

    repo = UserRepository(db)
    result = await repo.update(user)
    assert result is user
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(user)


@pytest.mark.asyncio
async def test_get_by_id_returns_scalar() -> None:
    """get_by_id() returns the scalar_one_or_none() result."""
    user = _make_user()
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    db.execute = AsyncMock(return_value=result)

    repo = UserRepository(db)
    found = await repo.get_by_id(user.id)
    assert found is user
