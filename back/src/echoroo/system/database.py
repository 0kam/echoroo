"""Function to initialize the database."""

import logging
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import AsyncGenerator

from alembic import script
from alembic.command import stamp, upgrade
from alembic.config import Config
from alembic.runtime import migration
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from echoroo import models
from echoroo.system.settings import Settings

logger = logging.getLogger("echoroo.database")

__all__ = [
    "create_async_db_engine",
    "create_db",
    "create_or_update_db",
    "create_async_db_engine",
    "create_sync_db_engine",
    "enable_pgvector_extension",
    "get_database_url",
    "get_db_state",
    "init_database",
    "is_postgresql",
    "get_async_session",
    "models",
    "run_migrations",
    "validate_database_url",
]


class DatabaseState(int, Enum):
    """The state of the database."""

    OK = 0
    NEEDS_MIGRATION = 1
    NEEDS_CREATION = 2
    CANNOT_CONNECT = 3
    UNKNOWN = 4


MIGRATIONS_PATH = Path(__file__).parent.parent / "migrations" / "versions"


def is_postgresql(db_url: URL) -> bool:
    """Check if the database URL is for PostgreSQL."""
    backend = db_url.get_backend_name()
    return backend == "postgresql"


def validate_database_url(database_url: URL, is_async: bool = False) -> URL:
    """Validate the database url.

    Parameters
    ----------
    database_url : str
        The url to the database. Defaults to `sqlite://`. See
        https://docs.sqlalchemy.org/en/14/core/engines.html#database-urls for
        more information on the format.
    async : bool
        Whether the database should be accessed asynchronously. Defaults to
        `False`.

    Returns
    -------
    str
        The validated database url.
    """
    backend = database_url.get_backend_name()
    if backend == "sqlite":
        if is_async:
            return database_url.set(drivername="sqlite+aiosqlite")
        return database_url.set(drivername="sqlite")

    if backend == "postgresql":
        if is_async:
            return database_url.set(drivername="postgresql+asyncpg")
        return database_url.set(drivername="postgresql+psycopg2")

    return database_url


def get_database_url(
    settings: Settings,
    is_async: bool = True,
) -> URL:
    """Get the database url.

    Parameters
    ----------
    settings : Settings
        The settings for the application.
    async : bool
        Whether the database should be accessed asynchronously. Defaults to
        `False`.

    Returns
    -------
    URL
        The database url.
    """
    db_url = settings.db_url

    if settings.dev and db_url is None:
        db_url = (
            "sqlite+aiosqlite:///echoroo.db"
            if is_async
            else "sqlite:///echoroo.db"
        )

    if db_url:
        return make_url(db_url)

    url = URL.create(
        drivername=settings.db_dialect,
        username=settings.db_username,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )

    return validate_database_url(url, is_async=is_async)


def create_async_db_engine(database_url: str | URL) -> AsyncEngine:
    """Create the database engine.

    Parameters
    ----------
    database_url : str
        The url to the database. Defaults to `sqlite+aiosqlite://`. See
        https://docs.sqlalchemy.org/en/14/core/engines.html#database-urls for
        more information on the format.

    Notes
    -----
    If using sqlite, you need to install the `aiosqlite` package and
    include `+aiosqlite` in the url to support asynchronous operations.

    Returns
    -------
    AsyncEngine
        The database engine.
    """
    if not isinstance(database_url, URL):
        database_url = make_url(database_url)

    database_url = validate_database_url(database_url, is_async=True)

    # PostgreSQL-specific optimizations
    if is_postgresql(database_url):
        return create_async_engine(
            database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # Connection health check
            pool_recycle=3600,  # Recycle connections after 1 hour
        )

    return create_async_engine(database_url)


def create_sync_db_engine(database_url: str | URL) -> Engine:
    """Create the database engine.

    Parameters
    ----------
    database_url : str
        The url to the database. Defaults to `sqlite://`. See
        https://docs.sqlalchemy.org/en/14/core/engines.html#database-urls for
        more information on the format.

    Returns
    -------
    Engine
        The database engine.
    """
    if not isinstance(database_url, URL):
        database_url = make_url(database_url)
    database_url = validate_database_url(database_url, is_async=False)
    return create_engine(database_url)


