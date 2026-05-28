"""Pytest configuration and fixtures."""

import importlib
import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import patch

# spec/011 NFR-011-010 — invitation token kid + HMAC defensive bootstrap.
# ``echoroo.core.settings.Settings`` requires INVITATION_TOKEN_KID_NEW and
# INVITATION_TOKEN_HMAC_KEY to be non-empty at every boot (dev / staging /
# prod). Any test-collection-time ``from echoroo...`` import below
# transitively constructs Settings (via get_settings() / database.py), so a
# missing env crashes the entire collection. CI sets these explicitly; this
# os.environ.setdefault block is a belt-and-braces safety net for local
# `uv run pytest` (e.g. dev shells without docker exec) so collection never
# fails for a developer who forgot to source the env. Strength check is
# prod/staging-only so these short fixtures are accepted.
import os as _os

_os.environ.setdefault("INVITATION_TOKEN_KID_NEW", "test-kid")
_os.environ.setdefault(
    "INVITATION_TOKEN_HMAC_KEY",
    "test-invitation-hmac-key-32-chars-min-padding-xxxxxxxx",
)

import pytest
import pytest_asyncio
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.api.v1.clips import get_audio_service as _get_audio_service_clips
from echoroo.api.v1.datasets import get_audio_service as _get_audio_service_datasets
from echoroo.api.v1.recordings import (
    get_audio_service as _get_audio_service_recordings,
)
from echoroo.core.database import get_db
from echoroo.core.settings import get_settings
from echoroo.main import create_app
from echoroo.models.base import Base
from echoroo.services.audio import AudioService

# Test database URL — override via TEST_DATABASE_URL env var to allow running
# from inside Docker containers where the DB is accessible via a service hostname
# rather than localhost (e.g. TEST_DATABASE_URL=postgresql+asyncpg://echoroo:echoroo@db:5432/echoroo_test).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)

CANONICAL_TEST_LICENSES = (
    {
        "id": "cc0",
        "name": "Creative Commons Zero",
        "short_name": "CC0",
        "url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "description": "Public domain dedication.",
    },
    {
        "id": "cc-by",
        "name": "Creative Commons Attribution",
        "short_name": "CC-BY",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "description": "Attribution required.",
    },
    {
        "id": "cc-by-nc",
        "name": "Creative Commons Attribution NonCommercial",
        "short_name": "CC-BY-NC",
        "url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "description": "Attribution required; non-commercial use only.",
    },
    {
        "id": "cc-by-sa",
        "name": "Creative Commons Attribution ShareAlike",
        "short_name": "CC-BY-SA",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "description": "Attribution required; derivatives share alike.",
    },
)


def _make_create_enum_sql(type_name: str, values: list[str]) -> str:
    """Build idempotent DO-block SQL for creating a Postgres enum type.

    Uses a DO block to skip creation if the type already exists, which is
    compatible with Postgres 10+.  ``CREATE TYPE IF NOT EXISTS`` is not
    supported for enum types on any current Postgres version.

    Args:
        type_name: Name of the enum type to create.
        values: Ordered list of enum value strings.

    Returns:
        SQL string safe to execute on an existing database.
    """
    quoted = ", ".join(f"'{v}'" for v in values)
    return (
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{type_name}') THEN "
        f"CREATE TYPE {type_name} AS ENUM ({quoted}); "
        f"END IF; "
        f"END $$"
    )


async def _sync_0023_license_schema(engine: AsyncEngine) -> None:
    """Apply the spec/012 Phase 2 license schema changes to the test DB."""

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        WHERE c.conrelid = 'licenses'::regclass
                        AND c.contype = 'u'
                        AND c.conkey = ARRAY[
                            (
                                SELECT a.attnum
                                FROM pg_attribute a
                                WHERE a.attrelid = 'licenses'::regclass
                                AND a.attname = 'short_name'
                                AND NOT a.attisdropped
                            )
                        ]::smallint[]
                    ) THEN
                        ALTER TABLE licenses
                            ADD CONSTRAINT uq_licenses_short_name UNIQUE (short_name);
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                INSERT INTO licenses (
                    id, name, short_name, url, description, created_at, updated_at
                )
                VALUES (
                    :id, :name, :short_name, :url, :description, now(), now()
                )
                ON CONFLICT (short_name) DO NOTHING
                """
            ),
            list(CANONICAL_TEST_LICENSES),
        )
        await conn.execute(
            sa.text(
                "ALTER TABLE projects ADD COLUMN IF NOT EXISTS license_id VARCHAR(50) NULL"
            )
        )
        await conn.execute(
            sa.text(
                """
                DO $$
                DECLARE
                    unmapped_count integer;
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'projects'
                        AND column_name = 'license'
                    ) THEN
                        UPDATE projects
                        SET license_id = licenses.id
                        FROM licenses
                        WHERE projects.license IS NOT NULL
                        AND projects.license_id IS NULL
                        AND licenses.short_name = projects.license::text;

                        SELECT count(*)
                        INTO unmapped_count
                        FROM projects
                        WHERE license IS NOT NULL
                        AND license_id IS NULL;

                        IF unmapped_count > 0 THEN
                            RAISE EXCEPTION
                                '0023 test schema sync could not map % project license value(s)',
                                unmapped_count;
                        END IF;
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                DO $$
                DECLARE
                    constraint_name text;
                    license_id_attnum smallint;
                    id_attnum smallint;
                BEGIN
                    SELECT a.attnum
                    INTO license_id_attnum
                    FROM pg_attribute a
                    WHERE a.attrelid = 'projects'::regclass
                    AND a.attname = 'license_id'
                    AND NOT a.attisdropped;

                    SELECT a.attnum
                    INTO id_attnum
                    FROM pg_attribute a
                    WHERE a.attrelid = 'licenses'::regclass
                    AND a.attname = 'id'
                    AND NOT a.attisdropped;

                    FOR constraint_name IN
                        SELECT c.conname
                        FROM pg_constraint c
                        WHERE c.conrelid = 'projects'::regclass
                        AND c.contype = 'f'
                        AND (
                            c.conname = 'projects_license_id_fkey'
                            OR (
                                c.confrelid = 'licenses'::regclass
                                AND c.conkey = ARRAY[license_id_attnum]::smallint[]
                            )
                        )
                    LOOP
                        EXECUTE format(
                            'ALTER TABLE projects DROP CONSTRAINT %I',
                            constraint_name
                        );
                    END LOOP;

                    IF license_id_attnum IS NOT NULL AND id_attnum IS NOT NULL THEN
                        ALTER TABLE projects
                            ADD CONSTRAINT projects_license_id_fkey
                            FOREIGN KEY (license_id) REFERENCES licenses(id)
                            ON DELETE RESTRICT;
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_projects_license_id "
                "ON projects (license_id)"
            )
        )
        await conn.execute(sa.text("ALTER TABLE projects DROP COLUMN IF EXISTS license"))
        await conn.execute(
            sa.text(
                """
                DO $$
                BEGIN
                    IF to_regclass('project_license_history') IS NOT NULL THEN
                        IF EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'project_license_history'
                            AND column_name = 'old_license'
                        ) THEN
                            ALTER TABLE project_license_history
                                ALTER COLUMN old_license TYPE VARCHAR(50)
                                USING old_license::text;
                        END IF;

                        IF EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = 'project_license_history'
                            AND column_name = 'new_license'
                        ) THEN
                            ALTER TABLE project_license_history
                                ALTER COLUMN new_license TYPE VARCHAR(50)
                                USING new_license::text;
                        END IF;
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                DO $$
                DECLARE
                    constraint_name text;
                    license_id_attnum smallint;
                    id_attnum smallint;
                BEGIN
                    SELECT a.attnum
                    INTO license_id_attnum
                    FROM pg_attribute a
                    WHERE a.attrelid = 'datasets'::regclass
                    AND a.attname = 'license_id'
                    AND NOT a.attisdropped;

                    SELECT a.attnum
                    INTO id_attnum
                    FROM pg_attribute a
                    WHERE a.attrelid = 'licenses'::regclass
                    AND a.attname = 'id'
                    AND NOT a.attisdropped;

                    FOR constraint_name IN
                        SELECT c.conname
                        FROM pg_constraint c
                        WHERE c.conrelid = 'datasets'::regclass
                        AND c.confrelid = 'licenses'::regclass
                        AND c.contype = 'f'
                        AND c.conname IN (
                            'fk_datasets_license_id',
                            'datasets_license_id_fkey'
                        )
                        AND c.conkey = ARRAY[license_id_attnum]::smallint[]
                        AND c.confkey = ARRAY[id_attnum]::smallint[]
                    LOOP
                        EXECUTE format(
                            'ALTER TABLE datasets DROP CONSTRAINT %I',
                            constraint_name
                        );
                    END LOOP;

                    IF license_id_attnum IS NOT NULL AND id_attnum IS NOT NULL THEN
                        ALTER TABLE datasets
                            ADD CONSTRAINT fk_datasets_license_id
                            FOREIGN KEY (license_id) REFERENCES licenses(id)
                            ON DELETE RESTRICT;
                    END IF;
                END
                $$;
                """
            )
        )


