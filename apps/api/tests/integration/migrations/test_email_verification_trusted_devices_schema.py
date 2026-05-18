"""Schema coverage for email verification and trusted-device persistence.

T005 is intentionally written before the migration/model implementation tasks.
It should fail until the Alembic migration adds:

* ``users.email_verified_at``
* ``email_verification_tokens``
* ``trusted_devices``
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dependency is declared in dev extras
    PostgresContainer = None  # type: ignore[assignment,misc]


API_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = API_ROOT / "alembic.ini"


@dataclass(frozen=True)
class ExpectedColumn:
    data_type: str
    udt_name: str
    nullable: bool
    max_length: int | None = None
    has_default: bool = False


EXPECTED_COLUMNS: dict[str, dict[str, ExpectedColumn]] = {
    "users": {
        "email_verified_at": ExpectedColumn(
            data_type="timestamp with time zone",
            udt_name="timestamptz",
            nullable=True,
        ),
    },
    "email_verification_tokens": {
        "id": ExpectedColumn("uuid", "uuid", nullable=False, has_default=True),
        "user_id": ExpectedColumn("uuid", "uuid", nullable=False),
        "email_normalized": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=False,
            max_length=255,
        ),
        "token_hash": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=False,
            max_length=64,
        ),
        "purpose": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=False,
            max_length=64,
        ),
        "expires_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=False,
        ),
        "consumed_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=True,
        ),
        "superseded_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=True,
        ),
        "created_ip_hash": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=True,
            max_length=64,
        ),
        "created_user_agent_hash": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=True,
            max_length=64,
        ),
        "created_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=False,
            has_default=True,
        ),
        "updated_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=False,
            has_default=True,
        ),
    },
    "trusted_devices": {
        "id": ExpectedColumn("uuid", "uuid", nullable=False, has_default=True),
        "user_id": ExpectedColumn("uuid", "uuid", nullable=False),
        "device_secret_hash": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=False,
            max_length=64,
        ),
        "security_stamp": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=False,
            max_length=64,
        ),
        "label": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=True,
            max_length=100,
        ),
        "created_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=False,
            has_default=True,
        ),
        "last_used_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=True,
        ),
        "expires_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=False,
        ),
        "revoked_at": ExpectedColumn(
            "timestamp with time zone",
            "timestamptz",
            nullable=True,
        ),
        "last_ip_hash": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=True,
            max_length=64,
        ),
        "last_user_agent_hash": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=True,
            max_length=64,
        ),
        "created_ip_hash": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=True,
            max_length=64,
        ),
        "created_user_agent_hash": ExpectedColumn(
            "character varying",
            "varchar",
            nullable=True,
            max_length=64,
        ),
    },
}


@pytest.fixture(scope="module")
def pg_container() -> Iterator[PostgresContainer]:
    """Spin up a throwaway PostgreSQL 16 container for migration checks."""

    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")

    container = PostgresContainer("pgvector/pgvector:pg16")
    container.start()
    try:
        yield container
    finally:
        container.stop()


def _admin_url(container: PostgresContainer) -> str:
    sync_url = container.get_connection_url()
    return sync_url.replace("postgresql+psycopg2://", "postgresql://")


def _create_isolated_db(admin_url: str, db_name: str) -> str:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            conn.execute(sa.text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()

    base, _, _ = admin_url.rpartition("/")
    return f"{base}/{db_name}"


def _alembic_upgrade(sync_url: str) -> None:
    async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")
    env = {
        **os.environ,
        "DATABASE_URL": async_url,
        "ALEMBIC_SYNC_URL": sync_url,
    }
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_INI),
            "upgrade",
            "head",
        ],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "alembic upgrade head failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


@pytest.fixture(scope="module")
def upgraded_engine(pg_container: PostgresContainer) -> Iterator[Engine]:
    admin_url = _admin_url(pg_container)
    sync_url = _create_isolated_db(admin_url, "echoroo_010_email_trusted_schema")
    _alembic_upgrade(sync_url)

    engine = create_engine(sync_url)
    try:
        yield engine
    finally:
        engine.dispose()


def _collect_columns(
    engine: Engine,
    table_names: tuple[str, ...],
) -> dict[tuple[str, str], dict[str, Any]]:
    sql = sa.text(
        """
        SELECT
            table_name,
            column_name,
            data_type,
            character_maximum_length,
            udt_name,
            is_nullable,
            column_default
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = ANY(:table_names)
         ORDER BY table_name, ordinal_position
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"table_names": list(table_names)}).mappings().all()
    return {(r["table_name"], r["column_name"]): dict(r) for r in rows}


