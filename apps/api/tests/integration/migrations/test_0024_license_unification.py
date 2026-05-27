"""Integration tests for Alembic revision 0024 (spec/012 Phase 2).

The migration promotes the project license field from the legacy
``projects.license`` enum string to ``projects.license_id`` referencing the
``licenses`` master, converts project license history snapshots to strings,
and aligns dataset/license deletion semantics with ``ON DELETE RESTRICT``.

These tests mirror the testcontainers pattern from
``test_0022_email_subsystem_removal.py`` while keeping every test isolated in
its own throwaway PostgreSQL 16 database. Negative-path cases intentionally
extend the legacy ``projectlicense`` enum with a non-canonical value before
running the migration so the audit-first safety belt can observe and reject it.
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
PREVIOUS_REVISION = "0023"
TARGET_REVISION = "0024"

OWNER_ID = "00000000-0000-0000-0000-000000000101"
PROJECT_IDS = {
    "CC0": "00000000-0000-0000-0000-000000000201",
    "CC-BY": "00000000-0000-0000-0000-000000000202",
    "CC-BY-NC": "00000000-0000-0000-0000-000000000203",
    "CC-BY-SA": "00000000-0000-0000-0000-000000000204",
}
HISTORY_ID = "00000000-0000-0000-0000-000000000301"


@pytest.fixture()
def pg_container() -> Iterator[PostgresContainer]:
    """Spin up one throwaway PostgreSQL 16 container per test."""

    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")

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
    sync_url = container.get_connection_url()
    return sync_url.replace("postgresql+psycopg2://", "postgresql://")


def _alembic_env(sync_url: str) -> dict[str, str]:
    async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")
    return {
        **os.environ,
        "DATABASE_URL": async_url,
        "ALEMBIC_SYNC_URL": sync_url,
        "INVITATION_TOKEN_KID_NEW": os.environ.get("INVITATION_TOKEN_KID_NEW")
        or "test-kid",
        "INVITATION_TOKEN_HMAC_KEY": os.environ.get("INVITATION_TOKEN_HMAC_KEY")
        or "test-invitation-hmac-key-32-chars-min-padding-xxxxxxxx",
    }


def _run_alembic(sync_url: str, target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
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
        env=_alembic_env(sync_url),
        capture_output=True,
        text=True,
        check=False,
    )


def _alembic_upgrade(sync_url: str, target: str) -> None:
    result = _run_alembic(sync_url, target)
    if result.returncode != 0:
        pytest.fail(
            f"alembic upgrade {target} failed against {sync_url}.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def _alembic_upgrade_expect_failure(sync_url: str, target: str) -> str:
    result = _run_alembic(sync_url, target)
    assert result.returncode != 0
    combined = f"{result.stdout}\n{result.stderr}"
    assert "ValueError" in combined
    return combined


def _engine(url: str) -> sa.Engine:
    return create_engine(url)


def _alembic_version(url: str) -> str:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()


def _columns(url: str, table_name: str) -> set[str]:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return set(
                conn.execute(
                    sa.text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :table_name"
                    ),
                    {"table_name": table_name},
                ).scalars()
            )
    finally:
        engine.dispose()


def _column_type(url: str, table_name: str, column_name: str) -> str:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name = :table_name "
                    "AND column_name = :column_name"
                ),
                {"table_name": table_name, "column_name": column_name},
            ).scalar_one()
    finally:
        engine.dispose()


def _constraint_delete_action(url: str, constraint_name: str) -> str:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text(
                    "SELECT confdeltype FROM pg_constraint "
                    "WHERE conname = :constraint_name"
                ),
                {"constraint_name": constraint_name},
            ).scalar_one()
    finally:
        engine.dispose()


def _index_exists(url: str, index_name: str) -> bool:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return (
                conn.execute(
                    sa.text(
                        "SELECT 1 FROM pg_indexes "
                        "WHERE schemaname = 'public' AND indexname = :index_name"
                    ),
                    {"index_name": index_name},
                ).scalar()
                is not None
            )
    finally:
        engine.dispose()


def _seed_owner(conn: sa.Connection) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO users (
                id, email, password_hash, display_name, security_stamp,
                created_at, updated_at
            )
            VALUES (
                :id, 'license-migration-owner@example.com', 'hash',
                'Migration Owner', 'security-stamp', now(), now()
            )
            ON CONFLICT (email) DO NOTHING
            """
        ),
        {"id": OWNER_ID},
    )