async def setup_test_database(engine: AsyncEngine) -> None:
    """Set up test database schema and enum types.

    Two-phase setup:
    1. If no tables exist at all → fresh schema creation (DROP + CREATE).
    2. If core tables exist but newer tables (search_sessions, embeddings) are
       missing → targeted migration using the idempotent DO-block enum helper
       and raw CREATE TABLE SQL so that existing indexes are not touched.
    """
    # Phase 13 P1 R2 致命 #1: register a stub ``superusers`` Table on
    # ``Base.metadata`` *unconditionally*, even when the DB-side schema is
    # already up to date. The stub is process-local (resets on every fresh
    # interpreter) and is needed by every ORM operation that walks the
    # ``system_settings.updated_by_id`` FK — including tests that run
    # *after* a previous test already populated the schema. Skipping this
    # block when the early-return below fires would leave subsequent ORM
    # operations exposed to ``NoReferencedTableError`` from
    # ``sort_tables_and_constraints``.
    if "superusers" not in Base.metadata.tables:
        sa.Table(
            "superusers",
            Base.metadata,
            sa.Column("id", PgUUID(as_uuid=True), primary_key=True),
            sa.Column("user_id", PgUUID(as_uuid=True), nullable=False),
            info={"_phase13_stub": True},
        )
    async with engine.connect() as conn:
        core_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users')"
            )
        )
        core_exists = bool(core_exists_result.scalar())

        search_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'search_sessions')"
            )
        )
        search_exists = bool(search_exists_result.scalar())

        # Phase 11: taxon auto-obscure tables (006-permissions-redesign).
        taxon_sensitivity_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'taxon_sensitivities')"
            )
        )
        taxon_sensitivity_exists = bool(taxon_sensitivity_exists_result.scalar())

        # Phase 12 R1: outbox_events lives only in Alembic 0001 (no ORM
        # model yet) so it must be created explicitly when missing.
        outbox_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'outbox_events')"
            )
        )
        outbox_exists = bool(outbox_exists_result.scalar())

        # Phase 12 R2: ``superusers`` (Alembic 0001, no ORM model) is
        # probed by every authenticated request — must exist in the
        # test DB.
        superusers_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'superusers')"
            )
        )
        superusers_exists = bool(superusers_exists_result.scalar())

        # Phase 15 NO-GO: ``superuser_approval_requests`` is the M-of-N
        # ticket store created in :mod:`apps/api/alembic/versions/0001`
        # and DDL-mirrored in this conftest. Probe it explicitly so an
        # existing test DB that pre-dates the Phase 15 batch gets the
        # CREATE TABLE block re-run.
        approval_requests_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'superuser_approval_requests')"
            )
        )
        approval_requests_exists = bool(
            approval_requests_exists_result.scalar()
        )

        # Phase 16 Batch 6g-2: ``platform_audit_log`` and ``project_audit_log``
        # are created by Alembic 0001 (no ORM model). The T993/T993a performance
        # tests write directly to these tables via ``AuditLogService``.
        platform_audit_log_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'platform_audit_log')"
            )
        )
        platform_audit_log_exists = bool(platform_audit_log_exists_result.scalar())

        project_audit_log_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'project_audit_log')"
            )
        )
        project_audit_log_exists = bool(project_audit_log_exists_result.scalar())

        # Phase 16 Batch 6g-2 R2 (Codex Minor 1): the early-return previously
        # only confirmed audit-log *tables* existed — but if a prior test
        # process aborted between CREATE TABLE and CREATE TRIGGER, the
        # ``platform_audit_log_immutable`` / ``project_audit_log_immutable``
        # triggers (and the ``ck_project_audit_log_project_id_required``
        # check constraint) could be missing. Skipping the re-attach path
        # in that state would let the T993/T993a tests DELETE rows that
        # production code can never delete, masking real append-only
        # contract regressions. Probe the triggers + constraint here so
        # the schema-up-to-date predicate is genuinely complete.
        platform_trigger_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger"
                " WHERE tgname = 'platform_audit_log_immutable')"
            )
        )
        platform_trigger_exists = bool(platform_trigger_exists_result.scalar())

        project_trigger_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger"
                " WHERE tgname = 'project_audit_log_immutable')"
            )
        )
        project_trigger_exists = bool(project_trigger_exists_result.scalar())

        project_exists_trigger_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger"
                " WHERE tgname = 'project_audit_log_project_exists')"
            )
        )
        project_exists_trigger_exists = bool(
            project_exists_trigger_exists_result.scalar()
        )

        project_audit_log_fk_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_constraint"
                " WHERE conrelid = to_regclass('project_audit_log')"
                " AND conname = 'project_audit_log_project_id_fkey')"
            )
        )
        project_audit_log_fk_exists = bool(
            project_audit_log_fk_exists_result.scalar()
        )

        # Phase 17 A-11: ``two_factor_reset_requests`` and companions are
        # created by Alembic 0014 and via ORM Base.metadata. Probe them
        # so an existing test DB that pre-dates A-11 gets the CREATE TABLE
        # block run on the next ``setup_test_database`` call.
        two_factor_reset_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'two_factor_reset_requests')"
            )
        )
        two_factor_reset_exists = bool(two_factor_reset_exists_result.scalar())

        # Round-2 Fix-2: probe the new ``dispatching_started_at`` column
        # added by alembic 0015 so an existing test DB with the A-11
        # tables but pre-0015 still gets the column added below.
        two_factor_reset_dispatching_col_exists = False
        if two_factor_reset_exists:
            col_result = await conn.execute(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
                    " WHERE table_name = 'two_factor_reset_requests'"
                    " AND column_name = 'dispatching_started_at')"
                )
            )
            two_factor_reset_dispatching_col_exists = bool(col_result.scalar())

        # Phase 2.11 P0-d (Alembic 0002): ``token_families`` has no ORM model
        # and is not picked up by ``Base.metadata.create_all``. Probe it so
        # existing test DBs that pre-date this migration get the table created.
        token_families_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables"
                " WHERE table_name = 'token_families')"
            )
        )
        token_families_exists = bool(token_families_exists_result.scalar())

        # Phase 17 backlog A-2 (FR-091b): probe the dual-write columns
        # added by alembic 0016. ``Base.metadata.create_all`` runs with
        # ``checkfirst=True`` so it never alters an existing table —
        # we therefore add the columns idempotently below if missing.
        invitation_v2_col_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
                " WHERE table_name = 'project_invitations'"
                " AND column_name = 'email_hash_v2')"
            )
        )
        invitation_v2_col_exists = bool(
            invitation_v2_col_exists_result.scalar()
        )
        audit_v2_col_exists_result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns"
                " WHERE table_name = 'platform_audit_log'"
                " AND column_name = 'actor_user_id_hash_v2')"
            )
        )
        audit_v2_col_exists = bool(audit_v2_col_exists_result.scalar())

        # Existing test DBs may still carry the pre-0017 project_id FK. We
        # drop it below before any early return so hard-deleted projects do
        # not require rewriting append-only audit rows during cleanup.
        license_schema_current_result = await conn.execute(
            sa.text(
                """
                SELECT
                    EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'projects'
                        AND column_name = 'license_id'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'projects'
                        AND column_name = 'license'
                    )
                    AND EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'project_license_history'
                        AND column_name = 'old_license'
                        AND data_type = 'character varying'
                        AND character_maximum_length = 50
                    )
                    AND EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'project_license_history'
                        AND column_name = 'new_license'
                        AND data_type = 'character varying'
                        AND character_maximum_length = 50
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        WHERE c.conrelid = to_regclass('licenses')
                        AND c.contype = 'u'
                        AND c.conkey = ARRAY[
                            (
                                SELECT a.attnum
                                FROM pg_attribute a
                                WHERE a.attrelid = to_regclass('licenses')
                                AND a.attname = 'short_name'
                                AND NOT a.attisdropped
                            )
                        ]::smallint[]
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        WHERE c.conname = 'projects_license_id_fkey'
                        AND c.conrelid = to_regclass('projects')
                        AND c.confrelid = to_regclass('licenses')
                        AND c.contype = 'f'
                        AND c.confdeltype = 'r'
                        AND c.conkey = ARRAY[
                            (
                                SELECT a.attnum
                                FROM pg_attribute a
                                WHERE a.attrelid = to_regclass('projects')
                                AND a.attname = 'license_id'
                                AND NOT a.attisdropped
                            )
                        ]::smallint[]
                        AND c.confkey = ARRAY[
                            (
                                SELECT a.attnum
                                FROM pg_attribute a
                                WHERE a.attrelid = to_regclass('licenses')
                                AND a.attname = 'id'
                                AND NOT a.attisdropped
                            )
                        ]::smallint[]
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM pg_class i
                        JOIN pg_index ix ON ix.indexrelid = i.oid
                        JOIN pg_attribute a
                            ON a.attrelid = ix.indrelid
                            AND a.attname = 'license_id'
                            AND NOT a.attisdropped
                        WHERE i.relname = 'ix_projects_license_id'
                        AND ix.indrelid = to_regclass('projects')
                        AND ix.indisvalid
                        AND ix.indisready
                        AND ix.indnatts = 1
                        AND ix.indkey[0] = a.attnum
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM pg_constraint c
                        WHERE c.conrelid = to_regclass('datasets')
                        AND c.confrelid = to_regclass('licenses')
                        AND c.contype = 'f'
                        AND c.confdeltype = 'r'
                        AND c.conkey = ARRAY[
                            (
                                SELECT a.attnum
                                FROM pg_attribute a
                                WHERE a.attrelid = to_regclass('datasets')
                                AND a.attname = 'license_id'
                                AND NOT a.attisdropped
                            )
                        ]::smallint[]
                        AND c.confkey = ARRAY[
                            (
                                SELECT a.attnum
                                FROM pg_attribute a
                                WHERE a.attrelid = to_regclass('licenses')
                                AND a.attname = 'id'
                                AND NOT a.attisdropped
                            )
                        ]::smallint[]
                    ) AS current
                """
            )
        )
        license_schema_current = bool(license_schema_current_result.scalar())

    if project_audit_log_exists and project_audit_log_fk_exists:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "ALTER TABLE project_audit_log "
                    "DROP CONSTRAINT IF EXISTS project_audit_log_project_id_fkey"
                )
            )
        project_audit_log_fk_exists = False

    non_license_schema_current = (
        core_exists
        and search_exists
        and taxon_sensitivity_exists
        and outbox_exists
        and superusers_exists
        and approval_requests_exists
        and platform_audit_log_exists
        and project_audit_log_exists
        and platform_trigger_exists
        and project_trigger_exists
        and project_exists_trigger_exists
        and not project_audit_log_fk_exists
        and two_factor_reset_exists
        and two_factor_reset_dispatching_col_exists
        and invitation_v2_col_exists
        and audit_v2_col_exists
        and token_families_exists
    )
    if non_license_schema_current and not license_schema_current:
        await _sync_0023_license_schema(engine)
        return

    if non_license_schema_current and license_schema_current:
        # Schema is fully up to date — nothing to do.
        return

    # Round-2 Fix-2: idempotent column add for legacy test DBs.
    if two_factor_reset_exists and not two_factor_reset_dispatching_col_exists:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "ALTER TABLE two_factor_reset_requests "
                    "ADD COLUMN IF NOT EXISTS dispatching_started_at "
                    "TIMESTAMP WITH TIME ZONE NULL"
                )
            )
            await conn.execute(
                sa.text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_two_factor_reset_requests_dispatching_started "
                    "ON two_factor_reset_requests (dispatching_started_at) "
                    "WHERE status = 'dispatching'"
                )
            )

    # Phase 17 backlog A-2 (FR-091b): idempotent column add for legacy
    # test DBs that pre-date Alembic 0016. The columns are nullable so
    # the add is safe on existing rows. Partial indexes mirror the
    # production migration so any "rotation in progress" filter in
    # tests benefits from the same query plan as live PostgreSQL.
    if not invitation_v2_col_exists or not audit_v2_col_exists:
        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "ALTER TABLE project_invitations "
                    "ADD COLUMN IF NOT EXISTS email_hash_v2 VARCHAR(64) NULL, "
                    "ADD COLUMN IF NOT EXISTS pii_hash_version INTEGER NULL"
                )
            )
            await conn.execute(
                sa.text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_project_invitations_email_hash_v2 "
                    "ON project_invitations (email_hash_v2) "
                    "WHERE email_hash_v2 IS NOT NULL"
                )
            )
            for table in ("platform_audit_log", "project_audit_log"):
                await conn.execute(
                    sa.text(
                        f"ALTER TABLE {table} "
                        f"ADD COLUMN IF NOT EXISTS actor_user_id_hash_v2 VARCHAR(64) NULL, "
                        f"ADD COLUMN IF NOT EXISTS ip_hash_v2 VARCHAR(64) NULL, "
                        f"ADD COLUMN IF NOT EXISTS user_agent_hash_v2 VARCHAR(64) NULL, "
                        f"ADD COLUMN IF NOT EXISTS pii_hash_version INTEGER NULL"
                    )
                )
                await conn.execute(
                    sa.text(
                        f"CREATE INDEX IF NOT EXISTS "
                        f"ix_{table}_actor_v2 "
                        f"ON {table} (actor_user_id_hash_v2) "
                        f"WHERE actor_user_id_hash_v2 IS NOT NULL"
                    )
                )

    if not core_exists:
        # Fresh database — build using the raw-SQL path below.
        # We do NOT drop and recreate the schema because echoroo user lacks
        # CREATE EXTENSION privilege — pgvector must already be installed by
        # the DBA/docker entrypoint (it is in the dev stack via initdb scripts).
        # Fall through to the enum + table creation logic below.
        pass

    # Create enum types and tables idempotently.
    # We always run this block (whether fully fresh or only partially set up)
    # so that newly added tables/enums are picked up on existing test databases.
    async with engine.begin() as conn:
        enum_defs: list[tuple[str, list[str]]] = [
            ("projectvisibility", ["private", "public", "restricted"]),
            ("projectrole", ["admin", "member", "viewer"]),
            ("projectmemberrole", ["admin", "member", "viewer"]),
            ("projectstatus", ["active", "dormant", "archived"]),
            ("projectlicense", ["CC0", "CC-BY", "CC-BY-NC", "CC-BY-SA"]),
            # Phase 13 P1 (T803a): ``setting_type`` enum was retired together
            # with the ``system_settings.value_type`` column when system_settings
            # values became JSONB-native. Do not declare it here.
            ("datasetvisibility", ["private", "public"]),
            ("datasetstatus", ["pending", "scanning", "processing", "completed", "failed"]),
            ("datetimeparsestatus", ["pending", "success", "failed"]),
            ("tagcategory", ["species", "sound_type", "quality"]),
            ("annotationprojectvisibility", ["private", "public"]),
            ("annotationtaskstatus", ["pending", "in_progress", "review_pending", "completed"]),
            ("reviewstatus", ["unreviewed", "approved", "rejected"]),
            ("annotationsource", ["human", "model"]),
            ("geometrytype", ["BoundingBox", "TimeInterval"]),
            (
                "detectionsource",
                [
                    "birdnet", "perch", "perch_search", "similarity_search",
                    "custom_svm", "human", "sampling_round",
                ],
            ),
            ("detectionstatus", ["unreviewed", "confirmed", "rejected"]),
            ("detectionrunstatus", ["pending", "running", "completed", "failed"]),
            (
                "uploadsessionstatus",
                ["issued", "uploaded", "validating", "validated", "importing", "imported", "failed"],
            ),
            ("uploadfilestatus", ["pending", "uploaded", "valid", "invalid", "imported"]),
            ("searchsessionstatus", ["pending", "running", "completed", "failed"]),
            ("votetype", ["agree", "disagree", "unsure"]),
            (
                "annotationvotesource",
                ["member", "guest_authenticated", "trusted_user"],
            ),
            ("signalquality", ["solo", "dominant", "mixed"]),
            ("consensusstatus", ["needs_votes", "agreed", "rejected", "disputed"]),
            ("annotationsetstatus", ["sampling", "ready", "in_progress", "completed"]),
            ("annotationsegmentstatus", ["unannotated", "annotated", "skipped"]),
            # Phase 11 taxon auto-obscure enums (006-permissions-redesign)
            ("taxonsensitivitysource", ["iucn", "moe_rdb", "manual"]),
            ("taxonoverridedirection", ["stricter", "looser"]),
            (
                "taxonoverrideapprovalstatus",
                ["applied", "pending_superuser_approval", "rejected"],
            ),
        ]
        for type_name, values in enum_defs:
            await conn.execute(sa.text(_make_create_enum_sql(type_name, values)))

        # Phase 13 P1 R2 致命 #1: the stub ``superusers`` Table was
        # registered above (before the early-return) so SA can resolve the
        # ``system_settings.updated_by_id`` FK during ``create_all``. Now
        # we still need to CREATE the real ``superusers`` (and its parent
        # ``users``) **before** the rest of ``create_all`` runs, so the FK
        # constraint emitted on ``system_settings`` does not reference a
        # missing relation.

        # (b) Create ``users`` (ORM table) + raw ``superusers`` upfront.
        users_table = Base.metadata.tables["users"]
        await conn.run_sync(
            lambda c: users_table.create(c, checkfirst=True)
        )
        await conn.execute(
            sa.text(
                """
                CREATE TABLE IF NOT EXISTS superusers (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL UNIQUE
                        REFERENCES users (id) ON DELETE CASCADE,
                    added_by_id UUID NULL REFERENCES users (id),
                    added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    revoked_at TIMESTAMPTZ NULL,
                    webauthn_credentials JSONB NOT NULL DEFAULT '[]'::jsonb,
                    allowed_ip_cidrs VARCHAR[] NOT NULL DEFAULT ARRAY[]::VARCHAR[],
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )

        # Create remaining tables. Filter out the ``superusers`` stub —
        # the real DDL is emitted above. Iterate ``tables.values()``
        # (unsorted; sort still happens internally inside ``create_all``
        # but it can now resolve the stub FK).
        _tables_to_create = [
            t
            for t in Base.metadata.tables.values()
            if not t.info.get("_phase13_stub")
        ]
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=_tables_to_create, checkfirst=True
            )
        )

        # Phase 12 R1 fix: ``outbox_events`` is created by Alembic
        # migration 0001 (no SQLAlchemy ORM model exists yet) so
        # ``Base.metadata.create_all`` does NOT pick it up. Tests that
        # exercise the ownership_service / dormancy_check workers need
        # the table to be present, so we create it idempotently here.
        await conn.execute(
            sa.text(
                """
                CREATE TABLE IF NOT EXISTS outbox_events (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    event_type VARCHAR(100) NOT NULL,
                    payload JSONB NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'pending',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    next_retry_at TIMESTAMPTZ NULL,
                    processed_at TIMESTAMPTZ NULL,
                    last_error TEXT NULL,
                    idempotency_key VARCHAR(128) NULL UNIQUE
                )
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_superusers_revoked_at
                ON superusers (revoked_at)
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_outbox_events_status_next_retry
                ON outbox_events (status, next_retry_at)
                WHERE status IN ('pending', 'processing')
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_outbox_events_event_type_created
                ON outbox_events (event_type, created_at DESC)
                """
            )
        )

        # Phase 15 NO-GO regression: ``superuser_approval_requests`` (Alembic
        # 0001) is not picked up by ``Base.metadata.create_all`` here because
        # the real ORM model declares its FK against ``superusers.id`` which
        # is created by the raw SQL above (the stub copy in metadata had a
        # different shape and was filtered out via ``_phase13_stub``).
        # The Phase 15 fix tests for ``approve_request`` race, duplicate
        # detection, etc. need this table to exist.
        await conn.execute(
            sa.text(
                """
                CREATE TABLE IF NOT EXISTS superuser_approval_requests (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    action VARCHAR(64) NOT NULL,
                    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
                    requested_by_id UUID NOT NULL REFERENCES superusers(id),
                    requesting_user_id UUID NULL REFERENCES users(id),
                    approvals JSONB NOT NULL DEFAULT '[]'::jsonb,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    executed_at TIMESTAMPTZ NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )

        # Phase 2.11 P0-d (Alembic 0002): ``token_families`` and
        # ``refresh_tokens`` back SqlTokenStore. These tables have no ORM
        # model so ``Base.metadata.create_all`` does not create them. Tests
        # in tests/security/csrf/test_samesite_strict.py connect directly to
        # TEST_DATABASE_URL and insert into these tables, so they must be
        # present in the test DB schema.
        await conn.execute(
            sa.text(
                """
                CREATE TABLE IF NOT EXISTS token_families (
                    family_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    revoked_at TIMESTAMPTZ NULL
                )
                """
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_token_families_user_id "
                "ON token_families (user_id)"
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_token_families_revoked_at "
                "ON token_families (revoked_at)"
            )
        )
        await conn.execute(
            sa.text(
                """
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    jti UUID PRIMARY KEY,
                    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    family_id UUID NOT NULL REFERENCES token_families(family_id) ON DELETE CASCADE,
                    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    consumed_at TIMESTAMPTZ NULL,
                    revoked_at TIMESTAMPTZ NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_user_family "
                "ON refresh_tokens (user_id, family_id)"
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_refresh_tokens_expires_at "
                "ON refresh_tokens (expires_at)"
            )
        )
        await conn.execute(
            sa.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_refresh_tokens_family_jti "
                "ON refresh_tokens (family_id, jti)"
            )
        )

        # Phase 13 P1 R2 致命 #1: ``system_settings.updated_by_id`` is now
        # ``NOT NULL`` and FKs ``superusers.id``. The historical conftest
        # seed used to insert four ``registration_mode`` / ``allow_registration``
        # / ``session_timeout_minutes`` / ``setup_completed`` rows with a
        # nullable FK; that path is no longer legal.
        #
        # No live code path *reads* those rows with a fail-required contract
        # — every reader uses ``get_value(default=…)`` and tolerates a
        # missing row — so the seed is now intentionally removed. Tests that
        # need a specific setting must create it via the admin service /
        # repository helpers (which resolve a real ``superusers.id`` first).

        # Phase 16 Batch 6g-2: ``project_audit_log`` and ``platform_audit_log``
        # are created by Alembic 0001 (no ORM model). The Phase 12 R4 /
        # T993 / T993a performance tests write directly to these tables via
        # ``AuditLogService``. The HMAC-chain tables include immutable triggers;
        # we CREATE them with IF NOT EXISTS and skip the trigger recreation if
        # the function already exists (idempotent).
        await conn.execute(
            sa.text(
                """
                CREATE TABLE IF NOT EXISTS project_audit_log (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    actor_user_id_hash VARCHAR(64) NOT NULL,
                    project_id UUID,
                    action VARCHAR(100) NOT NULL,
                    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
                    request_id VARCHAR(64) NOT NULL,
                    ip_hash VARCHAR(64) NOT NULL,
                    user_agent_hash VARCHAR(64) NOT NULL,
                    before JSONB NULL,
                    after JSONB NULL,
                    prev_hash VARCHAR(64) NOT NULL,
                    row_hash VARCHAR(64) NOT NULL,
                    CONSTRAINT ck_project_audit_log_project_id_required
                        CHECK (action = 'genesis' OR project_id IS NOT NULL)
                )
                """
            )
        )
        await conn.execute(
            sa.text(
                "ALTER TABLE project_audit_log "
                "DROP CONSTRAINT IF EXISTS project_audit_log_project_id_fkey"
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_project_audit_log_project_created "
                "ON project_audit_log (project_id, created_at DESC)"
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_project_audit_log_action_created "
                "ON project_audit_log (action, created_at DESC)"
            )
        )
        await conn.execute(
            sa.text(
                """
                CREATE TABLE IF NOT EXISTS platform_audit_log (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    actor_user_id_hash VARCHAR(64) NOT NULL,
                    action VARCHAR(100) NOT NULL,
                    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
                    request_id VARCHAR(64) NOT NULL,
                    ip_hash VARCHAR(64) NOT NULL,
                    user_agent_hash VARCHAR(64) NOT NULL,
                    before JSONB NULL,
                    after JSONB NULL,
                    prev_hash VARCHAR(64) NOT NULL,
                    row_hash VARCHAR(64) NOT NULL
                )
                """
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_platform_audit_log_action_created "
                "ON platform_audit_log (action, created_at DESC)"
            )
        )
        await conn.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_platform_audit_log_actor_created "
                "ON platform_audit_log (actor_user_id_hash, created_at DESC)"
            )
        )
        # Immutable trigger: prevent UPDATE/DELETE on audit log rows.
        # Uses DO $$ block to skip creation if the function already exists.
        await conn.execute(
            sa.text(
                """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_proc
                        WHERE proname = 'prevent_audit_log_mutation'
                    ) THEN
                        CREATE FUNCTION prevent_audit_log_mutation()
                        RETURNS trigger AS $fn$
                        BEGIN
                            RAISE EXCEPTION 'audit log rows are immutable';
                        END;
                        $fn$ LANGUAGE plpgsql;
                    END IF;
                END $$
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                CREATE OR REPLACE FUNCTION validate_project_audit_log_project_exists()
                RETURNS trigger AS $fn$
                BEGIN
                    IF NEW.action <> 'genesis'
                       AND NOT EXISTS (
                           SELECT 1
                           FROM projects p
                           WHERE p.id = NEW.project_id
                       )
                    THEN
                        RAISE EXCEPTION
                            'project_audit_log.project_id must reference an existing project';
                    END IF;
                    RETURN NEW;
                END;
                $fn$ LANGUAGE plpgsql;
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = 'project_audit_log_project_exists'
                    ) THEN
                        CREATE TRIGGER project_audit_log_project_exists
                        BEFORE INSERT ON project_audit_log
                        FOR EACH ROW
                        EXECUTE FUNCTION validate_project_audit_log_project_exists();
                    END IF;
                END $$
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = 'platform_audit_log_immutable'
                    ) THEN
                        CREATE TRIGGER platform_audit_log_immutable
                        BEFORE UPDATE OR DELETE ON platform_audit_log
                        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
                    END IF;
                END $$
                """
            )
        )
        await conn.execute(
            sa.text(
                """
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_trigger
                        WHERE tgname = 'project_audit_log_immutable'
                    ) THEN
                        CREATE TRIGGER project_audit_log_immutable
                        BEFORE UPDATE OR DELETE ON project_audit_log
                        FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
                    END IF;
                END $$
                """
            )
        )

    await _sync_0023_license_schema(engine)
    return



async def cleanup_test_data(session: AsyncSession) -> None:
    """Clean up test data from all tables."""

    def _safe_delete(table: str) -> str:
        """Return DO-block that DELETEs from *table* only if it exists."""
        return (
            f"DO $$ BEGIN IF EXISTS "
            f"(SELECT 1 FROM pg_class WHERE relname='{table}') "
            f"THEN DELETE FROM {table}; END IF; END $$"
        )

    # Delete in correct order (foreign key dependencies)
    # Annotation-related tables must be cleaned before clips/recordings/datasets
    await session.execute(sa.text(_safe_delete("sound_event_annotation_tags")))
    await session.execute(sa.text(_safe_delete("clip_annotation_tags")))
    await session.execute(sa.text(_safe_delete("annotation_project_tags")))
    await session.execute(sa.text(_safe_delete("annotation_project_datasets")))
    await session.execute(sa.text(_safe_delete("notes")))
    await session.execute(sa.text(_safe_delete("sound_event_annotations")))
    await session.execute(sa.text(_safe_delete("clip_annotations")))
    await session.execute(sa.text(_safe_delete("annotation_tasks")))
    await session.execute(sa.text(_safe_delete("annotation_projects")))
    # Annotation voting and comments (006-permissions-redesign)
    await session.execute(sa.text(_safe_delete("annotation_votes")))
    await session.execute(sa.text(_safe_delete("annotation_comments")))
    # Annotation sets / segments / time-range annotations (sampling rounds)
    await session.execute(sa.text(_safe_delete("time_range_annotations")))
    await session.execute(sa.text(_safe_delete("annotation_segments")))
    await session.execute(sa.text(_safe_delete("annotation_sets")))
    await session.execute(sa.text(_safe_delete("sampling_round_items")))
    await session.execute(sa.text(_safe_delete("sampling_rounds")))
    # Upload feature tables (004-upload-tables)
    await session.execute(sa.text(_safe_delete("upload_files")))
    await session.execute(sa.text(_safe_delete("upload_sessions")))
    # Detection review tables (003-detection-review)
    await session.execute(sa.text(_safe_delete("confirmed_regions")))
    await session.execute(sa.text(_safe_delete("annotations")))
    await session.execute(sa.text(_safe_delete("detection_runs")))
    # Evaluation tables
    await session.execute(sa.text(_safe_delete("evaluation_results")))
    await session.execute(sa.text(_safe_delete("evaluation_runs")))
    # Custom models
    await session.execute(sa.text(_safe_delete("custom_models")))
    # Search sessions (0011-search-sessions)
    await session.execute(sa.text(_safe_delete("search_query_embeddings")))
    await session.execute(sa.text(_safe_delete("search_sessions")))
    # Embeddings (ML feature vectors)
    await session.execute(sa.text(_safe_delete("embeddings")))
    # Tags, clips, recordings, datasets, sites
    await session.execute(sa.text(_safe_delete("tags")))
    await session.execute(sa.text(_safe_delete("clips")))
    await session.execute(sa.text(_safe_delete("recordings")))
    await session.execute(sa.text(_safe_delete("datasets")))
    await session.execute(sa.text(_safe_delete("sites")))
    # Project membership / invitations / license history / Trusted overlays.
    # Phase 10 Batch 2: ``project_trusted_users.invitation_id`` references
    # ``project_invitations.id`` so the overlay rows MUST be purged before
    # the parent invitations or the foreign-key constraint blocks the
    # ``DELETE FROM project_invitations``.
    await session.execute(sa.text(_safe_delete("project_trusted_users")))
    await session.execute(sa.text(_safe_delete("project_invitations")))
    await session.execute(sa.text(_safe_delete("project_license_history")))
    await session.execute(sa.text(_safe_delete("project_members")))
    # Phase 15 T155b: api_keys FKs projects.id (project_id) and users.id
    # (user_id). Must be deleted before projects and users.
    await session.execute(sa.text(_safe_delete("api_keys")))
    # project_audit_log is append-only and no longer has a project_id FK, so
    # cleanup must not rewrite audit rows before deleting test projects.
    await session.execute(sa.text(_safe_delete("projects")))
    # Phase 11 taxon auto-obscure tables (006-permissions-redesign)
    await session.execute(sa.text(_safe_delete("project_taxon_sensitivity_overrides")))
    await session.execute(sa.text(_safe_delete("taxon_sensitivities")))
    # Taxon tables
    await session.execute(sa.text(_safe_delete("taxon_vernacular_names")))
    await session.execute(sa.text(_safe_delete("taxa")))
    # Phase 12 R1: outbox events (idempotency dedupe + worker queue).
    await session.execute(sa.text(_safe_delete("outbox_events")))
    # Phase 13 P1 R2 致命 #1: ``system_settings.updated_by_id`` is NOT NULL
    # and FKs ``superusers.id``. The legacy cleanup path nulled the column
    # out so we could ``DELETE FROM users`` next; that is no longer legal.
    # Instead we drop every row and rely on tests to recreate any settings
    # they need via the admin service / repository helpers.
    await session.execute(sa.text(_safe_delete("system_settings")))
    # Phase 17 A-11: 2FA reset workflow tables reference users and
    # superuser_approval_requests. Clear them before those parents.
    await session.execute(sa.text(_safe_delete("two_factor_reset_requests")))
    await session.execute(sa.text(_safe_delete("two_factor_reset_magic_links")))
    await session.execute(sa.text(_safe_delete("two_factor_confirmation_tokens")))
    # Phase 15 NO-GO: M-of-N approval requests have FKs into superusers
    # (requested_by_id) so they must be deleted BEFORE the parent rows
    # below. The table is created in setup_test_database when missing.
    await session.execute(sa.text(_safe_delete("superuser_approval_requests")))
    # Phase 12 R2: superuser allow-list (FR-112a single source of truth).
    # Must be cleared before ``DELETE FROM users`` because of the FK to
    # users.id.
    await session.execute(sa.text(_safe_delete("superusers")))
    # Tokens / login history / notifications
    await session.execute(sa.text(_safe_delete("api_tokens")))
    await session.execute(sa.text(_safe_delete("password_reset_tokens")))
    await session.execute(sa.text(_safe_delete("user_login_notifications_seen")))
    await session.execute(sa.text(_safe_delete("login_attempts")))
    # Phase 2.11 P0-d (Alembic 0002): refresh token family tables. Must be
    # cleaned before users because of the FK(user_id → users.id ON DELETE CASCADE).
    await session.execute(sa.text(_safe_delete("refresh_tokens")))
    await session.execute(sa.text(_safe_delete("token_families")))
    # Clear licenses and recorders
    await session.execute(sa.text(_safe_delete("licenses")))
    await session.execute(sa.text(_safe_delete("recorders")))
    await session.execute(sa.text("DELETE FROM users"))
    await session.commit()


async def seed_canonical_test_licenses(session: AsyncSession) -> None:
    """Ensure canonical Creative Commons license rows exist for FK-backed tests."""
    await session.execute(
        sa.text(
            """
            INSERT INTO licenses (
                id,
                name,
                short_name,
                url,
                description,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :name,
                :short_name,
                :url,
                :description,
                now(),
                now()
            )
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                short_name = EXCLUDED.short_name,
                url = EXCLUDED.url,
                description = EXCLUDED.description,
                updated_at = now()
            """
        ),
        list(CANONICAL_TEST_LICENSES),
    )
    await session.commit()


def ensure_test_database_schema_sync() -> None:
    """Synchronously ensure the test DB schema is current.

    Runs ``setup_test_database`` exactly once. This guarantees that raw-SQL
    tables that are not part of ``Base.metadata`` (e.g. ``token_families``,
    ``refresh_tokens``, ``superuser_approval_requests``, ``project_audit_log``)
    exist even for tests that do NOT use the ``db_session`` fixture (such as
    ``test_samesite_strict.py`` which creates its own engine directly).

    Implemented synchronously (creates and tears down its own event loop)
    so the caller can wrap it in a session-scoped autouse pytest fixture
    without tripping pytest-asyncio's ``ScopeMismatch`` error. A dedicated
    event loop is created and destroyed without touching the main-thread
    event loop policy, to avoid breaking tests that call
    ``asyncio.get_event_loop()`` directly (e.g.
    ``test_url_allowlist_coverage.py::test_build_pinned_async_client``).

    Phase 17 §D-0 follow-up (2026-05-08): previously this ran as a session
    autouse fixture in the *root* ``tests/conftest.py``, which forced every
    test session — including ``tests/runbook/`` smoke tests that have no
    Postgres available — to attempt a connection at session start and crash
    with ``OSError: Multiple exceptions: [Errno 111] Connect call failed``.
    The autouse hook was therefore moved out of the root conftest and into
    per-directory conftests for the suites that genuinely need it
    (``tests/security/``, ``tests/contract/``, ``tests/integration/``,
    ``tests/unit/``, ``tests/performance/``, ``tests/workers/``). Runbook
    smoke tests (which only exercise CLI ``--help`` / argparse stability)
    no longer touch the DB at session setup.
    """
    import asyncio

    async def _run() -> None:
        engine = create_async_engine(
            TEST_DATABASE_URL,
            echo=False,
            poolclass=NullPool,
        )
        try:
            await setup_test_database(engine)
        finally:
            await engine.dispose()

    # Create a brand-new event loop, run setup, then close it — without
    # calling asyncio.set_event_loop so we don't disturb the main-thread
    # event loop that pytest-asyncio or tests may rely on.
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create test database session.

    Each test gets a fresh session with clean data.

    Yields:
        AsyncSession instance
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    # Ensure database is set up
    await setup_test_database(engine)

    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_maker() as session:
        # Clean up any leftover data from previous tests
        await cleanup_test_data(session)
        await seed_canonical_test_licenses(session)
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:  # noqa: ARG002
    """Create test HTTP client with database session override.

    Args:
        db_session: Test database session (ensures DB is set up)

    Yields:
        AsyncClient instance
    """
    # Phase 16 Batch 6c — /api/v1 Bearer JWT drift fix.
    #
    # In production (Phase 15 T155b) ``programmatic_prefix='/api/v1'`` is
    # bound to :class:`DbApiKeyVerifier`, which only accepts the Phase 15
    # ``echoroo_<prefix>_<secret>`` wire format. Legitimate test suites
    # predating Phase 15 still pass plain JWT access tokens (created via
    # :func:`echoroo.core.jwt.create_access_token`) or legacy ``ecr_*``
    # personal API tokens against ``/api/v1/*`` to exercise the RBAC
    # surface — under the Phase 15 surface those tokens 401 with
    # ``auth_invalid``.
    #
    # We patch :meth:`AuthRouterMiddleware._authenticate_api_key`
    # **inside the test client only** (production behaviour is
    # untouched) so the auth-router accepts:
    #
    # * ``echoroo_*`` — original DB-backed verifier (unchanged).
    # * JWT access tokens — synthesise a full-scope :class:`Principal`
    #   so RBAC role-based decisions stay observable. Scope intersection
    #   becomes a no-op because the synthetic principal has every
    #   :class:`Permission` granted.
    # * ``ecr_*`` legacy API tokens — emit the legacy-fallback sentinel
    #   so the downstream ``Depends(get_current_user)`` chain owns
    #   authentication via :class:`TokenService`.
    # * Anything else — fall back to the original verifier (returns
    #   ``None`` → 401), preserving the anti-enumeration posture.
    from uuid import UUID, uuid4

    from echoroo.core.jwt import decode_token
    from echoroo.core.permissions import Permission
    from echoroo.middleware.auth_router import (
        _LEGACY_FALLBACK_SENTINEL,
        AuthRouterMiddleware,
        Principal,
        _auth_failure,
    )
    from echoroo.middleware.two_factor_enforcement import (
        TwoFactorEnforcementMiddleware,
    )

    _ALL_PERMISSION_SCOPES = tuple(p.value for p in Permission)
    _SYNTHETIC_API_KEY_ID = uuid4()

    _original_authenticate_api_key = AuthRouterMiddleware._authenticate_api_key

    async def _patched_authenticate_api_key(
        self: AuthRouterMiddleware, request: Any
    ) -> Any:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            # Reuse production legacy-fallback behaviour.
            return await _original_authenticate_api_key(self, request)

        raw_key = auth_header.split(" ", 1)[1].strip()
        if not raw_key:
            return await _original_authenticate_api_key(self, request)

        # Production-format API keys → preserve original behaviour.
        if raw_key.startswith("echoroo_"):
            return await _original_authenticate_api_key(self, request)

        # Legacy ``ecr_*`` personal API tokens → fall through to the
        # legacy ``Depends`` chain so :class:`TokenService` resolves
        # them. Returning the sentinel mirrors the cookie-only branch
        # of the original verifier.
        if raw_key.startswith("ecr_"):
            return _LEGACY_FALLBACK_SENTINEL

        # Plain JWT access tokens — decode and synthesise a full-scope
        # session-ish principal. We attach an ``api_key_id`` so the
        # downstream ``_stamp_api_key_scopes`` helper still fires; the
        # scope set is ALL :class:`Permission` values so the matrix
        # intersection is a structural no-op (production behaviour
        # for cookie-session callers is the same — the intersection
        # only narrows when a real persisted scope is set).
        try:
            payload = decode_token(raw_key)
        except Exception:  # noqa: BLE001 — bad tokens fall through
            return _auth_failure(401, "auth_invalid", "API key invalid or revoked")

        sub = payload.get("sub")
        if not isinstance(sub, str):
            return _auth_failure(401, "auth_invalid", "API key invalid or revoked")
        try:
            user_uuid = UUID(sub)
        except (TypeError, ValueError):
            return _auth_failure(401, "auth_invalid", "API key invalid or revoked")

        return Principal.for_api_key(
            user_id=user_uuid,
            api_key_id=_SYNTHETIC_API_KEY_ID,
            scopes=_ALL_PERMISSION_SCOPES,
            project_id=None,
        )

    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # PR-C event-loop fix: build the app with the test session factory so
    # that the middleware-level :class:`DbApiKeyVerifier` /
    # :class:`JwtSessionVerifier` / :class:`DbIpEnforcer` open sessions on
    # the test engine (NullPool, current event loop) rather than the
    # module-global production ``AsyncSessionLocal`` bound to a different
    # loop. Without this, positive-path Bearer ``echoroo_*`` requests trip
    # ``RuntimeError: ... attached to a different loop`` from asyncpg.
    app = create_app(session_factory=session_maker)

    # PR-C extension: a long tail of production services (``auth.py``,
    # ``two_factor_service``, ``superuser_service``, ``invitation_service``,
    # the audit writers in ``stream_guard``/``ownership_service``, etc.)
    # call ``async with AsyncSessionLocal() as session:`` directly on the
    # **module-global** production session-maker rather than going through
    # ``Depends(get_db)``. Those direct callers therefore bypass the
    # ``app.dependency_overrides[get_db]`` shim and reach for the
    # production engine, which is bound to whatever event loop happened to
    # initialise it first. When the next test runs on a fresh event loop,
    # asyncpg trips ``RuntimeError: ... attached to a different loop``
    # during ``pool_pre_ping``.
    #
    # We rebind the ``AsyncSessionLocal`` symbol in every module that
    # captured a reference at import time so each direct caller transparently
    # lands on the test engine for the duration of the fixture.
    #
    # PR-C Round 2 (Codex review): switched to ``pytest.MonkeyPatch`` for
    # cleanup discipline and removed the broad ``except Exception`` so a
    # missing/typo'd module fails loudly instead of silently degrading
    # coverage. Constraints / known caveats:
    #
    #   * Concurrency: this rebind mutates **process-global** state and is
    #     therefore safe ONLY when the test session runs sequentially
    #     within a worker. ``pytest-xdist`` is acceptable because each
    #     worker is a separate process; raw threaded test runners are NOT
    #     supported here.
    #   * This is interim debt: the long-term fix is to migrate every
    #     ``async with AsyncSessionLocal() as session:`` direct caller to
    #     ``Depends(get_db)`` (or an injected session factory), at which
    #     point ``app.dependency_overrides[get_db]`` alone is sufficient
    #     and this rebind block can be deleted.
    #   * Refactor candidate: the modules listed below are the current
    #     known set of direct ``AsyncSessionLocal`` callers. Adding a new
    #     direct caller without registering it here will trip a
    #     "different loop" RuntimeError; mypy + the explicit
    #     ``hasattr`` check below catch most regressions, and module
    #     import errors now propagate rather than being swallowed.
    import echoroo.core.database as _db_mod

    _direct_session_local_modules = (
        "echoroo.api.web_v1.auth",
        "echoroo.api.web_v1.audit",
        "echoroo.api.web_v1.admin",
        "echoroo.api.web_v1.auth_confirm_identity",
        "echoroo.api.web_v1.projects._license",
        "echoroo.services.user_deletion_service",
        "echoroo.services.webauthn_service",
        "echoroo.services.two_factor_service",
        "echoroo.services.two_factor_reset_service",
        "echoroo.services.trusted_service",
        "echoroo.services.superuser_service",
        "echoroo.services.superuser_approval_service",
        "echoroo.services.invitation_service",
        "echoroo.services.restricted_config_service",
        "echoroo.services.ownership_service",
        "echoroo.middleware.two_factor_enforcement",
        "echoroo.core.stream_guard",
    )

    # ``pytest.MonkeyPatch()`` returns a fresh, manually-managed
    # ``MonkeyPatch`` object whose ``undo()`` restores every recorded
    # attribute in LIFO order — exactly the discipline the previous
    # hand-rolled list+reversed loop maintained, but tied to pytest's
    # canonical cleanup machinery rather than ad-hoc ``setattr`` calls.
    _session_monkeypatch = pytest.MonkeyPatch()
    _session_monkeypatch.setattr(
        _db_mod, "AsyncSessionLocal", session_maker, raising=True
    )
    for _modname in _direct_session_local_modules:
        # ``import_module`` is allowed to raise — a missing entry in this
        # tuple means the production module was renamed/removed and the
        # rebind list is stale. Fail loudly so the fixture maintainer
        # notices, rather than silently leaking the production
        # ``AsyncSessionLocal`` binding into the test session.
        _mod = importlib.import_module(_modname)
        # ``raising=True`` enforces the contract that every listed module
        # MUST expose ``AsyncSessionLocal`` at import time; if a module
        # legitimately stops needing the rebind it should be removed
        # from ``_direct_session_local_modules`` rather than tolerated.
        _session_monkeypatch.setattr(
            _mod, "AsyncSessionLocal", session_maker, raising=True
        )

    # Override get_db dependency
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Phase 5 polish round 3 (重要1): override AudioService so its S3 cache
    # directory points at a writable tmp dir rather than the hard-coded
    # ``/data/s3_audio_cache``. Tests (especially the Guest audio surface
    # in test_guest_public_access.py) trip over the ``/data/`` mkdir when
    # the runner has no write permission there. We pin the override to a
    # process-wide tmp dir so successive tests share the same cache.
    settings = get_settings()
    audio_cache_tmp_root = Path(tempfile.gettempdir()) / "echoroo-test-s3-audio-cache"
    audio_cache_tmp_root.mkdir(parents=True, exist_ok=True)

    def override_get_audio_service() -> AudioService:
        return AudioService(
            settings.AUDIO_ROOT,
            settings.AUDIO_CACHE_DIR,
            s3_audio_cache_dir=str(audio_cache_tmp_root),
        )

    # Register every route-local factory that constructs AudioService.
    app.dependency_overrides[_get_audio_service_clips] = override_get_audio_service
    app.dependency_overrides[_get_audio_service_datasets] = override_get_audio_service
    app.dependency_overrides[_get_audio_service_recordings] = override_get_audio_service

    # Patch RateLimiter.__call__ with a no-op that uses correct FastAPI types
    # so they are injected rather than treated as query params
    from starlette.requests import Request
    from starlette.responses import Response

    async def _noop_rate_limiter(
        self: Any,  # noqa: ARG001
        request: Request,  # noqa: ARG001
        response: Response,  # noqa: ARG001
    ) -> None:
        pass

    # Apply the AuthRouter patch via direct attribute assignment so it
    # survives starlette's lazy middleware-stack construction. The
    # ``patch.object`` context manager does NOT take effect here because
    # the middleware stack is built on first request after the context
    # has already restored the original method.
    AuthRouterMiddleware._authenticate_api_key = _patched_authenticate_api_key  # type: ignore[method-assign]

    # Phase 16 Batch 6c — bypass the 2FA enforcement middleware in
    # tests. Pre-Phase-4 fixtures create :class:`User` rows without
    # ``two_factor_enabled=True``; the production middleware (added in
    # Phase 4 / T155b) blocks every authenticated ``/api/v1/*`` and
    # ``/web-api/v1/*`` request with 403 ``2FA enrollment required``
    # before the route handler runs. Phase-4-aware suites
    # (``test_two_factor_enforcement_real_chain.py``, ``test_two_factor_setup_*``)
    # build their own apps without this override and therefore continue
    # to exercise the real enforcement chain.
    _original_two_factor_dispatch = TwoFactorEnforcementMiddleware.dispatch

    async def _patched_two_factor_dispatch(
        self: TwoFactorEnforcementMiddleware,
        request: Any,
        call_next: Any,
    ) -> Any:
        # Pass through unconditionally; production enforcement is locked
        # in by dedicated middleware suites.
        return await call_next(request)

    TwoFactorEnforcementMiddleware.dispatch = _patched_two_factor_dispatch  # type: ignore[method-assign]

    with patch(
        "fastapi_limiter.depends.RateLimiter.__call__",
        _noop_rate_limiter,
    ):
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as test_client:
                yield test_client
        finally:
            # Restore the original method so unrelated unit-test
            # suites (which build their own apps) see production
            # behaviour.
            AuthRouterMiddleware._authenticate_api_key = (  # type: ignore[method-assign]
                _original_authenticate_api_key
            )
            TwoFactorEnforcementMiddleware.dispatch = (  # type: ignore[method-assign]
                _original_two_factor_dispatch
            )
            # PR-C Round 2: restore each module-level
            # ``AsyncSessionLocal`` we rebound above so subsequent suites
            # that build their own apps see the production binding
            # again. ``MonkeyPatch.undo()`` walks its internal record in
            # LIFO order, so the canonical ``echoroo.core.database``
            # symbol — the first entry recorded — is restored last,
            # matching the discipline expected by any inner
            # ``importlib.reload``.
            _session_monkeypatch.undo()

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    """Configure anyio backend for async tests.

    Returns:
        Backend name
    """
    return "asyncio"
