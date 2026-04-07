"""Shared database session factory for Celery workers.

All Celery task modules should use ``get_worker_engine_and_session_factory()``
instead of creating their own engine/sessionmaker, and must dispose the engine
in a ``finally`` block after the task's ``asyncio.run()`` call completes.

Design rationale
----------------
Each Celery task calls ``asyncio.run()`` which creates a *new* event loop.
Reusing a cached SQLAlchemy async engine across different event loops causes
"Future attached to a different loop" errors.  Therefore a fresh engine must
be created per task invocation.  The caller is responsible for disposing the
engine after use so that all connection-pool connections are released cleanly.

Typical usage
-------------
::

    from echoroo.workers.db_utils import get_worker_engine_and_session_factory

    def my_celery_task(...) -> ...:
        return asyncio.run(_my_async_impl(...))

    async def _my_async_impl(...) -> ...:
        engine, session_factory = get_worker_engine_and_session_factory()
        try:
            async with session_factory() as db:
                ...
        finally:
            await engine.dispose()
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from echoroo.core.settings import get_settings


def get_worker_engine_and_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create a fresh async engine and session factory for one task invocation.

    Returns the engine separately so the caller can dispose it in a ``finally``
    block after the task completes, releasing all pooled connections back to
    PostgreSQL.

    Returns:
        A tuple of ``(engine, session_factory)`` where ``session_factory`` is
        an ``async_sessionmaker`` bound to the newly created engine.
    """
    settings = get_settings()
    engine: AsyncEngine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
    )
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, session_factory
