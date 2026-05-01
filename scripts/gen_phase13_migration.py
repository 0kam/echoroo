"""Generate static alembic migration for Phase 13 P0a (T801).

Walks ``Base.metadata`` and emits ``CREATE TABLE IF NOT EXISTS`` + ``CREATE
INDEX IF NOT EXISTS`` statements for every ORM-only table identified during
the Phase 13 inventory (T800).

Usage (inside echoroo-backend container)::

    docker exec echoroo-backend uv run python /app/scripts/gen_phase13_migration.py \
        > /tmp/0006_schema_reconcile_static.py.body

The output is a Python migration body. The header (revision metadata,
``upgrade``/``downgrade`` wrappers, enum helpers) is added by the wrapper
template baked into ``apps/api/alembic/versions/0006_schema_reconcile_static.py``.

Generation runs once. After the migration is checked in, do **not** re-run
this script when the ORM evolves; future schema changes must go into a new
migration revision.
"""
from __future__ import annotations

import sys

# Force-import all ORM modules so Base.metadata is fully populated.
import echoroo.models  # noqa: F401
from echoroo.models.base import Base
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

DIALECT = postgresql.dialect()


# Tables that already exist in the DB (per T800 inventory) — skip them.
DB_EXISTING_TABLES = {
    "annotation_comments",
    "annotation_votes",
    "annotations",
    "datasets",
    "iucn_sync_attempts",
    "password_reset_tokens",
    "project_invitations",
    "project_license_history",
    "project_members",
    "project_taxon_sensitivity_overrides",
    "project_trusted_users",
    "projects",
    "recordings",
    "sites",
    "system_settings",
    "tags",
    "taxon_sensitivities",
    "user_login_notifications_seen",
    "users",
    # DB-only tables (tables present in DB but absent in ORM) are
    # untouched by this migration. ``detections`` is the only DB-only
    # table that the static migration *re-emits* under the canonical ORM
    # definition (CREATE TABLE IF NOT EXISTS keeps existing rows).
    "api_keys",
    "dek_rewrap_failures",
    "outbox_events",
    "platform_audit_log",
    "project_audit_log",
    "refresh_tokens",
    "superuser_approval_requests",
    "superusers",
    "token_families",
    "wipe_guard",
    "alembic_version",
}


def render_sql(stmt) -> str:
    return str(stmt.compile(dialect=DIALECT)).strip()


def _quote_sql_for_python(sql: str) -> str:
    """Embed a SQL block inside a Python triple-quoted raw string safely."""

    return sql.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def main() -> int:
    metadata = Base.metadata

    # Sort topologically so dependent FKs are created last.
    sorted_tables = list(metadata.sorted_tables)
    target_tables = [t for t in sorted_tables if t.name not in DB_EXISTING_TABLES]

    sys.stdout.write(
        "    # ----- ORM-only tables (T801, generated from Base.metadata) -----\n"
    )
    sys.stdout.write(f"    # Total tables: {len(target_tables)}\n\n")

    for table in target_tables:
        create_table_sql = render_sql(CreateTable(table, if_not_exists=True))
        sys.stdout.write(
            f"    # --- {table.name} ---\n"
        )
        sys.stdout.write(
            "    op.execute(sa.text(\"\"\"\n"
            f"{create_table_sql}\n"
            "    \"\"\"))\n"
        )
        for idx in table.indexes:
            create_index_sql = render_sql(CreateIndex(idx, if_not_exists=True))
            sys.stdout.write(
                "    op.execute(sa.text(\"\"\"\n"
                f"{create_index_sql}\n"
                "    \"\"\"))\n"
            )
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
