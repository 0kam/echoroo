"""Phase 13 P1.5 (T804) — same-name table drift reconcile.

Revision ID: 0007
Revises: 0006b
Create Date: 2026-04-28 06:00:00.000000

This migration reconciles the three tables that exist on **both** sides of
the ORM/DB three-way diff (per ``/tmp/phase13-inventory.md`` section (4)):

* **annotations** — DB is the source of truth (the
  ``id, detection_id, user_id, source, taxon_id, label, created_at,
  updated_at`` shape created by baseline ``0001``). The recording-level
  fields the ORM previously declared (``recording_id``, ``tag_id``,
  ``status``, ``confidence``, ``start_time``, ``end_time``,
  ``freq_low / high``, ``reviewed_by_id``, ``reviewed_at``,
  ``search_session_id``, ``detection_run_id``) live only in the ORM today
  and are deferred to **Phase 14+** when a separate ``recording_annotations``
  table reinstates them. The ORM layer keeps the rich shape so existing
  Phase 6 contract tests (which use ``Base.metadata.create_all`` to
  materialise the test DB) still operate against the columns they expect.
  No DB-side change is required from this migration. See the docstring on
  :class:`echoroo.models.annotation.Annotation` for the bridging strategy.

* **tags** — ORM is the source of truth (taxa-based shape with a
  UUID ``taxon_id`` FK to ``taxa``, ``parent_id`` self-FK,
  ``gbif_taxon_key``, ``scientific_name``, ``common_name``). Existing dev
  DBs that arrive at this revision via the ``0001 → 0005 → 0006*`` chain
  carry only the legacy ``taxon_id`` ``VARCHAR(64)`` column, so we apply
  the canonical 5-step backfill from ``/tmp/plan-merged-v5-final.md`` §0.4.
  Fresh databases built directly from baseline ``0001`` already arrive in
  the final shape (the baseline file was edited in this same Phase 13 P1.5
  task to materialise the taxa-based form on first ``upgrade``); for them
  every step below short-circuits via the ``IF (NOT) EXISTS`` guards.

* **annotation_votes** — DB is the source of truth (the spec-aligned
  ``voter_user_id`` / ``project_id`` / ``vote smallint`` shape created by
  baseline ``0001``). The ORM was previously declaring
  ``user_id`` / ``vote::votetype`` / ``signal_quality`` / ``note`` /
  ``suggested_tag_id`` columns that no longer exist on the DB. The ORM
  rewrite happens in this same Phase 13 P1.5 task
  (``apps/api/echoroo/models/annotation_vote.py``); no DDL change is
  required here.

* **annotation_comments** — already aligned, no-op.

The migration is intentionally idempotent: every ``ALTER TABLE`` /
``CREATE INDEX`` / FK addition is guarded with a ``DO $$ ... $$``
``IF NOT EXISTS`` / ``IF EXISTS`` block so it can be re-applied on a
fresh DB (which already reaches the final shape via baseline ``0001``)
without raising. See ``/tmp/plan-merged-v5-final.md`` §0.4 for the
canonical recipe.

Phase 13 P1.5 also introduces a TODO marker for Phase 14+: the DB-truth
``annotations`` shape lacks the recording-level review state. The follow-up
phase will add a ``recording_annotations`` table whose row maps a recording
+ time region + tag onto a review-state lifecycle (status / confidence /
voting / review history). Until that lands, the rich ORM annotation row is
purely an in-memory test artefact.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006b"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# --------------------------------------------------------------------------- #
# Upgrade — tags 5-step backfill (the only DB-side reconcile in this revision)
# --------------------------------------------------------------------------- #


def upgrade() -> None:
    # ----------------------------------------------------------------- #
    # Step 1 + 2: rename legacy ``taxon_id`` (VARCHAR(64)) to
    # ``legacy_taxon_id`` and introduce the new UUID ``taxon_id`` column.
    # Idempotent: fresh DBs (baseline 0001 already materialised the new
    # shape) skip both branches.
    # ----------------------------------------------------------------- #
    op.execute(
        """
        DO $$
        BEGIN
            -- (a) Rename the legacy str64 column out of the way iff the
            --     UUID-shaped ``taxon_id`` does not yet exist.
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags'
                  AND column_name = 'taxon_id'
                  AND data_type = 'character varying'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags'
                  AND column_name = 'legacy_taxon_id'
            ) THEN
                ALTER TABLE tags RENAME COLUMN taxon_id TO legacy_taxon_id;
            END IF;

            -- (b) Add the new UUID-typed ``taxon_id`` column iff missing.
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags'
                  AND column_name = 'taxon_id'
                  AND data_type = 'uuid'
            ) THEN
                ALTER TABLE tags ADD COLUMN taxon_id UUID NULL;
            END IF;
        END
        $$;
        """
    )

    # ----------------------------------------------------------------- #
    # Step 3: add the four ORM-side columns that the legacy schema lacked
    # (``parent_id``, ``gbif_taxon_key``, ``scientific_name``,
    # ``common_name``). Each ALTER is wrapped in IF NOT EXISTS so that
    # both fresh and migrated DBs converge on the same final shape.
    # ----------------------------------------------------------------- #
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'parent_id'
            ) THEN
                ALTER TABLE tags
                ADD COLUMN parent_id UUID NULL
                REFERENCES tags(id) ON DELETE SET NULL;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'gbif_taxon_key'
            ) THEN
                ALTER TABLE tags ADD COLUMN gbif_taxon_key INTEGER NULL;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'scientific_name'
            ) THEN
                ALTER TABLE tags ADD COLUMN scientific_name VARCHAR(200) NULL;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'common_name'
            ) THEN
                ALTER TABLE tags ADD COLUMN common_name VARCHAR(200) NULL;
            END IF;
        END
        $$;
        """
    )

    # ----------------------------------------------------------------- #
    # Step 4: backfill ``taxon_id`` from ``legacy_taxon_id`` by looking
    # up GBIF keys against the ``taxa`` table. Pre-launch dev DBs are
    # expected to have zero rows in ``tags``, so this UPDATE typically
    # affects 0 rows. Mal-formed legacy values are left as NULL — frontend
    # re-tagging handles them in Phase 14+.
    # ----------------------------------------------------------------- #
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'legacy_taxon_id'
            ) THEN
                UPDATE tags t
                SET taxon_id = tx.id
                FROM taxa tx
                WHERE tx.gbif_taxon_key IS NOT NULL
                  AND t.legacy_taxon_id ~ '^[0-9]+$'
                  AND tx.gbif_taxon_key = t.legacy_taxon_id::INTEGER
                  AND t.taxon_id IS NULL;
            END IF;
        END
        $$;
        """
    )

    # ----------------------------------------------------------------- #
    # Step 5: install the FK + supporting index, then drop the legacy
    # column. Each branch is wrapped IF NOT EXISTS / IF EXISTS so reruns
    # stay idempotent.
    # ----------------------------------------------------------------- #
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_tags_taxon_id'
            ) THEN
                ALTER TABLE tags
                ADD CONSTRAINT fk_tags_taxon_id
                FOREIGN KEY (taxon_id) REFERENCES taxa(id) ON DELETE SET NULL;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_class
                WHERE relname = 'ix_tags_taxon_id' AND relkind = 'i'
            ) THEN
                CREATE INDEX ix_tags_taxon_id ON tags(taxon_id);
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'legacy_taxon_id'
            ) THEN
                ALTER TABLE tags DROP COLUMN legacy_taxon_id;
            END IF;
        END
        $$;
        """
    )

    # ----------------------------------------------------------------- #
    # Phase 13 P1.5 R2 (Codex follow-up — Major):
    # ``annotation_votes (annotation_id, voter_user_id)`` UNIQUE constraint.
    # The ORM has been declaring this since Phase 6 but earlier baselines
    # forgot to materialise it on the DB; a race between two parallel
    # ``cast_vote`` calls could persist two rows for the same (annotation,
    # voter) pair on a stale DB. Idempotent so fresh DBs (baseline ``0001``
    # already includes the constraint after this revision's batch edit)
    # short-circuit. The constraint name matches the ORM declaration in
    # ``echoroo.models.annotation_vote`` and the baseline 0001 batch edit.
    # ----------------------------------------------------------------- #
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_annotation_vote_user'
            ) THEN
                ALTER TABLE annotation_votes
                ADD CONSTRAINT uq_annotation_vote_user
                UNIQUE (annotation_id, voter_user_id);
            END IF;
        END
        $$;
        """
    )


# --------------------------------------------------------------------------- #
# Downgrade — revert the tags 5-step. This drops the new columns and
# reinstates the legacy ``taxon_id VARCHAR(64)`` column. Since this
# migration is part of the Phase 13 P1.5 reconcile and there is no
# legacy data to preserve in dev / pre-launch, the downgrade only restores
# enough shape for the previous revision (``0006b``) to round-trip.
# --------------------------------------------------------------------------- #


def downgrade() -> None:
    # Phase 13 P1.5 R2: drop the annotation_votes unique constraint added in
    # the upgrade. The constraint stays on baseline-fresh DBs because the
    # baseline 0001 batch edit also includes it; this branch only runs for
    # DBs that were stamped at 0006b or earlier.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_annotation_vote_user'
            ) THEN
                ALTER TABLE annotation_votes
                DROP CONSTRAINT uq_annotation_vote_user;
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_tags_taxon_id'
            ) THEN
                ALTER TABLE tags DROP CONSTRAINT fk_tags_taxon_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_class
                WHERE relname = 'ix_tags_taxon_id' AND relkind = 'i'
            ) THEN
                DROP INDEX ix_tags_taxon_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'taxon_id'
                  AND data_type = 'uuid'
            ) THEN
                ALTER TABLE tags DROP COLUMN taxon_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'parent_id'
            ) THEN
                ALTER TABLE tags DROP COLUMN parent_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'gbif_taxon_key'
            ) THEN
                ALTER TABLE tags DROP COLUMN gbif_taxon_key;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'scientific_name'
            ) THEN
                ALTER TABLE tags DROP COLUMN scientific_name;
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'common_name'
            ) THEN
                ALTER TABLE tags DROP COLUMN common_name;
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'tags' AND column_name = 'taxon_id'
            ) THEN
                ALTER TABLE tags ADD COLUMN taxon_id VARCHAR(64) NULL;
            END IF;
        END
        $$;
        """
    )
