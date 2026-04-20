"""Pytest configuration and fixtures."""

import os
from collections.abc import AsyncGenerator
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

from echoroo.core.database import get_db
from echoroo.main import create_app
from echoroo.models.base import Base

# Test database URL — override via TEST_DATABASE_URL env var to allow running
# from inside Docker containers where the DB is accessible via a service hostname
# rather than localhost (e.g. TEST_DATABASE_URL=postgresql+asyncpg://echoroo:echoroo@db:5432/echoroo_test).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


def _deduplicate_metadata_indexes() -> None:
    """Remove duplicate index objects from SQLAlchemy metadata tables.

    The SearchSession model has a duplicate index: TimestampMixin.created_at
    uses ``index=True`` which auto-generates ``ix_search_sessions_created_at``,
    AND ``__table_args__`` contains an explicit ``Index`` with the same name.
    SQLAlchemy stores both in the table's ``.indexes`` set, which causes
    ``DuplicateTableError`` when ``create_all`` emits both CREATE INDEX statements.

    This function deduplicates all table indexes by name, keeping only the first
    occurrence, so ``create_all`` succeeds.  It modifies the module-level
    ``Base.metadata`` in place — safe to call once before ``create_all``.
    """
    for table in Base.metadata.sorted_tables:
        seen: set[str | None] = set()
        to_remove = []
        for idx in list(table.indexes):
            if idx.name in seen:
                to_remove.append(idx)
            else:
                seen.add(idx.name)
        for idx in to_remove:
            table.indexes.discard(idx)


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

    if core_exists and search_exists:
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
            ("projectvisibility", ["private", "public"]),
            ("projectrole", ["admin", "member", "viewer"]),
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
            ("detectionsource", ["birdnet", "perch_search", "human"]),
            ("detectionstatus", ["unreviewed", "confirmed", "rejected"]),
            ("detectionrunstatus", ["pending", "running", "completed", "failed"]),
            (
                "uploadsessionstatus",
                ["issued", "uploaded", "validating", "validated", "importing", "imported", "failed"],
            ),
            ("uploadfilestatus", ["pending", "uploaded", "valid", "invalid", "imported"]),
            ("searchsessionstatus", ["pending", "running", "completed", "failed"]),
        ]
        for type_name, values in enum_defs:
            await conn.execute(sa.text(_make_create_enum_sql(type_name, values)))

        # Deduplicate indexes in SQLAlchemy metadata before calling create_all.
        # SearchSession has a duplicate index (TimestampMixin.created_at index=True
        # and an explicit Index in __table_args__ share the same auto-generated name).
        # We remove the duplicate in-place here to avoid DuplicateTableError.
        _deduplicate_metadata_indexes()

        # Create all tables that don't already exist.
        # Use checkfirst=True to skip tables that are already present so that
        # existing indexes are not re-emitted (which would cause DuplicateTableError
        # for tables that SQLAlchemy also generates auto-indexes for).
        await conn.run_sync(lambda c: Base.metadata.create_all(c, checkfirst=True))

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
    # Delete in correct order (foreign key dependencies)
    # Annotation-related tables must be cleaned before clips/recordings/datasets
    await session.execute(sa.text("DELETE FROM sound_event_annotation_tags"))
    await session.execute(sa.text("DELETE FROM clip_annotation_tags"))
    await session.execute(sa.text("DELETE FROM annotation_project_tags"))
    await session.execute(sa.text("DELETE FROM annotation_project_datasets"))
    await session.execute(sa.text("DELETE FROM notes"))
    await session.execute(sa.text("DELETE FROM sound_event_annotations"))
    await session.execute(sa.text("DELETE FROM clip_annotations"))
    await session.execute(sa.text("DELETE FROM annotation_tasks"))
    await session.execute(sa.text("DELETE FROM annotation_projects"))
    # Upload feature tables (004-upload-tables)
    await session.execute(sa.text("DELETE FROM upload_files"))
    await session.execute(sa.text("DELETE FROM upload_sessions"))
    # Detection review tables (003-detection-review)
    await session.execute(sa.text("DELETE FROM confirmed_regions"))
    await session.execute(sa.text("DELETE FROM annotations"))
    await session.execute(sa.text("DELETE FROM detection_runs"))
    # Search sessions (0011-search-sessions)
    # Use DO blocks so cleanup is safe even before the targeted migration runs.
    await session.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_class WHERE relname='search_sessions') "
            "THEN DELETE FROM search_sessions; END IF; END $$"
        )
    )
    # Embeddings (ML feature vectors)
    await session.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_class WHERE relname='embeddings') "
            "THEN DELETE FROM embeddings; END IF; END $$"
        )
    )
    await session.execute(sa.text("DELETE FROM tags"))
    await session.execute(sa.text("DELETE FROM clips"))
    await session.execute(sa.text("DELETE FROM recordings"))
    await session.execute(sa.text("DELETE FROM datasets"))
    await session.execute(sa.text("DELETE FROM sites"))
    await session.execute(sa.text("DELETE FROM project_invitations"))
    await session.execute(sa.text("DELETE FROM project_members"))
    await session.execute(sa.text("DELETE FROM projects"))
    await session.execute(sa.text("DELETE FROM api_tokens"))
    await session.execute(sa.text("DELETE FROM login_attempts"))
    # Clear licenses and recorders
    await session.execute(sa.text("DELETE FROM licenses"))
    await session.execute(sa.text("DELETE FROM recorders"))
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
