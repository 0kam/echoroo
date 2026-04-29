"""Phase 13 P5 / T808 — Alembic R3 normalized introspection parity test.

This test mechanically enforces the Phase 11 R3 forward-only convention that
*both* migration paths converge on the same final schema:

    Path A ("fresh"):    empty DB --> alembic upgrade head
                         (the baseline 0001 already emits the entire
                         Phase 13 final shape via
                         ``apply_phase13_supporting_tables``)

    Path B ("upgraded"): empty DB --> alembic upgrade 0005 --> alembic
                         upgrade head (the delta migrations
                         0006/0006a/0006b/0007/0008/0009 must reconcile a
                         long-lived dev DB to the same final shape)

Both paths must produce byte-for-byte identical schemas across **9
introspection axes** (per /tmp/plan-merged-v5-final.md §3 P5):

    1. information_schema.columns          — table/column/data_type/length/
                                              precision/udt_name
    2. pg_constraint                       — PK / UNIQUE / CHECK / FK with
                                              ``pg_get_constraintdef``
    3. pg_index                            — index name / columns /
                                              uniqueness / partial predicate
    4. pg_enum                             — enum label sets per type
    5. FK ondelete (confdeltype)           — referential action codes
    6. pg_attribute.attnotnull             — NOT NULL flags
    7. pg_attrdef                          — column default expressions
    8. pg_trigger                          — non-internal triggers
    9. seed/genesis rows                   — project_audit_log /
                                              platform_audit_log genesis
                                              with volatile cols (id,
                                              created_at, updated_at)
                                              excluded.

Volatile column rationale (Codex P0 R1): UUID-generated ``id``, ``now()``
``created_at`` and ``updated_at`` are guaranteed to differ between the two
DBs even when the schema and seed business state are identical. Comparing
business keys (``action``, ``prev_hash``, ``row_hash`` etc.) is sufficient.

The test is gated by the ``requires_postgres`` marker so it only runs in
environments with a working Docker socket (testcontainers).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover - dep declared in pyproject dev extras
    PostgresContainer = None  # type: ignore[assignment,misc]


API_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = API_ROOT / "alembic.ini"

# Revision the dev DB is assumed to have already applied at the start of
# Phase 13 (see project_006_implement_progress.md). The "upgraded" path
# stops here, then continues to ``head`` via the Phase 13 delta chain.
PHASE13_PRE_REVISION = "0005"


# ---------------------------------------------------------------------------
# Container fixtures — one PostgreSQL container hosting two independent DBs.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_container() -> Iterator[PostgresContainer]:
    """Spin up a throwaway PostgreSQL 16 container for the parity test."""

    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")

    # Use pgvector/pgvector:pg16 — the baseline migration requires the
    # ``vector`` extension (see 0001 ``CREATE EXTENSION IF NOT EXISTS vector``).
    # The plain ``postgres:16-alpine`` image lacks it.
    container = PostgresContainer("pgvector/pgvector:pg16")
    container.start()
    try:
        yield container
    finally:
        container.stop()


def _admin_url(container: PostgresContainer) -> str:
    """Return a sync (psycopg2-free) admin URL for the container."""

    sync_url = container.get_connection_url()  # postgresql+psycopg2://...
    return sync_url.replace("postgresql+psycopg2://", "postgresql://")


def _create_isolated_db(admin_url: str, db_name: str) -> str:
    """Create a fresh database `db_name` on the running container.

    Returns the sync URL pointing at the new database.
    """

    # Connect to the default 'test' DB (testcontainers default) with
    # AUTOCOMMIT to issue CREATE DATABASE.
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            conn.execute(sa.text(f'CREATE DATABASE "{db_name}"'))
    finally:
        engine.dispose()

    # Replace the path component (last segment of URL) with db_name.
    base, _, _ = admin_url.rpartition("/")
    return f"{base}/{db_name}"


def _alembic_upgrade(sync_url: str, target: str) -> None:
    """Invoke ``alembic upgrade <target>`` against the given sync URL."""

    async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")
    env = {
        **os.environ,
        "DATABASE_URL": async_url,
        "ALEMBIC_SYNC_URL": sync_url,
    }
    result = subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_INI), "upgrade", target],
        cwd=str(API_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"alembic upgrade {target} failed against {sync_url}.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


@pytest.fixture(scope="module")
def fresh_db_url(pg_container: PostgresContainer) -> str:
    """Return a sync URL for a DB created via the fresh path (Path A)."""

    admin = _admin_url(pg_container)
    url = _create_isolated_db(admin, "echoroo_p5_fresh")
    _alembic_upgrade(url, "head")
    return url


@pytest.fixture(scope="module")
def upgraded_db_url(pg_container: PostgresContainer) -> str:
    """Return a sync URL for a DB created via the upgraded path (Path B)."""

    admin = _admin_url(pg_container)
    url = _create_isolated_db(admin, "echoroo_p5_upgraded")
    # Step 1: bring DB to the Phase 13 pre-state.
    _alembic_upgrade(url, PHASE13_PRE_REVISION)
    # Step 2: continue through the Phase 13 delta chain to head.
    _alembic_upgrade(url, "head")
    return url


# ---------------------------------------------------------------------------
# Introspection helpers — one collector per axis.
# ---------------------------------------------------------------------------

def _collect_columns(engine: Engine) -> dict[tuple[str, str], tuple[Any, ...]]:
    """Axis 1: information_schema.columns canonical projection."""

    sql = sa.text(
        """
        SELECT
            table_name,
            column_name,
            data_type,
            character_maximum_length,
            numeric_precision,
            udt_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name NOT LIKE 'alembic_%'
           AND table_name <> 'alembic_version'
         ORDER BY table_name, ordinal_position
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()
    return {
        (r.table_name, r.column_name): (
            r.data_type,
            r.character_maximum_length,
            r.numeric_precision,
            r.udt_name,
        )
        for r in rows
    }


