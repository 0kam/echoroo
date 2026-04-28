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

    if (
        core_exists
        and search_exists
        and taxon_sensitivity_exists
        and outbox_exists
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
            ("setting_type", ["string", "number", "boolean", "json"]),
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

        # Create all tables that don't already exist.
        # Use checkfirst=True to skip tables that are already present so that
        # existing indexes are not re-emitted (which would cause DuplicateTableError
        # for tables that SQLAlchemy also generates auto-indexes for).
        await conn.run_sync(lambda c: Base.metadata.create_all(c, checkfirst=True))

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

        await conn.execute(
            sa.text(
                """
                INSERT INTO system_settings (key, value, value_type, description, updated_at)
                VALUES
                    ('registration_mode', '"open"', 'string', 'User registration mode: open or invitation', CURRENT_TIMESTAMP),
                    ('session_timeout_minutes', '120', 'number', 'Session timeout in minutes', CURRENT_TIMESTAMP),
                    ('allow_registration', 'true', 'boolean', 'Whether new user registration is allowed', CURRENT_TIMESTAMP),
                    ('setup_completed', 'false', 'boolean', 'Whether initial setup has been completed', CURRENT_TIMESTAMP)
                ON CONFLICT (key) DO NOTHING
                """
            )
        )

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
    # Tokens / login history / notifications
    await session.execute(sa.text(_safe_delete("api_tokens")))
    await session.execute(sa.text(_safe_delete("password_reset_tokens")))
    await session.execute(sa.text(_safe_delete("user_login_notifications_seen")))
    await session.execute(sa.text(_safe_delete("login_attempts")))
    # Clear licenses and recorders
    await session.execute(sa.text(_safe_delete("licenses")))
    await session.execute(sa.text(_safe_delete("recorders")))
    # Clear system_settings references to users before deleting users
    await session.execute(sa.text("UPDATE system_settings SET updated_by_id = NULL"))
    await session.execute(sa.text("DELETE FROM users"))
    # Reset setup_completed for setup tests
    await session.execute(
        sa.text("UPDATE system_settings SET value = 'false' WHERE key = 'setup_completed'")
    )
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
