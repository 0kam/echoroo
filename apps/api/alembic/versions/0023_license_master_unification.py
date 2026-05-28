"""License master unification — foundational migration (spec/012 Phase 2).

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-28

This forward-only migration promotes ``licenses`` to the single source of
truth for project license assignment:

1. Audit legacy license-bearing columns before touching schema.
2. Add a unique constraint on ``licenses.short_name``.
3. Seed the four canonical Creative Commons rows by ``short_name``.
4. Add nullable ``projects.license_id``.
5. Backfill it from the legacy ``projects.license`` enum by joining
   ``licenses.short_name``.
6. Add ``projects_license_id_fkey`` with ``ON DELETE RESTRICT`` and an
   explicit ``ix_projects_license_id`` index.
7. Drop the legacy ``projects.license`` column.
8. Convert ``project_license_history.old_license`` / ``new_license`` to
   ``VARCHAR(50)`` snapshot strings.
9. Recreate the dataset license FK as ``ON DELETE RESTRICT``.
10. Refuse downgrade; restore from backup if rollback is required.

The audit runs first per research R4 so unknown values abort before any
structural change is attempted. The legacy PostgreSQL ``projectlicense`` enum
type is intentionally left in place for a later cleanup migration.

Operator note: if PR #116 merges first, this migration must be renamed and
rebased to revision 0024.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# Audit allow-list for legacy enum values. Do not use these ids for backfill:
# admin-curated license rows may preserve a canonical short_name under a custom id.
_LICENSE_ID_FOR_ENUM: dict[str, str] = {
    "CC0": "cc0",
    "CC-BY": "cc-by",
    "CC-BY-NC": "cc-by-nc",
    "CC-BY-SA": "cc-by-sa",
}

_CANONICAL_LICENSE_ROWS: tuple[dict[str, str], ...] = (
    {
        "id": "cc0",
        "short_name": "CC0",
        "name": "Creative Commons Zero 1.0 Universal (Public Domain Dedication)",
        "url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "description": "No rights reserved.",
    },
    {
        "id": "cc-by",
        "short_name": "CC-BY",
        "name": "Creative Commons Attribution 4.0 International",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "description": "Attribution required.",
    },
    {
        "id": "cc-by-nc",
        "short_name": "CC-BY-NC",
        "name": "Creative Commons Attribution-NonCommercial 4.0 International",
        "url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "description": "Attribution, non-commercial use only.",
    },
    {
        "id": "cc-by-sa",
        "short_name": "CC-BY-SA",
        "name": "Creative Commons Attribution-ShareAlike 4.0 International",
        "url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "description": "Attribution, share-alike.",
    },
)


def _audit_legacy_license_values() -> None:
    """Abort if any legacy license-bearing column has an unmapped value."""

    bind = op.get_bind()
    allowed_values = tuple(_LICENSE_ID_FOR_ENUM)
    audit_targets = (
        ("projects", "license"),
        ("project_license_history", "old_license"),
        ("project_license_history", "new_license"),
    )
    offenders: dict[str, list[str]] = {}

    for table_name, column_name in audit_targets:
        rows = bind.execute(
            sa.text(
                f"""
                SELECT DISTINCT {column_name}::text AS value
                FROM {table_name}
                WHERE {column_name} IS NOT NULL
                AND {column_name}::text NOT IN :allowed_values
                ORDER BY value
                """
            ).bindparams(sa.bindparam("allowed_values", expanding=True)),
            {"allowed_values": allowed_values},
        ).scalars()
        values = list(rows)
        if values:
            offenders[f"{table_name}.{column_name}"] = values

    if offenders:
        details = "; ".join(
            f"{target}={values!r}" for target, values in offenders.items()
        )
        raise ValueError(
            "Migration 0023 cannot map unknown legacy license values: "
            f"{details}. Clean the data or extend _LICENSE_ID_FOR_ENUM before retrying."
        )


def _add_licenses_short_name_unique_constraint() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_licenses_short_name'
            ) THEN
                ALTER TABLE licenses
                    ADD CONSTRAINT uq_licenses_short_name UNIQUE (short_name);
            END IF;
        END
        $$;
        """
    )


