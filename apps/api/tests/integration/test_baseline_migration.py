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
# (datasets / detections / tags are still required because the baseline
# migration creates the whole schema from scratch, per FR-113).
#
# The minimal ``annotations`` table is intentionally absent here: it is created
# at baseline-time but dropped later in the chain by migration 0030 (P4 of the
# annotation-consolidation effort, which repointed sampling_round_items onto
# ``recording_annotations`` and removed the now-unused minimal table). This
# assertion runs against the head schema, so ``annotations`` must not appear.
SUPPORTING_TABLES: tuple[str, ...] = (
    "datasets",
    "detections",
    "tags",
)

LEGACY_ANNOTATION_WORKFLOW_TABLES: tuple[str, ...] = (
    "annotation_projects",
    "annotation_project_tags",
    "annotation_project_datasets",
    "annotation_tasks",
    "clip_annotations",
    "clip_annotation_tags",
    "sound_event_annotations",
    "sound_event_annotation_tags",
)

LEGACY_ANNOTATION_WORKFLOW_ENUMS: tuple[str, ...] = (
    "annotationprojectvisibility",
    "annotationtaskstatus",
    "reviewstatus",
    "geometrytype",
)

LEGACY_NOTE_PARENT_COLUMNS: tuple[str, ...] = (
    "clip_annotation_id",
    "sound_event_annotation_id",
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
        # spec/011 NFR-011-010: Settings validator now refuses an empty
        # invitation-token kid / HMAC at every boot, so the subprocess
        # that loads echoroo.core.settings must carry both values too.
        "INVITATION_TOKEN_KID_NEW": "test-kid",
        "INVITATION_TOKEN_HMAC_KEY": "test-invitation-hmac-key-32-chars-min-padding-xxxxxxxx",
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


def _enum_types_in_db(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT t.typname
                    FROM pg_type t
                    JOIN pg_enum e ON e.enumtypid = t.oid
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'public'
                    """
                )
            ).scalars()
            return set(rows)
    finally:
        engine.dispose()


def _columns_in_table(url: str, table_name: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
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


def test_legacy_annotation_project_tables_removed(upgraded_db: str) -> None:
    """Revision 0025 removes the legacy AnnotationProject workflow tables."""

    tables = _tables_in_db(upgraded_db)
    present = [t for t in LEGACY_ANNOTATION_WORKFLOW_TABLES if t in tables]
    assert not present, f"Legacy annotation workflow tables still present: {present}"


def test_legacy_annotation_project_enums_removed(upgraded_db: str) -> None:
    """Revision 0025 removes enum types used only by the legacy workflow."""

    enum_types = _enum_types_in_db(upgraded_db)
    present = [e for e in LEGACY_ANNOTATION_WORKFLOW_ENUMS if e in enum_types]
    assert not present, f"Legacy annotation workflow enums still present: {present}"


def test_legacy_note_parent_columns_removed(upgraded_db: str) -> None:
    """Current notes no longer point directly at legacy clip/sound-event rows."""

    columns = _columns_in_table(upgraded_db, "notes")
    present = [c for c in LEGACY_NOTE_PARENT_COLUMNS if c in columns]
    assert not present, f"Legacy note parent columns still present: {present}"


def test_alembic_version_stamped(upgraded_db: str) -> None:
    """alembic_version row reflects the script directory's head (FR-114 point (b)).

    The expected stamp is resolved from ``alembic.ini`` rather than hard-coded
    so the test does not rot every time a new migration lands. ``alembic
    upgrade head`` must leave the ``alembic_version`` row pinned at the head
    revision returned by ``ScriptDirectory``.
    """

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ALEMBIC_INI))
    script_dir = ScriptDirectory.from_config(config)
    expected_head = script_dir.get_current_head()
    assert expected_head is not None, (
        "alembic.ini must define a head revision; check apps/api/alembic/versions/"
    )

    engine = create_engine(upgraded_db)
    try:
        with engine.connect() as conn:
            version = conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar()
        assert version == expected_head, (
            f"alembic_version {version!r} does not match script head {expected_head!r}"
        )
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