def _collect_constraints(engine: Engine) -> dict[tuple[str, str, str], str]:
    """Axis 2: pg_constraint with rendered definitions.

    Keyed by ``(table_name, contype, conname)``. The value is the rendered
    constraint definition from ``pg_get_constraintdef``.

    PK auto-name fingerprint: ``conname`` for primary keys is included so
    drift between rename strategies surfaces. UNIQUE / CHECK / FK are also
    name-sensitive, matching Phase 11 R3 fingerprint norms.
    """

    sql = sa.text(
        """
        SELECT
            cls.relname  AS table_name,
            con.contype  AS contype,
            con.conname  AS conname,
            pg_get_constraintdef(con.oid, true) AS constraint_def
          FROM pg_constraint con
          JOIN pg_class     cls ON cls.oid = con.conrelid
          JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
         WHERE nsp.nspname = 'public'
           AND con.contype IN ('p', 'u', 'c', 'f')
           AND cls.relname NOT LIKE 'alembic_%'
           AND cls.relname <> 'alembic_version'
         ORDER BY cls.relname, con.contype, con.conname
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()
    return {(r.table_name, r.contype, r.conname): r.constraint_def for r in rows}


def _collect_indexes(engine: Engine) -> dict[tuple[str, str], tuple[Any, ...]]:
    """Axis 3: pg_index with column list, uniqueness, partial predicate."""

    sql = sa.text(
        """
        SELECT
            cls.relname        AS table_name,
            idx_cls.relname    AS index_name,
            idx.indisunique    AS is_unique,
            pg_get_indexdef(idx.indexrelid)             AS index_def,
            pg_get_expr(idx.indpred, idx.indrelid, true) AS predicate
          FROM pg_index     idx
          JOIN pg_class     cls     ON cls.oid     = idx.indrelid
          JOIN pg_class     idx_cls ON idx_cls.oid = idx.indexrelid
          JOIN pg_namespace nsp     ON nsp.oid     = cls.relnamespace
         WHERE nsp.nspname = 'public'
           AND cls.relname NOT LIKE 'alembic_%'
           AND cls.relname <> 'alembic_version'
         ORDER BY cls.relname, idx_cls.relname
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()
    return {
        (r.table_name, r.index_name): (r.is_unique, r.index_def, r.predicate)
        for r in rows
    }


def _collect_enums(engine: Engine) -> dict[str, tuple[str, ...]]:
    """Axis 4: pg_enum label sets keyed by enum type name."""

    sql = sa.text(
        """
        SELECT
            t.typname AS type_name,
            array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
          FROM pg_type t
          JOIN pg_enum e ON e.enumtypid = t.oid
          JOIN pg_namespace n ON n.oid = t.typnamespace
         WHERE n.nspname = 'public'
         GROUP BY t.typname
         ORDER BY t.typname
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()
    return {r.type_name: tuple(r.labels) for r in rows}


def _collect_fk_actions(
    engine: Engine,
) -> dict[tuple[str, str], tuple[str, str]]:
    """Axis 5: FK ondelete/onupdate action codes (``confdeltype`` / ``confupdtype``).

    Codes: a=NO ACTION, r=RESTRICT, c=CASCADE, n=SET NULL, d=SET DEFAULT, '-'=none.
    """

    sql = sa.text(
        """
        SELECT
            cls.relname  AS table_name,
            con.conname  AS conname,
            con.confdeltype AS ondelete,
            con.confupdtype AS onupdate
          FROM pg_constraint con
          JOIN pg_class     cls ON cls.oid = con.conrelid
          JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
         WHERE nsp.nspname = 'public'
           AND con.contype = 'f'
         ORDER BY cls.relname, con.conname
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()
    return {(r.table_name, r.conname): (r.ondelete, r.onupdate) for r in rows}


def _collect_notnull(engine: Engine) -> dict[tuple[str, str], bool]:
    """Axis 6: pg_attribute.attnotnull per (table, column)."""

    sql = sa.text(
        """
        SELECT
            cls.relname AS table_name,
            att.attname AS column_name,
            att.attnotnull AS notnull
          FROM pg_attribute att
          JOIN pg_class     cls ON cls.oid = att.attrelid
          JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
         WHERE nsp.nspname = 'public'
           AND att.attnum > 0
           AND NOT att.attisdropped
           AND cls.relkind = 'r'
           AND cls.relname NOT LIKE 'alembic_%'
           AND cls.relname <> 'alembic_version'
         ORDER BY cls.relname, att.attname
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()
    return {(r.table_name, r.column_name): bool(r.notnull) for r in rows}


def _collect_defaults(engine: Engine) -> dict[tuple[str, str], str]:
    """Axis 7: pg_attrdef rendered default expression per (table, column)."""

    sql = sa.text(
        """
        SELECT
            cls.relname AS table_name,
            att.attname AS column_name,
            pg_get_expr(adf.adbin, adf.adrelid) AS default_expr
          FROM pg_attrdef adf
          JOIN pg_attribute att
            ON att.attrelid = adf.adrelid AND att.attnum = adf.adnum
          JOIN pg_class     cls ON cls.oid = adf.adrelid
          JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
         WHERE nsp.nspname = 'public'
           AND cls.relname NOT LIKE 'alembic_%'
           AND cls.relname <> 'alembic_version'
         ORDER BY cls.relname, att.attname
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()
    return {(r.table_name, r.column_name): r.default_expr for r in rows}


def _collect_triggers(engine: Engine) -> dict[tuple[str, str], str]:
    """Axis 8: non-internal pg_trigger entries with rendered DDL."""

    sql = sa.text(
        """
        SELECT
            cls.relname AS table_name,
            tg.tgname   AS trigger_name,
            pg_get_triggerdef(tg.oid, true) AS trigger_def
          FROM pg_trigger tg
          JOIN pg_class     cls ON cls.oid = tg.tgrelid
          JOIN pg_namespace nsp ON nsp.oid = cls.relnamespace
         WHERE nsp.nspname = 'public'
           AND NOT tg.tgisinternal
           AND cls.relname NOT LIKE 'alembic_%'
           AND cls.relname <> 'alembic_version'
         ORDER BY cls.relname, tg.tgname
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql).all()
    return {(r.table_name, r.trigger_name): r.trigger_def for r in rows}


# Volatile columns excluded from seed-row comparisons. Codex P0 R1 confirmed
# that UUID ``id`` and ``now()`` timestamps must be excluded.
_VOLATILE_COLS = frozenset({"id", "created_at", "updated_at"})


def _collect_seed_rows(engine: Engine) -> dict[tuple[str, str], dict[str, Any]]:
    """Axis 9: genesis rows of project_audit_log / platform_audit_log.

    Returns ``{(table_name, action): {col: value}}`` with volatile columns
    (``id``, ``created_at``, ``updated_at``) stripped.
    """

    out: dict[tuple[str, str], dict[str, Any]] = {}
    with engine.connect() as conn:
        for table in ("project_audit_log", "platform_audit_log"):
            cols = conn.execute(
                sa.text(
                    """
                    SELECT column_name FROM information_schema.columns
                     WHERE table_schema = 'public' AND table_name = :t
                     ORDER BY ordinal_position
                    """
                ),
                {"t": table},
            ).scalars().all()
            keep = [c for c in cols if c not in _VOLATILE_COLS]
            if not keep:
                continue
            select_list = ", ".join(f'"{c}"' for c in keep)
            rows = conn.execute(
                sa.text(
                    f"SELECT {select_list} FROM {table} "
                    "WHERE action = 'genesis' ORDER BY action"
                )
            ).all()
            for row in rows:
                rec = dict(zip(keep, row, strict=True))
                # Cast bytes / memoryview-like values to bytes for stable
                # equality across psycopg backends.
                for k, v in list(rec.items()):
                    if isinstance(v, memoryview):
                        rec[k] = bytes(v)
                out[(table, rec.get("action", ""))] = rec
    return out


# ---------------------------------------------------------------------------
# Aggregator + assertion helper.
# ---------------------------------------------------------------------------


def _collect_all(engine: Engine) -> dict[str, Any]:
    """Run all 9 collectors against the given engine."""

    return {
        "columns": _collect_columns(engine),
        "constraints": _collect_constraints(engine),
        "indexes": _collect_indexes(engine),
        "enums": _collect_enums(engine),
        "fk_actions": _collect_fk_actions(engine),
        "notnull": _collect_notnull(engine),
        "defaults": _collect_defaults(engine),
        "triggers": _collect_triggers(engine),
        "seed_rows": _collect_seed_rows(engine),
    }


def _format_diff(axis: str, fresh: Any, upgraded: Any) -> str:
    """Render a human-readable diff for a single axis."""

    if isinstance(fresh, dict) and isinstance(upgraded, dict):
        only_fresh = sorted(set(fresh) - set(upgraded))
        only_upgraded = sorted(set(upgraded) - set(fresh))
        differing = sorted(
            k for k in (set(fresh) & set(upgraded)) if fresh[k] != upgraded[k]
        )
        parts: list[str] = [f"axis={axis}:"]
        if only_fresh:
            parts.append(f"  only in fresh ({len(only_fresh)}):")
            for k in only_fresh[:20]:
                parts.append(f"    + {k}: {fresh[k]!r}")
            if len(only_fresh) > 20:
                parts.append(f"    ... ({len(only_fresh) - 20} more)")
        if only_upgraded:
            parts.append(f"  only in upgraded ({len(only_upgraded)}):")
            for k in only_upgraded[:20]:
                parts.append(f"    + {k}: {upgraded[k]!r}")
            if len(only_upgraded) > 20:
                parts.append(f"    ... ({len(only_upgraded) - 20} more)")
        if differing:
            parts.append(f"  differing values ({len(differing)}):")
            for k in differing[:20]:
                parts.append(
                    f"    ~ {k}:\n        fresh    = {fresh[k]!r}\n"
                    f"        upgraded = {upgraded[k]!r}"
                )
            if len(differing) > 20:
                parts.append(f"    ... ({len(differing) - 20} more)")
        return "\n".join(parts)
    return f"axis={axis}: fresh={fresh!r} upgraded={upgraded!r}"


# ---------------------------------------------------------------------------
# Tests — one per axis so failures are scoped, plus an aggregate sanity test.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fresh_introspection(fresh_db_url: str) -> dict[str, Any]:
    engine = create_engine(fresh_db_url)
    try:
        return _collect_all(engine)
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def upgraded_introspection(upgraded_db_url: str) -> dict[str, Any]:
    engine = create_engine(upgraded_db_url)
    try:
        return _collect_all(engine)
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.requires_postgres
@pytest.mark.parametrize(
    "axis",
    [
        "columns",
        "constraints",
        "indexes",
        "enums",
        "fk_actions",
        "notnull",
        "defaults",
        "triggers",
        "seed_rows",
    ],
)
def test_fresh_vs_upgraded_axis_match(
    axis: str,
    fresh_introspection: dict[str, Any],
    upgraded_introspection: dict[str, Any],
) -> None:
    """Each of the 9 introspection axes must match between fresh and upgraded.

    Failure messages enumerate only-in-fresh, only-in-upgraded, and
    differing-value keys so root-cause analysis can pinpoint which baseline
    edit (0001 ``apply_phase13_supporting_tables``) or delta migration
    (0006/0006a/0006b/0007/0008/0009) needs adjustment.
    """

    fresh = fresh_introspection[axis]
    upgraded = upgraded_introspection[axis]
    assert fresh == upgraded, _format_diff(axis, fresh, upgraded)


@pytest.mark.integration
@pytest.mark.requires_postgres
def test_fresh_vs_upgraded_db_match_on_9_axes(
    fresh_introspection: dict[str, Any],
    upgraded_introspection: dict[str, Any],
) -> None:
    """Aggregate sanity: union over all 9 axes must match exactly.

    This duplicates the parametrized per-axis assertions but produces a single
    combined diff if multiple axes drift simultaneously, which makes root-cause
    review faster when the per-axis tests cascade.
    """

    mismatches = [
        axis
        for axis in fresh_introspection
        if fresh_introspection[axis] != upgraded_introspection[axis]
    ]
    if mismatches:
        rendered = "\n\n".join(
            _format_diff(
                axis,
                fresh_introspection[axis],
                upgraded_introspection[axis],
            )
            for axis in mismatches
        )
        pytest.fail(
            "Phase 13 R3 parity violated on axes "
            f"{mismatches}:\n\n{rendered}"
        )
