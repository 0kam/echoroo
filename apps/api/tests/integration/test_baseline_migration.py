"""Integration test for the 006-permissions-redesign baseline Alembic migration.

This is a TDD Red test (per PR-001 / PR-006): it is committed BEFORE the actual
migration file and MUST initially fail with CI showing the failure, then turn
Green once the migration is added.

Scope (T023):
- Spin up an empty PostgreSQL database via testcontainers.
- Run ``alembic upgrade head`` pointing at it.
- Assert that the 22 authoritative entities from data-model.md §0 are present
  in ``information_schema.tables`` after the migration completes.
- Assert that the genesis rows for ``project_audit_log`` and
  ``platform_audit_log`` exist with ``prev_hash = repeat('0', 64)`` (FR-092).
- Assert that the ``wipe_guard`` table is empty at baseline (FR-114).
- Assert that the CHECK constraints documented in data-model §3 exist on the
  expected tables (FR-027, FR-048, FR-091).

The test deliberately works against a *fresh* container each run so it does not
interfere with the dev / test databases configured in ``conftest.py``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dep declared in pyproject dev extras
    PostgresContainer = None  # type: ignore[assignment,misc]


API_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = API_ROOT / "alembic.ini"


# The authoritative list of 22 entities declared in
# specs/006-permissions-redesign/data-model.md §0.
EXPECTED_TABLES: tuple[str, ...] = (
    "users",
    "superusers",
    "superuser_approval_requests",
    "projects",
    "project_license_history",
    "project_members",
    "project_invitations",
    "project_trusted_users",
    "project_taxon_sensitivity_overrides",
    "sites",
    "recordings",
    "taxon_sensitivities",
    "iucn_sync_attempts",
    "annotation_votes",
    "annotation_comments",
    "api_keys",
    "project_audit_log",
    "platform_audit_log",
    "outbox_events",
    "system_settings",
    "dek_rewrap_failures",
    "wipe_guard",
)


# Additional support tables carried over from data-model §0 "参考" row
# (datasets / detections / annotations / tags are still required because the
# baseline migration creates the whole schema from scratch, per FR-113).
SUPPORTING_TABLES: tuple[str, ...] = (
    "datasets",
    "detections",
    "annotations",
    "tags",
)


@pytest.fixture(scope="module")
def pg_container() -> Iterator[object]:
    """Spin up a throwaway PostgreSQL 16 container for the migration test."""

    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")

    container = PostgresContainer("pgvector/pgvector:pg16")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="module")
def alembic_db_url(pg_container: object) -> str:
    """Compute the SQLAlchemy URL for the container, mapped to the async driver."""

    sync_url = pg_container.get_connection_url()  # type: ignore[attr-defined]
    # testcontainers returns psycopg2-style URLs; keep sync for alembic + verification.
    return sync_url.replace("postgresql+psycopg2://", "postgresql://")


@pytest.fixture(scope="module")
def upgraded_db(alembic_db_url: str) -> str:
    """Run ``alembic upgrade head`` against the throwaway DB."""

    env = {
        "DATABASE_URL": alembic_db_url.replace("postgresql://", "postgresql+asyncpg://"),
        "ALEMBIC_SYNC_URL": alembic_db_url,
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
    return alembic_db_url


def _tables_in_db(url: str) -> set[str]:
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


def test_all_22_primary_entities_created(upgraded_db: str) -> None:
    """FR-113: the single baseline migration creates all 22 authoritative tables."""

    tables = _tables_in_db(upgraded_db)
    missing = [t for t in EXPECTED_TABLES if t not in tables]
    assert not missing, f"Missing primary entities from baseline: {missing}"


def test_supporting_tables_created(upgraded_db: str) -> None:
    """data-model §0 参考: supporting tables are still part of the baseline."""

    tables = _tables_in_db(upgraded_db)
    missing = [t for t in SUPPORTING_TABLES if t not in tables]
    assert not missing, f"Missing supporting tables from baseline: {missing}"


def test_alembic_version_stamped(upgraded_db: str) -> None:
    """alembic_version row reflects the baseline revision (FR-114 point (b))."""

    engine = create_engine(upgraded_db)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == "0001", f"Unexpected alembic version: {version!r}"
    finally:
        engine.dispose()


def test_audit_log_genesis_rows(upgraded_db: str) -> None:
    """FR-092: baseline seeds genesis rows with prev_hash = repeat('0', 64)."""

    zero64 = "0" * 64
    engine = create_engine(upgraded_db)
    try:
        with engine.connect() as conn:
            proj_genesis = conn.execute(
                sa.text(
                    "SELECT prev_hash, action FROM project_audit_log WHERE action = 'genesis'"
                )
            ).one()
            assert proj_genesis.prev_hash == zero64
            plat_genesis = conn.execute(
                sa.text(
                    "SELECT prev_hash, action FROM platform_audit_log WHERE action = 'genesis'"
                )
            ).one()
            assert plat_genesis.prev_hash == zero64
    finally:
        engine.dispose()


def test_wipe_guard_empty_at_baseline(upgraded_db: str) -> None:
    """FR-114: wipe_guard is present but empty at fresh baseline apply."""

    engine = create_engine(upgraded_db)
    try:
        with engine.connect() as conn:
            count = conn.execute(sa.text("SELECT COUNT(*) FROM wipe_guard")).scalar()
        assert count == 0, "wipe_guard should be empty at baseline"
    finally:
        engine.dispose()


def test_taxon_sensitivity_h3_check_present(upgraded_db: str) -> None:
    """FR-027: CHECK constraint restricts sensitivity_h3_res to {2,5,7,9,15}."""

    engine = create_engine(upgraded_db)
    try:
        with engine.connect() as conn, pytest.raises(IntegrityError):
            # Inserting a forbidden value must fail on the CHECK constraint.
            conn.execute(
                sa.text(
                    "INSERT INTO taxon_sensitivities "
                    "(id, taxon_id, source, sensitivity_h3_res, "
                    " created_at, updated_at) "
                    "VALUES (gen_random_uuid(), 'taxon:test', 'manual', 3, "
                    " now(), now())"
                )
            )
            conn.commit()
    finally:
        engine.dispose()
