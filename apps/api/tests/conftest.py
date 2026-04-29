"""Pytest configuration and fixtures."""

import os
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
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

from echoroo.api.v1.recordings import get_audio_service
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

    if (
        core_exists
        and search_exists
        and taxon_sensitivity_exists
        and outbox_exists
        and superusers_exists
        and approval_requests_exists
    ):
        # Schema is fully up to date — nothing to do.
        return

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
    # Clear licenses and recorders
    await session.execute(sa.text(_safe_delete("licenses")))
    await session.execute(sa.text(_safe_delete("recorders")))
    await session.execute(sa.text("DELETE FROM users"))
    await session.commit()


@pytest.fixture
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
        yield session

    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:  # noqa: ARG002
    """Create test HTTP client with database session override.

    Args:
        db_session: Test database session (ensures DB is set up)

    Yields:
        AsyncClient instance
    """
    app = create_app()

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

    app.dependency_overrides[get_audio_service] = override_get_audio_service

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

    with patch(
        "fastapi_limiter.depends.RateLimiter.__call__",
        _noop_rate_limiter,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as test_client:
            yield test_client

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    """Configure anyio backend for async tests.

    Returns:
        Backend name
    """
    return "asyncio"
