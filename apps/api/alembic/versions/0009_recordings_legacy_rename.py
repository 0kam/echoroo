"""Phase 13 P3 (T806) — recordings legacy rename + extend.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-28 12:00:00.000000

Phase 13 P0 inventory flagged ``recordings`` as the third of the four core
tables in the ORM/DB three-way diff. The live DB carries the legacy
shape created by baseline ``0001`` prior to Phase 13 P3:

    id, project_id (NOT NULL), dataset_id (nullable), site_id, path TEXT,
    duration_seconds, sample_rate, channels, recorded_at, h3_index_member,
    h3_index_member_resolution, gps_stripped, created_at, updated_at

The ORM canonical (``apps/api/echoroo/models/recording.py``) and the
spec target (``data-model.md`` §3.11, plan v5-final §2.3) require the
rebuilt 19-column shape with legacy command-line names
(``duration`` / ``samplerate`` / ``datetime``), an ``API alias`` strategy
in ``schemas/recording.py`` to preserve wire compatibility for the
frontend, the dataset-only parentage (``project_id`` dropped — fetched
via ``dataset.project_id``), and the audio-metadata extensions
(``filename``, ``hash``, ``bit_depth``, ``datetime_parse_status``,
``datetime_parse_error``, ``time_expansion``, ``note``).

This revision applies the diff via fully idempotent ``DO $$ ... $$``
blocks so that:

* a fresh DB reaches the final shape from ``0001`` alone (the baseline
  edit in this same Phase 13 P3 batch materialises the post-rename
  shape directly inside the ``create_table()`` block);
* a long-lived dev DB at ``0008`` arrives at byte-for-byte the same
  end state by sequentially applying ``0001 → 0002 → … → 0008 → 0009``.

**Backfill note for non-empty DBs**: Phase 13 was conducted on an
empty ``recordings`` table (``SELECT count(*) FROM recordings``
returns 0 in dev prior to T806); the spec mandates that
``006-permissions-redesign`` ships on a freshly wiped DB
(FR-113 / FR-114), so the NOT NULL columns (``filename``, ``duration``,
``samplerate``, ``channels``, ``time_expansion``,
``datetime_parse_status``, ``gps_stripped``) are tightened directly
without a multi-pass nullable backfill phase. If this migration is
ever re-run against a populated ``recordings`` table, the
``ALTER COLUMN ... SET NOT NULL`` steps for ``duration``,
``samplerate`` and ``channels`` will fail unless every existing row
already has those values, and ``filename`` will be left as the empty
string (the operator must subsequently backfill from
``regexp_replace(path, '.*/', '')`` or similar). The ``project_id``
DROP COLUMN step is likewise unconditional and assumes 0 rows.

The 19-column shape produced (per ORM ``Recording`` and v5-final §2.3):

* ``id`` UUID PK
* ``dataset_id`` UUID NOT NULL FK ``datasets.id`` ON DELETE CASCADE
  (was nullable in ``0001`` baseline; tightened here)
* ``site_id`` UUID nullable FK ``sites.id`` ON DELETE SET NULL
  (override; NULL ⇒ inherit ``dataset.site_id``)
* ``filename`` VARCHAR(255) NOT NULL (new)
* ``path`` VARCHAR(500) NOT NULL (was ``TEXT``, narrowed)
* ``hash`` VARCHAR(64) nullable (new)
* ``duration`` DOUBLE PRECISION NOT NULL (renamed from ``duration_seconds``)
* ``samplerate`` INTEGER NOT NULL (renamed from ``sample_rate``)
* ``channels`` INTEGER NOT NULL (NULL → NOT NULL)
* ``bit_depth`` INTEGER nullable (new)
* ``datetime`` TIMESTAMPTZ nullable (renamed from ``recorded_at``)
* ``datetime_parse_status`` ``datetimeparsestatus`` NOT NULL DEFAULT
  ``'pending'`` (new)
* ``datetime_parse_error`` TEXT nullable (new)
* ``time_expansion`` DOUBLE PRECISION NOT NULL DEFAULT ``1.0`` (new)
* ``note`` TEXT nullable (new)
* ``h3_index_member`` VARCHAR(32) nullable (kept)
* ``h3_index_member_resolution`` INTEGER nullable (kept; new CHECK)
* ``gps_stripped`` BOOLEAN NOT NULL DEFAULT ``false`` (kept)
* ``created_at`` / ``updated_at`` TIMESTAMPTZ NOT NULL DEFAULT
  ``now()`` (kept)

Plus:

* DROP COLUMN ``project_id`` (denormalised; reach via dataset)
* UNIQUE ``(dataset_id, path)`` ⇒ ``uq_recording_dataset_path``
* INDEX ``ix_recordings_hash`` on ``hash``
* INDEX ``ix_recordings_dataset_id_datetime`` on ``(dataset_id, datetime)``
* INDEX ``ix_recordings_datetime`` on ``datetime``
* INDEX ``ix_recordings_h3_index_member`` on ``h3_index_member``
* CHECK ``ck_recordings_h3_resolution``
  (``h3_index_member_resolution IS NULL OR h3_index_member_resolution
  IN (9, 15)``)

Existing ``ix_recordings_dataset_id`` and ``ix_recordings_site_id``
from baseline ``0001`` are kept as-is. The
``ix_recordings_project_id`` index is dropped together with the
``project_id`` column.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# --------------------------------------------------------------------------- #
# Upgrade — idempotent rename + extend
# --------------------------------------------------------------------------- #


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Phase A — rename legacy columns to ORM canonical names.
    # All three RENAME COLUMN statements are guarded by IF EXISTS via a
    # DO $$ ... $$ block so that re-applying on a fresh DB (which
    # already holds the renamed columns via baseline 0001) is a no-op.
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'duration_seconds'
            ) THEN
                ALTER TABLE recordings RENAME COLUMN duration_seconds TO duration;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'sample_rate'
            ) THEN
                ALTER TABLE recordings RENAME COLUMN sample_rate TO samplerate;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'recorded_at'
            ) THEN
                ALTER TABLE recordings RENAME COLUMN recorded_at TO datetime;
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------ #
    # Phase B — drop legacy ``project_id`` (denormalised — reach via
    # dataset.project_id). Drops the supporting index first (the
    # column drop would cascade, but explicit DROP INDEX IF EXISTS is
    # cleaner for downgrade symmetry).
    # ------------------------------------------------------------------ #
    op.execute("DROP INDEX IF EXISTS ix_recordings_project_id")
    op.execute("ALTER TABLE recordings DROP COLUMN IF EXISTS project_id")

    # Tighten ``dataset_id`` to NOT NULL. Idempotent: SET NOT NULL on an
    # already-NOT-NULL column is a no-op in PostgreSQL but we still
    # guard via information_schema for clarity.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings'
                  AND column_name = 'dataset_id'
                  AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE recordings ALTER COLUMN dataset_id SET NOT NULL;
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------ #
    # Phase C — add new columns. Each ALTER is wrapped in IF NOT EXISTS
    # via DO $$ ... $$. The ``filename`` NOT NULL DEFAULT '' pattern is
    # safe on the empty Phase 13 dev DB; on a populated DB the operator
    # must backfill from ``path`` before the DEFAULT is dropped (which
    # we do not bother doing here — the DEFAULT '' is harmless).
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'filename'
            ) THEN
                ALTER TABLE recordings ADD COLUMN filename VARCHAR(255) NOT NULL DEFAULT '';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'hash'
            ) THEN
                ALTER TABLE recordings ADD COLUMN hash VARCHAR(64);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'bit_depth'
            ) THEN
                ALTER TABLE recordings ADD COLUMN bit_depth INTEGER;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'datetime_parse_status'
            ) THEN
                ALTER TABLE recordings
                    ADD COLUMN datetime_parse_status datetimeparsestatus
                    NOT NULL DEFAULT 'pending';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'datetime_parse_error'
            ) THEN
                ALTER TABLE recordings ADD COLUMN datetime_parse_error TEXT;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'time_expansion'
            ) THEN
                ALTER TABLE recordings
                    ADD COLUMN time_expansion DOUBLE PRECISION
                    NOT NULL DEFAULT 1.0;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'note'
            ) THEN
                ALTER TABLE recordings ADD COLUMN note TEXT;
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------ #
    # Phase D — tighten existing nullable columns to NOT NULL and
    # narrow ``path`` from TEXT → VARCHAR(500). All idempotent.
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings'
                  AND column_name = 'duration'
                  AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE recordings ALTER COLUMN duration SET NOT NULL;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings'
                  AND column_name = 'samplerate'
                  AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE recordings ALTER COLUMN samplerate SET NOT NULL;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings'
                  AND column_name = 'channels'
                  AND is_nullable = 'YES'
            ) THEN
                ALTER TABLE recordings ALTER COLUMN channels SET NOT NULL;
            END IF;

            -- Narrow path TEXT → VARCHAR(500). PostgreSQL tolerates
            -- ALTER COLUMN ... TYPE VARCHAR(500) when no row exceeds
            -- the new length (USING is implicit for compatible casts).
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings'
                  AND column_name = 'path'
                  AND data_type = 'text'
            ) THEN
                ALTER TABLE recordings
                    ALTER COLUMN path TYPE VARCHAR(500) USING path::VARCHAR(500);
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------ #
    # Phase E — UNIQUE / INDEX / CHECK
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_recording_dataset_path'
            ) THEN
                ALTER TABLE recordings
                    ADD CONSTRAINT uq_recording_dataset_path
                    UNIQUE (dataset_id, path);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_recordings_h3_resolution'
            ) THEN
                ALTER TABLE recordings
                    ADD CONSTRAINT ck_recordings_h3_resolution
                    CHECK (
                        h3_index_member_resolution IS NULL
                        OR h3_index_member_resolution IN (9, 15)
                    );
            END IF;
        END
        $$;
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_recordings_hash ON recordings (hash)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recordings_datetime ON recordings (datetime)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recordings_dataset_id_datetime "
        "ON recordings (dataset_id, datetime)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recordings_h3_index_member "
        "ON recordings (h3_index_member)"
    )


# --------------------------------------------------------------------------- #
# Downgrade — reverse the rename + extend.
# Best-effort symmetry; the original ``project_id`` column is restored as
# nullable (no source data). Not designed for production rollback.
# --------------------------------------------------------------------------- #


def downgrade() -> None:
    # Drop indexes / constraints first.
    op.execute("DROP INDEX IF EXISTS ix_recordings_h3_index_member")
    op.execute("DROP INDEX IF EXISTS ix_recordings_dataset_id_datetime")
    op.execute("DROP INDEX IF EXISTS ix_recordings_datetime")
    op.execute("DROP INDEX IF EXISTS ix_recordings_hash")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_recordings_h3_resolution'
            ) THEN
                ALTER TABLE recordings DROP CONSTRAINT ck_recordings_h3_resolution;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_recording_dataset_path'
            ) THEN
                ALTER TABLE recordings DROP CONSTRAINT uq_recording_dataset_path;
            END IF;
        END
        $$;
        """
    )

    # Drop new columns.
    for col in (
        "note",
        "time_expansion",
        "datetime_parse_error",
        "datetime_parse_status",
        "bit_depth",
        "hash",
        "filename",
    ):
        op.execute(f"ALTER TABLE recordings DROP COLUMN IF EXISTS {col}")

    # Loosen NOT NULL on duration/samplerate/channels (they were
    # nullable in the pre-Phase-13 baseline shape).
    op.execute("ALTER TABLE recordings ALTER COLUMN duration DROP NOT NULL")
    op.execute("ALTER TABLE recordings ALTER COLUMN samplerate DROP NOT NULL")
    op.execute("ALTER TABLE recordings ALTER COLUMN channels DROP NOT NULL")

    # Widen path back to TEXT.
    op.execute("ALTER TABLE recordings ALTER COLUMN path TYPE TEXT USING path::TEXT")

    # Loosen dataset_id back to nullable.
    op.execute("ALTER TABLE recordings ALTER COLUMN dataset_id DROP NOT NULL")

    # Restore project_id (nullable; no backfill source).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'project_id'
            ) THEN
                ALTER TABLE recordings ADD COLUMN project_id UUID;
                ALTER TABLE recordings
                    ADD CONSTRAINT recordings_project_id_fkey
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recordings_project_id ON recordings (project_id)"
    )

    # Reverse-rename the legacy columns.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'datetime'
            ) THEN
                ALTER TABLE recordings RENAME COLUMN datetime TO recorded_at;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'samplerate'
            ) THEN
                ALTER TABLE recordings RENAME COLUMN samplerate TO sample_rate;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recordings' AND column_name = 'duration'
            ) THEN
                ALTER TABLE recordings RENAME COLUMN duration TO duration_seconds;
            END IF;
        END
        $$;
        """
    )
