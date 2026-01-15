import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import URL, Connection, engine_from_config
from sqlalchemy.ext.asyncio import async_engine_from_config

from echoroo import models
from echoroo.system import get_settings
from echoroo.system.database import get_database_url, is_postgresql

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except KeyError:
        # Ignore KeyError as it is raised when the config file does not contain
        pass

# add your model's MetaData object here
target_metadata = models.Base.metadata


# Check if we should run migrations asynchronously
should_run_async = config.attributes.get("should_run_async", True)


def get_url() -> URL:
    """Get database URL."""
    if "db_url" in config.attributes:
        return config.attributes["db_url"]

    settings = get_settings()
    db_url = get_database_url(settings)
    return db_url


def get_configurations() -> dict:
    """Get Alembic configurations."""
    configuration = config.get_section(config.config_ini_section)
    if configuration is None:
        raise RuntimeError("No alembic configuration found")
    configuration["sqlalchemy.url"] = get_url()  # type: ignore
    return configuration


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well.  By skipping the Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the script
    output.
    """
    url = get_url()
    # render_as_batch is required for SQLite to support ALTER TABLE operations
    # For PostgreSQL, it's not needed but doesn't cause issues
    render_as_batch = not is_postgresql(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=render_as_batch,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Determine render_as_batch based on database dialect
    # render_as_batch is required for SQLite to support ALTER TABLE operations
    dialect_name = connection.dialect.name
    render_as_batch = dialect_name == "sqlite"
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=render_as_batch,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations() -> None:
    """Run migrations synchronously."""
    configuration = get_configurations()

    connectable = engine_from_config(
        configuration,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


async def run_async_migrations() -> None:
    """Run migrations asynchronously."""
    configuration = get_configurations()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    if should_run_async:
        asyncio.run(run_async_migrations())
        return

    run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
