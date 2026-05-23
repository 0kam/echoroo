"""Integration test for Alembic revision 0022 (spec/011 step 11 / T701).

Spec/011 T701 requires that the destructive ``0022_email_subsystem_
removal`` migration:

1. Runs cleanly against a DB that has already received ``0021``
   (i.e. ``alembic_version`` row = ``0021``).
2. Drops the ``email_verification_tokens`` table (FR-011-002).
3. Drops the ``password_reset_tokens`` table (FR-011-003).
4. Drops the ``users.email_verified_at`` column (FR-011-002).
5. Does NOT drop ``trusted_devices`` (HANDOFF.md line 73 — out of
   scope).
6. Does NOT touch the additive surface introduced by ``0021``
   (``users.must_change_password``, ``user_banner_dismissals`` etc.).
7. Leaves ``alembic_version`` advanced to ``0022``.
8. ``downgrade()`` raises ``NotImplementedError`` (NFR-011-002).

The test spins up a throwaway PostgreSQL 16 container (pgvector image —
required by ``0001_baseline`` ``CREATE EXTENSION vector``), runs
``alembic upgrade 0021`` to land at the pre-destructive state,
snapshots the schema, runs ``alembic upgrade head`` (which advances by
exactly one revision to 0022), then asserts the post-destructive
state.

The unit-level companion ``tests/unit/test_migration_0022.py``
verifies the migration *intent* via a recording-op fake — that test
gives a fast container-free signal. This integration test gives the
real-SQL signal demanded by T701.

Skipped when ``testcontainers`` (or the docker socket it needs) is
unavailable — mirrors the existing ``test_baseline_migration.py`` /
``test_alembic_r3_parity.py`` conventions.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dep declared in pyproject dev extras
    PostgresContainer = None  # type: ignore[assignment,misc]


API_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = API_ROOT / "alembic.ini"


# ---------------------------------------------------------------------------
# Container fixture — one PostgreSQL 16 container per test module.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_container() -> Iterator[PostgresContainer]:
    """Spin up a throwaway PostgreSQL 16 container."""

    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")

    # pgvector image — required by 0001_baseline ``CREATE EXTENSION vector``.
    # Both construction and ``.start()`` can probe the docker socket and
    # raise ``docker.errors.DockerException`` when the socket is missing
    # (sandboxed CI / docker-in-docker not configured). Skip in that
    # case — this mirrors the existing pattern in
    # ``test_audit_serializable_isolation.py``.
    try:
        container = PostgresContainer("pgvector/pgvector:pg16")
        container.start()
    except Exception as exc:  # pragma: no cover - docker socket missing
        pytest.skip(f"docker / testcontainers unavailable: {exc!r}")
    try:
        yield container
    finally:
        container.stop()


def _admin_sync_url(container: PostgresContainer) -> str:
    """Return a sync (psycopg2-free) admin URL for the container."""

    sync_url = container.get_connection_url()  # postgresql+psycopg2://...
    return sync_url.replace("postgresql+psycopg2://", "postgresql://")


def _alembic_upgrade(sync_url: str, target: str) -> None:
    """Invoke ``alembic upgrade <target>`` against the given sync URL.

    Mirrors the pattern in ``test_alembic_r3_parity.py``: ``python -m
    alembic`` against the current interpreter (avoids ``uv run`` which
    may collide with bind-mounted venvs).
    """

    async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")
    # spec/011 NFR-011-010: Settings validator refuses an empty
    # invitation-token kid / HMAC at every boot, so the subprocess that
    # loads echoroo.core.settings via alembic env.py must carry both
    # values too. We honour any host-side override (so a CI job that
    # already sets these values keeps using them) but otherwise inject
    # the same test fixtures used by ``test_baseline_migration.py``.
    env = {
        **os.environ,
        "DATABASE_URL": async_url,
        "ALEMBIC_SYNC_URL": sync_url,
        "INVITATION_TOKEN_KID_NEW": os.environ.get(
            "INVITATION_TOKEN_KID_NEW"
        )
        or "test-kid",
        "INVITATION_TOKEN_HMAC_KEY": os.environ.get(
            "INVITATION_TOKEN_HMAC_KEY"
        )
        or "test-invitation-hmac-key-32-chars-min-padding-xxxxxxxx",
    }
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_INI),
            "upgrade",
            target,
        ],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"alembic upgrade {target} failed against {sync_url}.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Schema introspection helpers.
# ---------------------------------------------------------------------------


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
            ).scalars()
            return set(rows)
    finally:
        engine.dispose()


def _user_columns(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'users'"
                )
            ).scalars()
            return set(rows)
    finally:
        engine.dispose()


def _alembic_version(url: str) -> str:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# The DB fixture: upgrade to 0021, capture pre-state, upgrade to head.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def migration_state(pg_container: PostgresContainer) -> dict[str, object]:
    """Drive the DB through ``0021 → head`` and capture pre/post state.

    Returns a dict with ``pre_tables``, ``pre_user_columns``,
    ``pre_version``, ``post_tables``, ``post_user_columns``,
    ``post_version`` — the assertions below consume this.
    """

    admin = _admin_sync_url(pg_container)
    # testcontainers default DB name is 'test' — reuse it; the container
    # is single-use for this module so isolation is not a concern.
    url = admin

    # Step 1: drive the DB up to 0021 (the pre-destructive state).
    _alembic_upgrade(url, "0021")
    pre_version = _alembic_version(url)
    pre_tables = _tables(url)
    pre_user_columns = _user_columns(url)

    # Step 2: drive the DB up to head (which advances by exactly one
    # revision to 0022 — this is the migration under test).
    _alembic_upgrade(url, "head")
    post_version = _alembic_version(url)
    post_tables = _tables(url)
    post_user_columns = _user_columns(url)

    return {
        "pre_tables": pre_tables,
        "pre_user_columns": pre_user_columns,
        "pre_version": pre_version,
        "post_tables": post_tables,
        "post_user_columns": post_user_columns,
        "post_version": post_version,
    }


# ---------------------------------------------------------------------------
# Pre-state assertions — the 0021 baseline.
# ---------------------------------------------------------------------------


def test_pre_state_has_email_verification_tokens_table(
    migration_state: dict[str, object],
) -> None:
    pre_tables = migration_state["pre_tables"]
    assert isinstance(pre_tables, set)
    assert "email_verification_tokens" in pre_tables


def test_pre_state_has_password_reset_tokens_table(
    migration_state: dict[str, object],
) -> None:
    pre_tables = migration_state["pre_tables"]
    assert isinstance(pre_tables, set)
    assert "password_reset_tokens" in pre_tables


def test_pre_state_has_email_verified_at_column(
    migration_state: dict[str, object],
) -> None:
    pre_user_columns = migration_state["pre_user_columns"]
    assert isinstance(pre_user_columns, set)
    assert "email_verified_at" in pre_user_columns


def test_pre_state_version_is_0021(migration_state: dict[str, object]) -> None:
    assert migration_state["pre_version"] == "0021"


# ---------------------------------------------------------------------------
# Post-state assertions — after 0022 has run.
# ---------------------------------------------------------------------------


def test_post_state_email_verification_tokens_table_dropped(
    migration_state: dict[str, object],
) -> None:
    post_tables = migration_state["post_tables"]
    assert isinstance(post_tables, set)
    assert "email_verification_tokens" not in post_tables


def test_post_state_password_reset_tokens_table_dropped(
    migration_state: dict[str, object],
) -> None:
    post_tables = migration_state["post_tables"]
    assert isinstance(post_tables, set)
    assert "password_reset_tokens" not in post_tables


def test_post_state_email_verified_at_column_dropped(
    migration_state: dict[str, object],
) -> None:
    post_user_columns = migration_state["post_user_columns"]
    assert isinstance(post_user_columns, set)
    assert "email_verified_at" not in post_user_columns


def test_post_state_trusted_devices_table_preserved(
    migration_state: dict[str, object],
) -> None:
    """HANDOFF.md line 73 scopes the destructive surface — trusted_devices
    is intentionally out of scope and MUST survive the migration."""
    post_tables = migration_state["post_tables"]
    assert isinstance(post_tables, set)
    assert "trusted_devices" in post_tables


def test_post_state_0021_additive_surface_preserved(
    migration_state: dict[str, object],
) -> None:
    """The additive ``0021`` surface (``users.must_change_password``,
    ``user_banner_dismissals`` etc.) MUST be untouched by 0022."""
    post_tables = migration_state["post_tables"]
    post_user_columns = migration_state["post_user_columns"]
    assert isinstance(post_tables, set)
    assert isinstance(post_user_columns, set)
    assert "user_banner_dismissals" in post_tables
    assert "must_change_password" in post_user_columns
    assert "temp_password_expires_at" in post_user_columns
    assert "email_change_cooldown_until" in post_user_columns


def test_post_state_version_advanced_to_0022(
    migration_state: dict[str, object],
) -> None:
    assert migration_state["post_version"] == "0022"


# ---------------------------------------------------------------------------
# Forward-only invariant — exercises the module directly without a DB.
# ---------------------------------------------------------------------------


def test_downgrade_raises_not_implemented() -> None:
    """spec/011 NFR-011-002 — ``downgrade()`` is forever forbidden."""

    import importlib.util

    migration_path = (
        API_ROOT / "alembic" / "versions" / "0022_email_subsystem_removal.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migration_0022_integration", migration_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(NotImplementedError, match="NFR-011-002"):
        module.downgrade()