def create_alembic_config(db_url: str | URL, is_async: bool = True) -> Config:
    """Create the Alembic configurations."""
    if not isinstance(db_url, URL):
        db_url = make_url(db_url)
    db_url = validate_database_url(db_url, is_async=is_async)

    cfg = Config()
    cfg.set_main_option("script_location", "echoroo:migrations")
    cfg.set_main_option("sqlalchemy.url", db_url.render_as_string())

    # NOTE: Pass the database url to the config so that we can use it in the
    # migrations scripts.
    cfg.attributes["db_url"] = db_url
    cfg.attributes["should_run_async"] = is_async
    return cfg


def get_current_revisions(conn: Connection) -> set:
    """Check the database state."""
    context = migration.MigrationContext.configure(conn)
    return set(context.get_current_heads())


def get_db_state(conn: Connection, cfg: Config) -> DatabaseState:
    """Get the state of the database.

    Parameters
    ----------
    cfg
        The Alembic configuration.
    conn
        The database connection.

    Returns
    -------
    DatabaseState
        The state of the database.
    """
    directory = script.ScriptDirectory.from_config(cfg)
    head_rev = set(directory.get_heads())
    current_rev = get_current_revisions(conn)

    if not current_rev:
        return DatabaseState.NEEDS_CREATION

    if current_rev != head_rev:
        return DatabaseState.NEEDS_MIGRATION

    return DatabaseState.OK


def run_migrations(cfg: Config) -> None:
    """Run the database migrations."""
    upgrade(cfg, "head")


def create_db(conn: Connection, cfg: Config) -> None:
    """Create the database."""
    models.Base.metadata.create_all(conn)
    stamp(cfg, "head")


def create_or_update_db(conn: Connection, cfg: Config) -> None:
    """Create the database and tables."""
    state = get_db_state(conn, cfg)

    if state == DatabaseState.OK:
        return

    if state == DatabaseState.UNKNOWN:
        raise RuntimeError("Unknown database state.")

    if state == DatabaseState.NEEDS_CREATION:
        create_db(conn, cfg)

    run_migrations(cfg)


@asynccontextmanager
async def get_async_session(
    engine: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    """Get a session to the database asynchronously."""
    async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session_maker() as session:
        yield session


def is_sqlite(dbapi_connection: DBAPIConnection) -> bool:
    dbapi = getattr(dbapi_connection, "dbapi", None)
    return dbapi is not None and hasattr(dbapi, "sqlite_version")


@event.listens_for(Engine, "connect")
def enable_foreign_key_support_sqlite(dbapi_connection: DBAPIConnection, _):
    if not is_sqlite(dbapi_connection):
        return

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


async def enable_pgvector_extension(engine: AsyncEngine) -> None:
    """Enable pgvector extension for PostgreSQL.

    This function enables the pgvector extension which is required for
    storing and querying ML model embeddings.

    Parameters
    ----------
    engine : AsyncEngine
        The database engine.

    Notes
    -----
    This function is a no-op if the extension is already enabled.
    It requires the pgvector extension to be installed on the PostgreSQL server.
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    logger.info("pgvector extension enabled")


async def init_database(settings: Settings) -> None:
    """Create the database and tables on startup."""
    db_url = get_database_url(settings)
    engine = create_async_db_engine(db_url)

    # Enable pgvector extension for PostgreSQL
    if is_postgresql(db_url):
        try:
            await enable_pgvector_extension(engine)
        except Exception as e:
            logger.warning(
                f"Failed to enable pgvector extension: {e}. "
                "ML embedding similarity search will not be available. "
                "To enable, ensure pgvector is installed on your PostgreSQL server."
            )

    async with engine.begin() as conn:
        cfg = create_alembic_config(db_url, is_async=False)
        await conn.run_sync(create_or_update_db, cfg)
