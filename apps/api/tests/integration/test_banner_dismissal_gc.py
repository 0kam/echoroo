"""Integration tests for the banner-dismissal GC worker (spec/011 T625).

Exercises :func:`echoroo.workers.banner_gc._impl` against the real Postgres
test database:

* Dismissals at 29 days → kept (within cap).
* Dismissals at 31 days → deleted (beyond cap).
* Boundary at exactly DEFAULT_BANNER_MAX_AGE_DAYS days → kept (strict ``<``).
* The cutoff is aligned with ``DEFAULT_BANNER_MAX_AGE_DAYS`` from the service.
* Re-running the task on a clean dataset is a no-op (idempotency).

The worker uses ``AsyncSessionLocal`` internally.  We monkeypatch that binding
onto a NullPool session-maker bound to ``TEST_DATABASE_URL`` so the DELETE
lands in the same test database rather than the production engine.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

import echoroo.workers.banner_gc as gc_mod
from echoroo.services.user_banner import DEFAULT_BANNER_MAX_AGE_DAYS
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def gc_session_maker(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Rebind ``AsyncSessionLocal`` in banner_gc onto the test engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(gc_mod, "AsyncSessionLocal", maker, raising=True)
    yield maker
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession) -> UUID:
    uid = uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO users (id, email, password_hash, security_stamp) "
            "VALUES (:id, :email, 'x', :stamp)"
        ),
        {
            "id": str(uid),
            "email": f"gc-user-{uid}@example.com",
            "stamp": "s" * 64,
        },
    )
    return uid


async def _insert_dismissal(
    session: AsyncSession,
    *,
    user_id: UUID,
    dismissed_at: datetime,
) -> UUID:
    """Insert a user_banner_dismissals row with an explicit dismissed_at."""
    audit_log_id = uuid4()
    await session.execute(
        sa.text(
            """
            INSERT INTO user_banner_dismissals
              (user_id, audit_table, audit_log_id, dismissed_at)
            VALUES
              (:uid, 'platform_audit_log', :lid, :dismissed)
            """
        ),
        {
            "uid": str(user_id),
            "lid": str(audit_log_id),
            "dismissed": dismissed_at,
        },
    )
    return audit_log_id


async def _count_dismissal(
    session: AsyncSession,
    *,
    user_id: UUID,
    audit_log_id: UUID,
) -> int:
    """Return 1 if the dismissal row exists, 0 otherwise."""
    result = await session.execute(
        sa.text(
            "SELECT COUNT(*) FROM user_banner_dismissals "
            "WHERE user_id = :uid AND audit_log_id = :lid"
        ),
        {"uid": str(user_id), "lid": str(audit_log_id)},
    )
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_gc_deletes_31day_dismissal_keeps_29day(
    db_session: AsyncSession,
    gc_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """31-day-old dismissal is deleted; 29-day-old dismissal is kept."""
    user_id = await _create_user(db_session)
    await db_session.commit()

    now = datetime.now(UTC)
    old_dismissed = now - timedelta(days=DEFAULT_BANNER_MAX_AGE_DAYS + 1)
    young_dismissed = now - timedelta(days=DEFAULT_BANNER_MAX_AGE_DAYS - 1)

    async with gc_session_maker() as session:
        old_lid = await _insert_dismissal(
            session, user_id=user_id, dismissed_at=old_dismissed
        )
        young_lid = await _insert_dismissal(
            session, user_id=user_id, dismissed_at=young_dismissed
        )
        await session.commit()

    result = await gc_mod._impl(now=now)
    assert result["deleted"] >= 1

    async with gc_session_maker() as session:
        assert await _count_dismissal(session, user_id=user_id, audit_log_id=old_lid) == 0, (
            "31-day-old dismissal must be deleted"
        )
        assert await _count_dismissal(session, user_id=user_id, audit_log_id=young_lid) == 1, (
            "29-day-old dismissal must be kept"
        )


async def test_gc_respects_strict_less_than_boundary(
    db_session: AsyncSession,
    gc_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Exactly DEFAULT_BANNER_MAX_AGE_DAYS old → kept (SQL uses strict ``<``).

    The GC SQL is ``WHERE dismissed_at < :cutoff``. A row dismissed exactly
    at the cutoff (``now - MAX_AGE_DAYS``) is NOT strictly less than the
    cutoff, so it must be retained.
    """
    user_id = await _create_user(db_session)
    await db_session.commit()

    now = datetime.now(UTC)
    cutoff = now - timedelta(days=DEFAULT_BANNER_MAX_AGE_DAYS)

    async with gc_session_maker() as session:
        # Exactly at the boundary
        exact_lid = await _insert_dismissal(
            session, user_id=user_id, dismissed_at=cutoff
        )
        # One microsecond older than the boundary → must be deleted
        just_past_lid = await _insert_dismissal(
            session,
            user_id=user_id,
            dismissed_at=cutoff - timedelta(microseconds=1),
        )
        await session.commit()

    await gc_mod._impl(now=now)

    async with gc_session_maker() as session:
        assert await _count_dismissal(session, user_id=user_id, audit_log_id=exact_lid) == 1, (
            "dismissal exactly at cutoff must NOT be deleted (strict <)"
        )
        assert await _count_dismissal(session, user_id=user_id, audit_log_id=just_past_lid) == 0, (
            "dismissal one microsecond past cutoff must be deleted"
        )