def _seed_projects_and_history(url: str) -> None:
    engine = _engine(url)
    try:
        with engine.begin() as conn:
            _seed_owner(conn)
            for legacy_license, project_id in PROJECT_IDS.items():
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO projects (
                            id, name, owner_id, visibility, license,
                            restricted_config, restricted_config_version,
                            status, review_min_votes,
                            review_consensus_threshold, created_at, updated_at
                        )
                        VALUES (
                            :id, :name, :owner_id, 'restricted',
                            CAST(:license AS projectlicense),
                            '{
                                "allow_media_playback": true,
                                "allow_detection_view": true,
                                "mask_species_in_detection": false,
                                "allow_download": true,
                                "allow_export": true,
                                "allow_voting_and_comments": true,
                                "public_location_precision_h3_res": 7,
                                "allow_precise_location_to_viewer": false
                            }'::jsonb,
                            1, 'active', 2, 0.667, now(), now()
                        )
                        """
                    ),
                    {
                        "id": project_id,
                        "name": f"Project {legacy_license}",
                        "owner_id": OWNER_ID,
                        "license": legacy_license,
                    },
                )
            conn.execute(
                sa.text(
                    """
                    INSERT INTO project_license_history (
                        id, project_id, old_license, new_license, changed_at,
                        changed_by_id, created_at, updated_at
                    )
                    VALUES (
                        :id, :project_id, CAST(NULL AS projectlicense),
                        CAST('CC-BY' AS projectlicense), now(), :changed_by_id,
                        now(), now()
                    )
                    """
                ),
                {
                    "id": HISTORY_ID,
                    "project_id": PROJECT_IDS["CC-BY"],
                    "changed_by_id": OWNER_ID,
                },
            )
            conn.execute(
                sa.text(
                    """
                    INSERT INTO licenses (
                        id, name, short_name, url, description,
                        created_at, updated_at
                    )
                    VALUES (
                        'cc0', 'Admin Curated CC0', 'CC0',
                        'https://example.com/admin-cc0', 'Preserve me',
                        now(), now()
                    )
                    """
                )
            )
            conn.execute(
                sa.text(
                    """
                    INSERT INTO datasets (
                        name, site_id, project_id, created_by_id,
                        license_id, visibility, status, total_files,
                        processed_files, created_at, updated_at
                    )
                    SELECT
                        'Dataset with CC0', sites.id, :project_id, :owner_id,
                        'cc0', 'private', 'pending', 0, 0, now(), now()
                    FROM sites
                    LIMIT 1
                    """
                ),
                {"project_id": PROJECT_IDS["CC0"], "owner_id": OWNER_ID},
            )
    finally:
        engine.dispose()


def _add_unknown_enum_value(url: str, value: str) -> None:
    engine = _engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(f"ALTER TYPE projectlicense ADD VALUE '{value}'"))
    finally:
        engine.dispose()


def _inject_unknown_project_license(url: str, value: str) -> None:
    engine = _engine(url)
    try:
        with engine.begin() as conn:
            _seed_owner(conn)
            conn.execute(
                sa.text(
                    """
                    INSERT INTO projects (
                        id, name, owner_id, visibility, license,
                        restricted_config, restricted_config_version,
                        status, review_min_votes,
                        review_consensus_threshold, created_at, updated_at
                    )
                    VALUES (
                        gen_random_uuid(), 'Unknown license project', :owner_id,
                        'restricted', CAST(:license AS projectlicense),
                        '{
                            "allow_media_playback": true,
                            "allow_detection_view": true,
                            "mask_species_in_detection": false,
                            "allow_download": true,
                            "allow_export": true,
                            "allow_voting_and_comments": true,
                            "public_location_precision_h3_res": 7,
                            "allow_precise_location_to_viewer": false
                        }'::jsonb,
                        1, 'active', 2, 0.667, now(), now()
                    )
                    """
                ),
                {"owner_id": OWNER_ID, "license": value},
            )
    finally:
        engine.dispose()


def _inject_unknown_history_license(url: str, value: str) -> None:
    engine = _engine(url)
    try:
        with engine.begin() as conn:
            _seed_owner(conn)
            conn.execute(
                sa.text(
                    """
                    INSERT INTO projects (
                        id, name, owner_id, visibility, license,
                        restricted_config, restricted_config_version,
                        status, review_min_votes,
                        review_consensus_threshold, created_at, updated_at
                    )
                    VALUES (
                        :project_id, 'History unknown project', :owner_id,
                        'restricted', CAST('CC-BY' AS projectlicense),
                        '{
                            "allow_media_playback": true,
                            "allow_detection_view": true,
                            "mask_species_in_detection": false,
                            "allow_download": true,
                            "allow_export": true,
                            "allow_voting_and_comments": true,
                            "public_location_precision_h3_res": 7,
                            "allow_precise_location_to_viewer": false
                        }'::jsonb,
                        1, 'active', 2, 0.667, now(), now()
                    )
                    """
                ),
                {"project_id": PROJECT_IDS["CC-BY"], "owner_id": OWNER_ID},
            )
            conn.execute(
                sa.text(
                    """
                    INSERT INTO project_license_history (
                        id, project_id, old_license, new_license, changed_at,
                        changed_by_id, created_at, updated_at
                    )
                    VALUES (
                        gen_random_uuid(), :project_id, CAST('CC-BY' AS projectlicense),
                        CAST(:license AS projectlicense), now(), :changed_by_id,
                        now(), now()
                    )
                    """
                ),
                {
                    "project_id": PROJECT_IDS["CC-BY"],
                    "license": value,
                    "changed_by_id": OWNER_ID,
                },
            )
    finally:
        engine.dispose()


def _license_rows(url: str) -> dict[str, tuple[str, str]]:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return {
                row.short_name: (row.id, row.name)
                for row in conn.execute(
                    sa.text("SELECT id, short_name, name FROM licenses")
                )
            }
    finally:
        engine.dispose()


def _project_license_ids(url: str) -> dict[str, str | None]:
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return {
                str(row.id): row.license_id
                for row in conn.execute(
                    sa.text("SELECT id, license_id FROM projects")
                )
            }
    finally:
        engine.dispose()


def test_0024_happy_path_seeds_maps_and_rewrites_schema(
    pg_container: PostgresContainer,
) -> None:
    url = _admin_sync_url(pg_container)
    _alembic_upgrade(url, PREVIOUS_REVISION)
    _seed_projects_and_history(url)

    _alembic_upgrade(url, TARGET_REVISION)

    license_rows = _license_rows(url)
    assert license_rows["CC0"] == ("cc0", "Admin Curated CC0")
    assert license_rows["CC-BY"][0] == "cc-by"
    assert license_rows["CC-BY-NC"][0] == "cc-by-nc"
    assert license_rows["CC-BY-SA"][0] == "cc-by-sa"

    project_license_ids = _project_license_ids(url)
    assert project_license_ids[PROJECT_IDS["CC0"]] == "cc0"
    assert project_license_ids[PROJECT_IDS["CC-BY"]] == "cc-by"
    assert project_license_ids[PROJECT_IDS["CC-BY-NC"]] == "cc-by-nc"
    assert project_license_ids[PROJECT_IDS["CC-BY-SA"]] == "cc-by-sa"

    project_columns = _columns(url, "projects")
    assert "license" not in project_columns
    assert "license_id" in project_columns

    assert _constraint_delete_action(url, "projects_license_id_fkey") == "r"
    assert _index_exists(url, "ix_projects_license_id")
    assert _constraint_delete_action(url, "fk_datasets_license_id") == "r"

    assert _column_type(url, "project_license_history", "old_license") == "character varying"
    assert _column_type(url, "project_license_history", "new_license") == "character varying"
    assert _alembic_version(url) == TARGET_REVISION


def test_0024_rejects_unknown_project_license_without_schema_changes(
    pg_container: PostgresContainer,
) -> None:
    url = _admin_sync_url(pg_container)
    _alembic_upgrade(url, PREVIOUS_REVISION)
    _add_unknown_enum_value(url, "PUBLIC-DOMAIN")
    _inject_unknown_project_license(url, "PUBLIC-DOMAIN")

    error = _alembic_upgrade_expect_failure(url, TARGET_REVISION)

    assert "projects.license" in error
    assert "PUBLIC-DOMAIN" in error
    assert _alembic_version(url) == PREVIOUS_REVISION
    assert "license" in _columns(url, "projects")
    assert "license_id" not in _columns(url, "projects")
    assert _column_type(url, "project_license_history", "new_license") == "USER-DEFINED"
    assert _constraint_delete_action(url, "fk_datasets_license_id") == "n"


def test_0024_rejects_unknown_history_license_without_schema_changes(
    pg_container: PostgresContainer,
) -> None:
    url = _admin_sync_url(pg_container)
    _alembic_upgrade(url, PREVIOUS_REVISION)
    _add_unknown_enum_value(url, "CC-BY-ND")
    _inject_unknown_history_license(url, "CC-BY-ND")

    error = _alembic_upgrade_expect_failure(url, TARGET_REVISION)

    assert "project_license_history.new_license" in error
    assert "CC-BY-ND" in error
    assert _alembic_version(url) == PREVIOUS_REVISION
    assert "license" in _columns(url, "projects")
    assert "license_id" not in _columns(url, "projects")
    assert _column_type(url, "project_license_history", "old_license") == "USER-DEFINED"
    assert _column_type(url, "project_license_history", "new_license") == "USER-DEFINED"
    assert _constraint_delete_action(url, "fk_datasets_license_id") == "n"


def test_0024_preserves_license_history_snapshot_values(
    pg_container: PostgresContainer,
) -> None:
    url = _admin_sync_url(pg_container)
    _alembic_upgrade(url, PREVIOUS_REVISION)
    _seed_projects_and_history(url)

    _alembic_upgrade(url, TARGET_REVISION)

    engine = _engine(url)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    """
                    SELECT old_license, new_license
                    FROM project_license_history
                    WHERE id = :history_id
                    """
                ),
                {"history_id": HISTORY_ID},
            ).one()
    finally:
        engine.dispose()

    assert row.old_license is None
    assert row.new_license == "CC-BY"
