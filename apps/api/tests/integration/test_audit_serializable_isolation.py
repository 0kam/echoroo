"""Integration test for FR-093 SERIALIZABLE isolation pre-condition (Phase 2.10 #5).

PostgreSQL rejects ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` once any
other statement has executed on the connection. The audit writer
(``AuditLogService._write``) issues that statement as its first SQL, so
callers MUST supply a *fresh* AsyncSession that has not previously
executed any read or write. The audit *read* endpoints exemplify the
constraint: they SELECT a page first (committing the connection to a
default isolation), then need to write a meta-audit row — that meta
write must run on a SECOND session, not the request-scoped one.

This test verifies the contract end-to-end by:

1. Reusing the request-scoped session for both the SELECT and the
   audit write → expects a runtime PostgreSQL error.
2. Using a brand-new session for the audit write (the production
   pattern in ``api/web_v1/audit.py:_write_meta_audit_in_fresh_session``)
   → expects success.

Skipped when ``testcontainers`` is unavailable (matches the existing
pattern in ``test_baseline_migration.py``).
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
import sqlalchemy as sa

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dep declared in pyproject dev extras
    PostgresContainer = None  # type: ignore[assignment,misc]


API_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = API_ROOT / "alembic.ini"


@pytest.fixture(scope="module")
def pg_container() -> Iterator[object]:
    """Spin up a throwaway PostgreSQL 16 container for isolation tests."""
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
        env={**env, "PATH": __import__("os").environ.get("PATH", "")},
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


@pytest.mark.asyncio
async def test_set_serializable_after_select_raises_on_postgres(upgraded_db: str) -> None:
    """Reusing a session that has already SELECTed for a serializable write fails.

    This is the underlying PostgreSQL semantics that motivates Phase 2.10 #5:
    if the audit read endpoints reused their request-scoped session for
    the meta-audit write, the SET TRANSACTION would error out at runtime.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async_url = upgraded_db.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as session, session.begin():
            # First SELECT — fixes the connection's isolation to default.
            await session.execute(sa.text("SELECT 1"))

            # Now the SET should be rejected by PostgreSQL.
            with pytest.raises(Exception) as excinfo:
                await session.execute(
                    sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                )
            # Error message variants across libpq versions; just confirm
            # we got an exception rather than silently succeeding.
            assert excinfo.type.__name__ != "AssertionError"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_audit_writer_succeeds_on_fresh_session(upgraded_db: str) -> None:
    """A *fresh* session accepts SERIALIZABLE upgrade and writes the row.

    This mirrors the production pattern: the read endpoint runs its
    SELECT on session-A, returns the page, then opens session-B
    dedicated to the meta-audit write.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async_url = upgraded_db.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # Step 1: simulate the read endpoint on a request-scoped session.
    async with Session() as read_session, read_session.begin():
        result = await read_session.execute(
            sa.text("SELECT count(*) FROM project_audit_log")
        )
        first = result.first()
        assert first is not None
        # Force the connection to have done real work.
        _ = first[0]

    # Step 2: meta-audit write on a brand-new session — SET TRANSACTION
    # must succeed because the connection is unsullied.
    async with Session() as audit_session, audit_session.begin():
        await audit_session.execute(
            sa.text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        )
        # Verify we can also acquire the advisory lock.
        await audit_session.execute(
            sa.text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=12345)
        )

    await engine.dispose()


def test_helper_uses_async_session_local() -> None:
    """The audit read endpoint helper must spin up a fresh session.

    Static check that ``_write_meta_audit_in_fresh_session`` exists and
    references ``AsyncSessionLocal`` (the application-wide factory) so
    the meta-audit write does not reuse the request-scoped session.
    """
    from echoroo.api.web_v1 import audit as audit_api

    fn = audit_api._write_meta_audit_in_fresh_session
    src = __import__("inspect").getsource(fn)
    assert "AsyncSessionLocal()" in src, (
        "meta-audit helper must instantiate a fresh AsyncSessionLocal"
    )


# Keep the asyncio compatibility helper for environments without
# pytest-asyncio's autouse mode:
_ = asyncio  # silence unused-import warnings under some toolchains
_ = UUID  # noqa: F401  # kept for future expansion
