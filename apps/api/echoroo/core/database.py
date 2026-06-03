"""Database connection and session management."""

import sys
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core.settings import get_settings

settings = get_settings()

# Under pytest, the module-global engine is shared across every test, but each
# test runs on its own function-scoped event loop (pytest-asyncio default).
# SQLAlchemy's default ``AsyncAdaptedQueuePool`` keeps asyncpg connections alive
# between checkouts; a connection opened on test A's event loop lingers in the
# pool and is later reused (or terminated) on test B's *fresh* loop. asyncpg
# then calls ``self._loop.create_task(...)`` against the now-closed loop, which
# raises ``RuntimeError: Event loop is closed`` (and the sibling
# "got Future ... attached to a different loop"). This surfaced as a flaky,
# order-dependent failure in the ``backend-tests`` / ``security-tests`` CI gates
# — most visibly in the FR-088 soft-alert audit writers (superuser_service /
# trusted_device_service) that open a *fresh* ``AsyncSessionLocal`` on the
# global engine, including in suites that build their own app and therefore do
# not go through the ``client`` fixture's per-module rebind.
#
# ``NullPool`` opens and fully closes a brand-new connection per checkout, so no
# connection is ever retained across event loops and the cross-loop reaping path
# cannot fire. Production (non-pytest) behaviour is unchanged: it keeps the
# pre-ping ``QueuePool`` sizing below. The signal — ``"pytest" in sys.modules``
# — is true at import time during collection (verified) and false in the
# uvicorn / celery runtime.
_UNDER_PYTEST = "pytest" in sys.modules

if _UNDER_PYTEST:
    # Connection-per-checkout: loop-safe across function-scoped event loops.
    engine: AsyncEngine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        poolclass=NullPool,
    )
else:
    # Create async engine (production / runtime: pooled with pre-ping).
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session dependency.

    Yields:
        AsyncSession: Database session that will be automatically closed

    Example:
        ```python
        @router.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(User))
            return result.scalars().all()
        ```
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Type annotation for dependency injection
DbSession = Annotated[AsyncSession, Depends(get_db)]
