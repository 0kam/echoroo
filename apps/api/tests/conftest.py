"""Pytest configuration and fixtures."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from echoroo.core.database import get_db
from echoroo.main import create_app
from echoroo.models.base import Base

# Test database URL (use different database for tests)
TEST_DATABASE_URL = "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test"


@pytest.fixture(scope="function")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests.

    Yields:
        Event loop instance
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create test database engine.

    Yields:
        AsyncEngine instance for test database
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=NullPool,
    )

    # Create all tables and enum types
    async with engine.begin() as conn:
        # Create enum types first
        await conn.execute(
            sa.text(
                "DO $$ BEGIN "
                "CREATE TYPE project_visibility AS ENUM ('private', 'public'); "
                "EXCEPTION WHEN duplicate_object THEN null; END $$;"
            )
        )
        await conn.execute(
            sa.text(
                "DO $$ BEGIN "
                "CREATE TYPE project_role AS ENUM ('admin', 'member', 'viewer'); "
                "EXCEPTION WHEN duplicate_object THEN null; END $$;"
            )
        )
        await conn.execute(
            sa.text(
                "DO $$ BEGIN "
                "CREATE TYPE setting_type AS ENUM ('string', 'number', 'boolean', 'json'); "
                "EXCEPTION WHEN duplicate_object THEN null; END $$;"
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

    yield engine

    # Drop all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        # Drop enum types
        await conn.execute(sa.text("DROP TYPE IF EXISTS setting_type CASCADE"))
        await conn.execute(sa.text("DROP TYPE IF EXISTS project_role CASCADE"))
        await conn.execute(sa.text("DROP TYPE IF EXISTS project_visibility CASCADE"))

    await engine.dispose()


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session with transaction rollback.

    Each test gets a fresh session that rolls back all changes.

    Args:
        engine: Test database engine

    Yields:
        AsyncSession instance
    """
    connection = await engine.connect()
    transaction = await connection.begin()

    # Create session bound to the connection
    async_session_maker = sessionmaker(
        connection, class_=AsyncSession, expire_on_commit=False
    )
    session = async_session_maker()

    # Disable commit to force rollback
    @event.listens_for(session.sync_session, "after_transaction_end")
    def restart_savepoint(session: Any, transaction: Any) -> None:
        if transaction.nested and not transaction._parent.nested:
            session.begin_nested()

    yield session

    await session.close()
    await transaction.rollback()
    await connection.close()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client with database session override.

    Args:
        db_session: Test database session

    Yields:
        AsyncClient instance
    """
    app = create_app()

    # Override get_db dependency
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def anyio_backend() -> str:
    """Configure anyio backend for async tests.

    Returns:
        Backend name
    """
    return "asyncio"