def _collect_constraints(
    engine: Engine,
    table_names: tuple[str, ...],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    sql = sa.text(
        """
        SELECT
            cls.relname AS table_name,
            con.contype AS contype,
            con.conname AS conname,
            ref_cls.relname AS referenced_table,
            con.confdeltype AS ondelete,
            ARRAY(
                SELECT att.attname
                  FROM unnest(con.conkey) WITH ORDINALITY AS cols(attnum, ord)
                  JOIN pg_attribute att
                    ON att.attrelid = con.conrelid AND att.attnum = cols.attnum
                 ORDER BY cols.ord
            ) AS columns
          FROM pg_constraint con
          JOIN pg_class cls ON cls.oid = con.conrelid
          JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
          LEFT JOIN pg_class ref_cls ON ref_cls.oid = con.confrelid
         WHERE nsp.nspname = 'public'
           AND cls.relname = ANY(:table_names)
         ORDER BY cls.relname, con.contype, con.conname
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"table_names": list(table_names)}).mappings().all()

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["table_name"], row["contype"]), []).append(dict(row))
    return grouped


def _collect_indexes(
    engine: Engine,
    table_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    sql = sa.text(
        """
        SELECT
            cls.relname AS table_name,
            idx_cls.relname AS index_name,
            idx.indisunique AS is_unique,
            ARRAY(
                SELECT att.attname
                  FROM unnest(idx.indkey) WITH ORDINALITY AS cols(attnum, ord)
                  JOIN pg_attribute att
                    ON att.attrelid = idx.indrelid AND att.attnum = cols.attnum
                 WHERE cols.attnum > 0
                 ORDER BY cols.ord
            ) AS columns,
            pg_get_expr(idx.indpred, idx.indrelid, true) AS predicate
          FROM pg_index idx
          JOIN pg_class cls ON cls.oid = idx.indrelid
          JOIN pg_class idx_cls ON idx_cls.oid = idx.indexrelid
          JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
         WHERE nsp.nspname = 'public'
           AND cls.relname = ANY(:table_names)
         ORDER BY cls.relname, idx_cls.relname
        """
    )
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(sql, {"table_names": list(table_names)}).mappings()]


def _assert_index_exists(
    indexes: list[dict[str, Any]],
    *,
    table_name: str,
    columns: tuple[str, ...],
    is_unique: bool,
    predicate_fragments: tuple[str, ...] = (),
) -> None:
    matches = [
        idx
        for idx in indexes
        if idx["table_name"] == table_name
        and tuple(idx["columns"]) == columns
        and idx["is_unique"] is is_unique
        and all(fragment in (idx["predicate"] or "") for fragment in predicate_fragments)
    ]
    assert matches, (
        f"Missing index on {table_name}{columns}, unique={is_unique}, "
        f"predicate fragments={predicate_fragments}; found={indexes}"
    )


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_email_verification_and_trusted_device_columns(upgraded_engine: Engine) -> None:
    """Alembic head exposes the columns declared by the Phase 010 data model."""

    table_names = tuple(EXPECTED_COLUMNS)
    columns = _collect_columns(upgraded_engine, table_names)

    for table_name, expected_table in EXPECTED_COLUMNS.items():
        for column_name, expected in expected_table.items():
            actual = columns.get((table_name, column_name))
            assert actual is not None, f"Missing column {table_name}.{column_name}"
            assert actual["data_type"] == expected.data_type
            assert actual["udt_name"] == expected.udt_name
            assert actual["is_nullable"] == ("YES" if expected.nullable else "NO")
            assert actual["character_maximum_length"] == expected.max_length
            assert (actual["column_default"] is not None) is expected.has_default


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_email_verification_and_trusted_device_constraints(
    upgraded_engine: Engine,
) -> None:
    """Token and trusted-device tables are user-bound and cascade on delete."""

    constraints = _collect_constraints(
        upgraded_engine,
        ("email_verification_tokens", "trusted_devices"),
    )

    for table_name in ("email_verification_tokens", "trusted_devices"):
        primary_keys = constraints.get((table_name, "p"), [])
        assert any(c["columns"] == ["id"] for c in primary_keys), (
            f"Missing id primary key for {table_name}; found={primary_keys}"
        )

        foreign_keys = constraints.get((table_name, "f"), [])
        assert any(
            c["columns"] == ["user_id"]
            and c["referenced_table"] == "users"
            and c["ondelete"] == "c"
            for c in foreign_keys
        ), f"Missing ON DELETE CASCADE user_id FK for {table_name}; found={foreign_keys}"


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_email_verification_and_trusted_device_indexes(upgraded_engine: Engine) -> None:
    """Alembic head creates the lookup and active-record indexes from the data model."""

    indexes = _collect_indexes(
        upgraded_engine,
        ("email_verification_tokens", "trusted_devices"),
    )

    _assert_index_exists(
        indexes,
        table_name="email_verification_tokens",
        columns=("token_hash",),
        is_unique=True,
        predicate_fragments=("consumed_at IS NULL", "superseded_at IS NULL"),
    )
    _assert_index_exists(
        indexes,
        table_name="email_verification_tokens",
        columns=("user_id", "purpose", "email_normalized"),
        is_unique=True,
        predicate_fragments=("consumed_at IS NULL", "superseded_at IS NULL"),
    )
    _assert_index_exists(
        indexes,
        table_name="email_verification_tokens",
        columns=("user_id", "purpose", "consumed_at", "superseded_at", "expires_at"),
        is_unique=False,
    )
    _assert_index_exists(
        indexes,
        table_name="email_verification_tokens",
        columns=("expires_at",),
        is_unique=False,
    )
    _assert_index_exists(
        indexes,
        table_name="trusted_devices",
        columns=("device_secret_hash",),
        is_unique=True,
        predicate_fragments=("revoked_at IS NULL",),
    )
    _assert_index_exists(
        indexes,
        table_name="trusted_devices",
        columns=("user_id", "revoked_at", "expires_at"),
        is_unique=False,
    )
