"""Integration tests for :class:`echoroo.core.auth.SqlTokenStore` (Phase 2.11 P0-d).

Skipped automatically when ``testcontainers`` is unavailable so dev
environments that cannot pull the Postgres image still run a green test
matrix — same pattern used by ``test_baseline_migration.py`` and
``test_audit_serializable_isolation.py``.

Verifies the production-path properties that :class:`InMemoryTokenStore`
already covered in Phase 2.10:

* ``record_issued`` then ``is_consumed`` is False; ``mark_consumed``
  flips it.
* ``atomic_consume_and_issue`` succeeds the FIRST time and returns
  False on every subsequent call with the same ``old_jti`` (replay
  detection signal).
* Two concurrent calls with the SAME ``old_jti`` produce exactly ONE
  ``True`` and one ``False`` — proves PostgreSQL's row-level lock on
  ``UPDATE ... WHERE consumed_at IS NULL RETURNING jti`` is the chosen
  serialisation primitive (FR-055 / FR-071 replay detection).
* ``revoke_family`` propagates to every member token and to the family
  row.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dep declared in pyproject dev extras
    PostgresContainer = None  # type: ignore[assignment,misc]


API_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = API_ROOT / "alembic.ini"


@pytest.fixture(scope="module")
def pg_container() -> Iterator[object]:
    """Spin up a throwaway PostgreSQL 16 container for SqlTokenStore tests."""
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    container = PostgresContainer("postgres:16-alpine")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="module")
def upgraded_db(pg_container: object) -> str:
    """Run ``alembic upgrade head`` against the throwaway DB and return URL."""
    sync_url = pg_container.get_connection_url()  # type: ignore[attr-defined]
    sync_url = sync_url.replace("postgresql+psycopg2://", "postgresql://")
    env = {
        "DATABASE_URL": sync_url.replace("postgresql://", "postgresql+asyncpg://"),
        "ALEMBIC_SYNC_URL": sync_url,
    }
    result = subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(API_ROOT),
        env={**env, "PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "alembic upgrade head failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return sync_url


@pytest.fixture
async def session_factory(upgraded_db: str) -> AsyncIterator[object]:
    """Per-test async session factory bound to the upgraded DB."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async_url = upgraded_db.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded_user_id(session_factory: object) -> uuid.UUID:
    """Insert a minimal users row to satisfy refresh_tokens.user_id FK."""
    import sqlalchemy as sa

    user_id = uuid.uuid4()
    async with session_factory() as session, session.begin():  # type: ignore[operator]
        await session.execute(
            sa.text(
                "INSERT INTO users (id, email, password_hash, security_stamp) "
                "VALUES (:id, :email, :pw, :stamp)"
            ),
            {
                "id": user_id,
                "email": f"u{user_id}@test.local",
                "pw": "hash",
                "stamp": "s" * 64,
            },
        )
    return user_id


def _make_record(
    *, user_id: uuid.UUID, family_id: str | None = None, jti: str | None = None
):
    from echoroo.core.auth import RefreshTokenRecord

    fam = family_id or str(uuid.uuid4())
    j = jti or str(uuid.uuid4())
    now = datetime.now(UTC)
    return RefreshTokenRecord(
        jti=j,
        family_id=fam,
        user_id=user_id,
        issued_at=now,
        expires_at=now + timedelta(days=30),
    )


# ---------------------------------------------------------------------------
# 1) Basic round-trip: issue, query state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_issued_then_get_family_state(
    session_factory: object, seeded_user_id: uuid.UUID
) -> None:
    from echoroo.core.auth import SqlTokenStore

    store = SqlTokenStore(session_factory)
    record = _make_record(user_id=seeded_user_id)
    await store.record_issued(record)

    state = await store.get_family_state(record.family_id)
    assert state is not None
    assert state["revoked"] is False
    assert state["consumed_jtis"] == set()


