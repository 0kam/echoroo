"""Phase 13 P2 (T805) — datasets extension (14 columns).

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-28 09:00:00.000000

Phase 13 P0 inventory (``/tmp/phase13-inventory.md``) flagged ``datasets`` as
one of the four core tables in the ORM/DB three-way diff: the live DB carries
only the 8-column placeholder shape created by baseline ``0001``
(``id, project_id, name, description, status, visibility, created_at, updated_at``),
while the ORM canonical (``apps/api/echoroo/models/dataset.py``) and the
spec target (``data-model.md`` §3.22, plan v5-final §2.2) require the full
22-column shape used by the legacy 002-data-management feature. This
revision applies the 14 missing columns + the 3 missing indexes + the
``(project_id, name)`` UNIQUE via idempotent ``ALTER TABLE`` /
``CREATE INDEX IF NOT EXISTS`` blocks.

The dual-track invariant from Phase 13 P1 / P1.5 is preserved: the
companion edit to ``0001_baseline_permissions_redesign.py`` materialises
the same final shape directly inside the ``create_table()`` block (with
the ``recorder_id`` / ``license_id`` FKs deferred to after
``apply_phase13_supporting_tables()`` since ``recorders`` / ``licenses``
are emitted by the supporting-DDL helper). A fresh DB built from
``0001`` alone therefore reaches the same byte-for-byte schema as a
long-lived DB that arrives via ``0001 → 0002 → … → 0007 → 0008``.

The 14 columns added (per ORM ``Dataset`` and v5-final §2.2):

* ``site_id`` UUID NOT NULL FK ``sites.id`` ON DELETE CASCADE
* ``recorder_id`` VARCHAR(50) nullable FK ``recorders.id`` ON DELETE SET NULL
* ``license_id`` VARCHAR(50) nullable FK ``licenses.id`` ON DELETE SET NULL
* ``created_by_id`` UUID NOT NULL FK ``users.id`` ON DELETE RESTRICT
  (data-model.md §3.22 line 890 — RESTRICT chosen over SET NULL because
  the column is NOT NULL; creator deletion must cascade-delete or be
  blocked).
* ``audio_dir`` VARCHAR(500) nullable (deprecated, ORM-marked)
* ``doi`` VARCHAR(255) nullable
* ``gain`` FLOAT nullable
* ``note`` TEXT nullable
* ``datetime_pattern`` VARCHAR(500) nullable
* ``datetime_format`` VARCHAR(100) nullable
* ``datetime_timezone`` VARCHAR(50) nullable
* ``total_files`` INTEGER NOT NULL DEFAULT 0
* ``processed_files`` INTEGER NOT NULL DEFAULT 0
* ``processing_error`` TEXT nullable

Plus indexes ``ix_datasets_site_id``, ``ix_datasets_status``,
``ix_datasets_visibility`` and the ``uq_dataset_project_name`` UNIQUE
constraint on ``(project_id, name)``.

**Backfill note for non-empty DBs**: Phase 13 was conducted on an empty
``datasets`` table (``SELECT count(*) FROM datasets`` returns 0 in dev
prior to T805); the spec mandates that `006-permissions-redesign` ships
on a freshly wiped DB (FR-113 / FR-114), so the NOT NULL columns
``site_id`` and ``created_by_id`` are added directly with no temporary
nullable phase. If this migration is ever re-run against a populated
``datasets`` table, the ``ALTER COLUMN ... SET NOT NULL`` step will
fail; the operator must first backfill ``site_id`` (e.g. via the
sentinel site of the parent project) and ``created_by_id`` (e.g. via
the project owner) before applying.

Downgrade drops the 14 columns + the 3 ``ix_datasets_*`` indexes +
the UNIQUE; ``ix_datasets_project_id`` is left intact (it predates
this revision in baseline 0001).
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# --------------------------------------------------------------------------- #
# Upgrade — idempotent ALTER TABLE per column
# --------------------------------------------------------------------------- #


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Add the 14 missing columns. Each ALTER is wrapped in IF NOT
    #    EXISTS via a DO $$ ... $$ block so re-applying on a fresh DB
    #    (which already holds the final shape via baseline 0001) is a
    #    no-op.
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DO $$
        BEGIN
            -- site_id UUID NOT NULL FK sites.id ON DELETE CASCADE
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'site_id'
            ) THEN
                ALTER TABLE datasets ADD COLUMN site_id UUID;
                ALTER TABLE datasets
                    ADD CONSTRAINT fk_datasets_site_id
                    FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE;
                ALTER TABLE datasets ALTER COLUMN site_id SET NOT NULL;
            END IF;

            -- recorder_id VARCHAR(50) nullable FK recorders.id ON DELETE SET NULL
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'recorder_id'
            ) THEN
                ALTER TABLE datasets ADD COLUMN recorder_id VARCHAR(50);
                ALTER TABLE datasets
                    ADD CONSTRAINT fk_datasets_recorder_id
                    FOREIGN KEY (recorder_id) REFERENCES recorders(id) ON DELETE SET NULL;
            END IF;

            -- license_id VARCHAR(50) nullable FK licenses.id ON DELETE SET NULL
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'license_id'
            ) THEN
                ALTER TABLE datasets ADD COLUMN license_id VARCHAR(50);
                ALTER TABLE datasets
                    ADD CONSTRAINT fk_datasets_license_id
                    FOREIGN KEY (license_id) REFERENCES licenses(id) ON DELETE SET NULL;
            END IF;

            -- created_by_id UUID NOT NULL FK users.id ON DELETE RESTRICT
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'created_by_id'
            ) THEN
                ALTER TABLE datasets ADD COLUMN created_by_id UUID;
                ALTER TABLE datasets
                    ADD CONSTRAINT fk_datasets_created_by_id
                    FOREIGN KEY (created_by_id) REFERENCES users(id) ON DELETE RESTRICT;
                ALTER TABLE datasets ALTER COLUMN created_by_id SET NOT NULL;
            END IF;

            -- audio_dir VARCHAR(500) nullable (deprecated)
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'audio_dir'
            ) THEN
                ALTER TABLE datasets ADD COLUMN audio_dir VARCHAR(500);
            END IF;

            -- doi VARCHAR(255) nullable
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'doi'
            ) THEN
                ALTER TABLE datasets ADD COLUMN doi VARCHAR(255);
            END IF;

            -- gain FLOAT nullable
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'gain'
            ) THEN
                ALTER TABLE datasets ADD COLUMN gain DOUBLE PRECISION;
            END IF;

            -- note TEXT nullable
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'note'
            ) THEN
                ALTER TABLE datasets ADD COLUMN note TEXT;
            END IF;

            -- datetime_pattern VARCHAR(500) nullable
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'datetime_pattern'
            ) THEN
                ALTER TABLE datasets ADD COLUMN datetime_pattern VARCHAR(500);
            END IF;

            -- datetime_format VARCHAR(100) nullable
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'datetime_format'
            ) THEN
                ALTER TABLE datasets ADD COLUMN datetime_format VARCHAR(100);
            END IF;

            -- datetime_timezone VARCHAR(50) nullable
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'datetime_timezone'
            ) THEN
                ALTER TABLE datasets ADD COLUMN datetime_timezone VARCHAR(50);
            END IF;

            -- total_files INTEGER NOT NULL DEFAULT 0
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'total_files'
            ) THEN
                ALTER TABLE datasets ADD COLUMN total_files INTEGER NOT NULL DEFAULT 0;
            END IF;

            -- processed_files INTEGER NOT NULL DEFAULT 0
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'processed_files'
            ) THEN
                ALTER TABLE datasets ADD COLUMN processed_files INTEGER NOT NULL DEFAULT 0;
            END IF;

            -- processing_error TEXT nullable
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'datasets' AND column_name = 'processing_error'
            ) THEN
                ALTER TABLE datasets ADD COLUMN processing_error TEXT;
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------ #
    # 2. Add the (project_id, name) UNIQUE constraint. Idempotent via
    #    pg_constraint check.
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_dataset_project_name'
            ) THEN
                ALTER TABLE datasets
                    ADD CONSTRAINT uq_dataset_project_name
                    UNIQUE (project_id, name);
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------ #
    # 3. Add the 3 missing indexes. ``ix_datasets_project_id`` is created
    #    by baseline 0001 and is left untouched.
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_datasets_site_id ON datasets (site_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_datasets_status ON datasets (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_datasets_visibility ON datasets (visibility)"
    )
    # Phase 13 P2 R2 (Codex follow-up): TimestampMixin declares
    # created_at with index=True so the ORM expects
    # ix_datasets_created_at. Materialise it here so P5 introspection
    # parity holds for datasets.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_datasets_created_at ON datasets (created_at)"
    )


# --------------------------------------------------------------------------- #
# Downgrade — drop the 14 columns + 4 indexes + UNIQUE
# --------------------------------------------------------------------------- #


def downgrade() -> None:
    # Drop indexes first (cheap; safe even if some never existed).
    op.execute("DROP INDEX IF EXISTS ix_datasets_created_at")
    op.execute("DROP INDEX IF EXISTS ix_datasets_visibility")
    op.execute("DROP INDEX IF EXISTS ix_datasets_status")
    op.execute("DROP INDEX IF EXISTS ix_datasets_site_id")

    # Drop UNIQUE constraint.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_dataset_project_name'
            ) THEN
                ALTER TABLE datasets DROP CONSTRAINT uq_dataset_project_name;
            END IF;
        END
        $$;
        """
    )

    # Drop the 14 columns. ``DROP COLUMN IF EXISTS`` cascades the FK
    # constraints we created so no separate drop-constraint pass is
    # required.
    for col in (
        "processing_error",
        "processed_files",
        "total_files",
        "datetime_timezone",
        "datetime_format",
        "datetime_pattern",
        "note",
        "gain",
        "doi",
        "audio_dir",
        "created_by_id",
        "license_id",
        "recorder_id",
        "site_id",
    ):
        op.execute(f"ALTER TABLE datasets DROP COLUMN IF EXISTS {col}")