async def test_gc_cutoff_aligns_with_default_banner_max_age_days(
    db_session: AsyncSession,
    gc_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """GC cutoff uses DEFAULT_BANNER_MAX_AGE_DAYS — not a hardcoded literal.

    Run _impl with a controlled ``now`` and verify only rows older than
    DEFAULT_BANNER_MAX_AGE_DAYS from that ``now`` are deleted.  This
    assertion would catch a drift if banner_gc.py stopped importing the
    constant and used a different number.
    """
    user_id = await _create_user(db_session)
    await db_session.commit()

    # Use a fake "now" far in the future to exercise the constant unambiguously.
    fake_now = datetime(2030, 1, 1, tzinfo=UTC)
    expected_cutoff = fake_now - timedelta(days=DEFAULT_BANNER_MAX_AGE_DAYS)

    # Insert one row just before the cutoff (kept) and one just after (deleted).
    async with gc_session_maker() as session:
        kept_lid = await _insert_dismissal(
            session,
            user_id=user_id,
            dismissed_at=expected_cutoff + timedelta(seconds=1),  # not yet past
        )
        deleted_lid = await _insert_dismissal(
            session,
            user_id=user_id,
            dismissed_at=expected_cutoff - timedelta(seconds=1),  # just past
        )
        await session.commit()

    result = await gc_mod._impl(now=fake_now)

    async with gc_session_maker() as session:
        assert await _count_dismissal(session, user_id=user_id, audit_log_id=kept_lid) == 1
        assert await _count_dismissal(session, user_id=user_id, audit_log_id=deleted_lid) == 0

    assert result["status"] == "ok"
    assert result["deleted"] >= 1


async def test_gc_idempotent_no_eligible_rows(
    db_session: AsyncSession,
    gc_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Running GC when no rows are past the cutoff is a no-op (deleted=0)."""
    user_id = await _create_user(db_session)
    await db_session.commit()

    now = datetime.now(UTC)
    async with gc_session_maker() as session:
        # Insert a young dismissal (well within cap).
        await _insert_dismissal(
            session,
            user_id=user_id,
            dismissed_at=now - timedelta(days=1),
        )
        await session.commit()

    result = await gc_mod._impl(now=now)
    assert result["deleted"] == 0
    assert result["status"] == "ok"


async def test_gc_returns_summary_dict(
    db_session: AsyncSession,
    gc_session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """_impl returns a dict with status/deleted/evaluated_at/cutoff keys."""
    result = await gc_mod._impl()
    assert result["status"] == "ok"
    assert isinstance(result["deleted"], int)
    assert "evaluated_at" in result
    assert "cutoff" in result
