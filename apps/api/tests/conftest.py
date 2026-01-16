"""Pytest configuration and fixtures."""

from collections.abc import AsyncGenerator

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

# Test database URL (use different database for tests)
TEST_DATABASE_URL = "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test"


async def setup_test_database(engine: AsyncEngine) -> None:
    """Set up test database schema and enum types."""
    # Check if tables exist
    async with engine.connect() as conn:
        result = await conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"
            )
        )
        tables_exist = result.scalar()

    if tables_exist:
        return

    async with engine.begin() as conn:
        # Fully reset schema
        await conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(sa.text("CREATE SCHEMA public"))

        # Create enum types first (must match SQLAlchemy enum names)
        await conn.execute(
            sa.text("CREATE TYPE projectvisibility AS ENUM ('private', 'public')")
        )
        await conn.execute(
            sa.text("CREATE TYPE projectrole AS ENUM ('admin', 'member', 'viewer')")
        )
        await conn.execute(
            sa.text(
                "CREATE TYPE setting_type AS ENUM ('string', 'number', 'boolean', 'json')"
            )
        )
        await conn.execute(
            sa.text("CREATE TYPE datasetvisibility AS ENUM ('private', 'public')")
        )
        await conn.execute(
            sa.text(
                "CREATE TYPE datasetstatus AS ENUM ('pending', 'scanning', 'processing', 'completed', 'failed')"
            )
        )
        await conn.execute(
            sa.text(
                "CREATE TYPE datetimeparsestatus AS ENUM ('pending', 'success', 'failed')"
            )
        )
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)

        # Insert default system settings
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


async def cleanup_test_data(session: AsyncSession) -> None:
    """Clean up test data from all tables."""
    # Delete in correct order (foreign key dependencies)
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
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
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
            yield session

    app.dependency_overrides[get_db] = override_get_db

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