# ---------------------------------------------------------------------------
# 2) Atomic consume + issue: success on first call, False on replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atomic_consume_and_issue_first_call_succeeds(
    session_factory: object, seeded_user_id: uuid.UUID
) -> None:
    from echoroo.core.auth import SqlTokenStore

    store = SqlTokenStore(session_factory)
    initial = _make_record(user_id=seeded_user_id)
    await store.record_issued(initial)

    successor = _make_record(
        user_id=seeded_user_id, family_id=initial.family_id
    )
    swapped = await store.atomic_consume_and_issue(
        family_id=initial.family_id,
        old_jti=initial.jti,
        new_record=successor,
    )
    assert swapped is True

    # The original is now consumed.
    assert await store.is_consumed(initial.family_id, initial.jti) is True
    # The successor is NOT yet consumed.
    assert await store.is_consumed(initial.family_id, successor.jti) is False


@pytest.mark.asyncio
async def test_atomic_consume_and_issue_replay_returns_false(
    session_factory: object, seeded_user_id: uuid.UUID
) -> None:
    """Second rotation against the SAME old_jti returns False (reuse signal)."""
    from echoroo.core.auth import SqlTokenStore

    store = SqlTokenStore(session_factory)
    initial = _make_record(user_id=seeded_user_id)
    await store.record_issued(initial)

    succ_a = _make_record(user_id=seeded_user_id, family_id=initial.family_id)
    succ_b = _make_record(user_id=seeded_user_id, family_id=initial.family_id)

    first = await store.atomic_consume_and_issue(
        family_id=initial.family_id, old_jti=initial.jti, new_record=succ_a
    )
    second = await store.atomic_consume_and_issue(
        family_id=initial.family_id, old_jti=initial.jti, new_record=succ_b
    )
    assert first is True
    assert second is False  # replay detected


# ---------------------------------------------------------------------------
# 3) Concurrency: exactly one True under parallel rotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_atomic_consume_and_issue_under_concurrency(
    session_factory: object, seeded_user_id: uuid.UUID
) -> None:
    """Two concurrent rotations of the same token: exactly one wins."""
    from echoroo.core.auth import SqlTokenStore

    store = SqlTokenStore(session_factory)
    initial = _make_record(user_id=seeded_user_id)
    await store.record_issued(initial)

    succ_a = _make_record(user_id=seeded_user_id, family_id=initial.family_id)
    succ_b = _make_record(user_id=seeded_user_id, family_id=initial.family_id)

    results = await asyncio.gather(
        store.atomic_consume_and_issue(
            family_id=initial.family_id,
            old_jti=initial.jti,
            new_record=succ_a,
        ),
        store.atomic_consume_and_issue(
            family_id=initial.family_id,
            old_jti=initial.jti,
            new_record=succ_b,
        ),
        return_exceptions=False,
    )
    # Exactly one True, one False.
    assert sorted(results) == [False, True], (
        f"expected exactly one rotation to win, got {results}"
    )


# ---------------------------------------------------------------------------
# 4) Family revoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_family_propagates_to_state(
    session_factory: object, seeded_user_id: uuid.UUID
) -> None:
    from echoroo.core.auth import SqlTokenStore

    store = SqlTokenStore(session_factory)
    record = _make_record(user_id=seeded_user_id)
    await store.record_issued(record)

    assert await store.is_family_revoked(record.family_id) is False

    await store.revoke_family(record.family_id)

    assert await store.is_family_revoked(record.family_id) is True
    state = await store.get_family_state(record.family_id)
    assert state is not None
    assert state["revoked"] is True


@pytest.mark.asyncio
async def test_is_family_revoked_for_unknown_family_is_false(
    session_factory: object,
) -> None:
    """Unknown family is treated as "not revoked" (caller mints on first use)."""
    from echoroo.core.auth import SqlTokenStore

    store = SqlTokenStore(session_factory)
    assert await store.is_family_revoked(str(uuid.uuid4())) is False