def _seed_canonical_licenses() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO licenses (
                id, short_name, name, url, description, created_at, updated_at
            )
            VALUES (
                :id, :short_name, :name, :url, :description, now(), now()
            )
            ON CONFLICT (short_name) DO NOTHING
            """
        ),
        list(_CANONICAL_LICENSE_ROWS),
    )


def _backfill_project_license_ids() -> None:
    bind = op.get_bind()
    op.execute(
        """
        UPDATE projects
        SET license_id = licenses.id
        FROM licenses
        WHERE projects.license IS NOT NULL
        AND licenses.short_name = projects.license::text;
        """
    )
    unmapped_count = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM projects
            WHERE license IS NOT NULL
            AND license_id IS NULL
            """
        )
    ).scalar_one()
    if unmapped_count:
        raise ValueError(
            "Migration 0023 failed to backfill projects.license_id for "
            f"{unmapped_count} project(s) with non-null legacy license."
        )


def _replace_datasets_license_fk() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            constraint_name text;
            id_attnum smallint;
            license_id_attnum smallint;
        BEGIN
            SELECT a.attnum
            INTO license_id_attnum
            FROM pg_attribute a
            WHERE a.attrelid = 'datasets'::regclass
            AND a.attname = 'license_id'
            AND NOT a.attisdropped;

            SELECT a.attnum
            INTO id_attnum
            FROM pg_attribute a
            WHERE a.attrelid = 'licenses'::regclass
            AND a.attname = 'id'
            AND NOT a.attisdropped;

            IF EXISTS (
                SELECT 1
                FROM pg_constraint c
                WHERE c.conname IN ('fk_datasets_license_id', 'datasets_license_id_fkey')
                AND c.conrelid = 'datasets'::regclass
                AND c.confrelid = 'licenses'::regclass
                AND c.contype = 'f'
                AND c.conkey = ARRAY[license_id_attnum]::smallint[]
                AND c.confkey = ARRAY[id_attnum]::smallint[]
            ) THEN
                FOR constraint_name IN
                    SELECT c.conname
                    FROM pg_constraint c
                    WHERE c.conname IN ('fk_datasets_license_id', 'datasets_license_id_fkey')
                    AND c.conrelid = 'datasets'::regclass
                    AND c.confrelid = 'licenses'::regclass
                    AND c.contype = 'f'
                    AND c.conkey = ARRAY[license_id_attnum]::smallint[]
                    AND c.confkey = ARRAY[id_attnum]::smallint[]
                LOOP
                    EXECUTE format('ALTER TABLE datasets DROP CONSTRAINT %I', constraint_name);
                END LOOP;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint c
                WHERE c.conname = 'fk_datasets_license_id'
                AND c.conrelid = 'datasets'::regclass
                AND c.confrelid = 'licenses'::regclass
                AND c.contype = 'f'
                AND c.conkey = ARRAY[license_id_attnum]::smallint[]
                AND c.confkey = ARRAY[id_attnum]::smallint[]
            ) THEN
                ALTER TABLE datasets
                    ADD CONSTRAINT fk_datasets_license_id
                    FOREIGN KEY (license_id) REFERENCES licenses(id)
                    ON DELETE RESTRICT;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    """Apply spec/012 Phase 2 foundational schema changes."""

    # 1. Audit first so unknown legacy values fail before any DDL runs.
    _audit_legacy_license_values()
    # 2. Allow seed de-duplication by visible short_name.
    _add_licenses_short_name_unique_constraint()
    # 3. Seed the four canonical rows without overwriting admin edits.
    _seed_canonical_licenses()
    # 4. Add the new nullable FK column for live project license state.
    op.add_column("projects", sa.Column("license_id", sa.String(50), nullable=True))
    # 5. Deterministically backfill from the legacy enum values.
    _backfill_project_license_ids()
    # 6. Protect references and index the new lookup path.
    op.create_foreign_key(
        "projects_license_id_fkey",
        "projects",
        "licenses",
        ["license_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_projects_license_id", "projects", ["license_id"])
    # 7. Remove the legacy live enum column.
    op.drop_column("projects", "license")
    # 8. Keep history as immutable short_name snapshots.
    op.alter_column(
        "project_license_history",
        "old_license",
        existing_type=sa.Enum(name="projectlicense"),
        type_=sa.String(50),
        postgresql_using="old_license::text",
        existing_nullable=True,
    )
    op.alter_column(
        "project_license_history",
        "new_license",
        existing_type=sa.Enum(name="projectlicense"),
        type_=sa.String(50),
        postgresql_using="new_license::text",
        existing_nullable=False,
    )
    # 9. Align dataset/license delete behavior with projects.
    _replace_datasets_license_fk()


def downgrade() -> None:
    """Forward-only per spec/012 A-005 and spec/011 step 11 precedent."""
    raise NotImplementedError(
        "Migration 0023 is forward-only per spec/012 A-005. "
        "License master unification rewrites live project license storage; "
        "restore from backup if rollback is required."
    )
