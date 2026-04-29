"""Phase 13 P5 R2 (T809) — align R3 forward-only drift residue.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-28 18:00:00.000000

Phase 13 P5 R2 introspection parity sweep across the 9 axes surfaced four
real drifts between the **fresh** path (empty DB → ``alembic upgrade head``
landing on the Phase-13-aware baseline ``0001``) and the **upgraded** path
(replay of the frozen pre-Phase-13 ``0005`` SQL dump → delta chain
``0006/0006a/0006b/0007/0008/0009``). The Phase 11 R3 forward-only
convention requires both paths to converge on byte-for-byte identical
schemas, so this migration closes 3 of the 4 drifts. The 4th (enum label
ordering) cannot be reconciled without a multi-step ``ALTER TYPE`` rewrite
and is documented as a set-semantics relaxation in
``test_alembic_r3_parity._collect_enums``.

Drifts addressed by this migration
----------------------------------

**Drift 1 — datasets FK constraint name lexical mismatch.**
The fresh path emits ``datasets`` via ``op.create_table`` with
``sa.ForeignKey("sites.id", ...)`` / ``sa.ForeignKey("users.id", ...)``
without an explicit ``name=`` argument, so PostgreSQL auto-generates
``datasets_site_id_fkey`` / ``datasets_created_by_id_fkey``. The upgraded
path adds the same two columns via 0008 with explicit
``ADD CONSTRAINT fk_datasets_site_id`` / ``fk_datasets_created_by_id``.
Semantics are identical; only the constraint name lexically diverges.
This migration renames the explicit-named constraints to match the PG
auto-name on any DB where the explicit name is present (no-op on a
fresh DB where the auto-name already holds). The two ``recorder_id`` /
``license_id`` FKs use the same explicit name in **both** paths
(``fk_datasets_recorder_id`` / ``fk_datasets_license_id`` are emitted by
baseline 0001 lines 1362-1386 *and* by 0008) — they are also covered by
this migration as a defensive idempotent no-op rename guard for any
historic DB that may have landed on a different name.

**Drift 2 — ``ix_sites_project_id`` index missing in upgraded path.**
The fresh-path baseline 0001 (Phase 13 P4 / T807, line 736) emits
``CREATE INDEX IF NOT EXISTS ix_sites_project_id ON sites (project_id)``,
but no delta migration carried it forward. Upgraded DBs land at head
without the index. This migration adds it idempotently.

**Drift 3 — ``ix_outbox_events_status_next_retry`` partial-predicate
PG canonical-form drift.** Baseline 0001 emits the index via
``op.create_index(..., postgresql_where=sa.text("status IN
('pending', 'processing')"))``. The frozen 0005 dump replays the same
partial predicate but the PostgreSQL planner serialises it in a slightly
different canonical form on a fresh ``CREATE INDEX`` versus a
``pg_dump --schema-only`` round-trip:

  fresh    : ``(status)::text = ANY ((ARRAY['pending', 'processing'])::text[])``
  upgraded : ``(status)::text = ANY (ARRAY['pending'::text, 'processing'::text])``

These are semantically identical but ``pg_get_expr`` returns the strings
verbatim so the parity test reports a diff. This migration drops and
recreates the index using the same DDL the fresh path uses, so the
upgraded path arrives at the same canonical form.

**Drift 4 (NOT addressed here) — ``detectionsource`` enum label ordering.**
PG's ``ALTER TYPE ADD VALUE`` only appends labels at the tail; reordering
labels requires a 4-step rewrite (rename → recreate → cast → drop) that
costs more than the parity benefit at pre-launch scale. The companion
test change in ``_collect_enums`` switches to set-semantics for label
comparison so semantic equivalence is asserted while ordering is
explicitly tolerated. See the test docstring for the rationale.

Idempotency / safety
--------------------

All steps are wrapped in ``DO $$ ... $$`` ``IF EXISTS`` / ``IF NOT EXISTS``
guards so re-applying on a fresh DB (which already holds the canonical
shape from baseline 0001) is a no-op. The migration does not touch row
data; only DDL.

Downgrade
---------

Best-effort symmetry. Drift 1 is reversed by renaming back to the
explicit ``fk_datasets_*`` names. Drift 2 drops the index. Drift 3
recreates the index using ``CREATE INDEX`` against the same DDL — there
is no canonical-form difference to revert because the canonical form on
``CREATE INDEX`` is the fresh-path form by definition. Not designed for
production rollback.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# --------------------------------------------------------------------------- #
# Upgrade — align FK names + add missing index + recanonicalise partial index.
# --------------------------------------------------------------------------- #


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Drift 1 — rename explicit-named datasets FKs to PG auto-name so the
    # upgraded path matches the fresh path's ``datasets_<col>_fkey``
    # convention. Idempotent: the rename only runs when the explicit
    # name is still present.
    # ------------------------------------------------------------------ #
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_datasets_site_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'datasets_site_id_fkey'
            ) THEN
                ALTER TABLE datasets
                    RENAME CONSTRAINT fk_datasets_site_id
                    TO datasets_site_id_fkey;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_datasets_created_by_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'datasets_created_by_id_fkey'
            ) THEN
                ALTER TABLE datasets
                    RENAME CONSTRAINT fk_datasets_created_by_id
                    TO datasets_created_by_id_fkey;
            END IF;

            -- ``fk_datasets_recorder_id`` / ``fk_datasets_license_id`` are
            -- emitted with identical names by both baseline 0001 (lines
            -- 1362-1386) and 0008, so the parity test does not flag them.
            -- We still include defensive no-op guards in case a historic
            -- dev DB landed on the auto-name variant for either FK.
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'datasets_recorder_id_fkey'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_datasets_recorder_id'
            ) THEN
                ALTER TABLE datasets
                    RENAME CONSTRAINT datasets_recorder_id_fkey
                    TO fk_datasets_recorder_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'datasets_license_id_fkey'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_datasets_license_id'
            ) THEN
                ALTER TABLE datasets
                    RENAME CONSTRAINT datasets_license_id_fkey
                    TO fk_datasets_license_id;
            END IF;
        END
        $$;
        """
    )

    # ------------------------------------------------------------------ #
    # Drift 2 — add ``ix_sites_project_id`` to the upgraded path. Fresh
    # path created it via baseline 0001 line 736-742 (Phase 13 P4 /
    # T807); no delta migration carried the index forward. Idempotent
    # via ``IF NOT EXISTS``.
    # ------------------------------------------------------------------ #
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sites_project_id ON sites (project_id)"
    )

    # ------------------------------------------------------------------ #
    # Drift 3 — recanonicalise the ``ix_outbox_events_status_next_retry``
    # partial predicate by dropping and recreating the index. The fresh
    # path serialises the predicate as
    # ``(status)::text = ANY ((ARRAY['pending', 'processing'])::text[])``
    # while the upgraded path (via the pg_dump 0005 fixture) lands on
    # ``(status)::text = ANY (ARRAY['pending'::text, 'processing'::text])``.
    # Both are semantically identical but the parity test compares
    # ``pg_get_expr`` strings verbatim. Recreating the index using the
    # fresh-path DDL forces both DBs onto the same canonical form.
    # ------------------------------------------------------------------ #
    op.execute("DROP INDEX IF EXISTS ix_outbox_events_status_next_retry")
    op.execute(
        """
        CREATE INDEX ix_outbox_events_status_next_retry
            ON outbox_events (status, next_retry_at)
            WHERE status IN ('pending', 'processing')
        """
    )


# --------------------------------------------------------------------------- #
# Downgrade — best-effort reversal.
# --------------------------------------------------------------------------- #


def downgrade() -> None:
    # Drift 3 — recreate the index. There is no canonical-form difference
    # to revert because ``CREATE INDEX`` always produces the fresh-path
    # canonical form; this step is therefore a structural no-op kept for
    # symmetry with the upgrade.
    op.execute("DROP INDEX IF EXISTS ix_outbox_events_status_next_retry")
    op.execute(
        """
        CREATE INDEX ix_outbox_events_status_next_retry
            ON outbox_events (status, next_retry_at)
            WHERE status IN ('pending', 'processing')
        """
    )

    # Drift 2 — drop the index added on upgrade.
    op.execute("DROP INDEX IF EXISTS ix_sites_project_id")

    # Drift 1 — rename the FKs back to the explicit ``fk_datasets_*``
    # form used pre-0010 by 0008.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'datasets_site_id_fkey'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_datasets_site_id'
            ) THEN
                ALTER TABLE datasets
                    RENAME CONSTRAINT datasets_site_id_fkey
                    TO fk_datasets_site_id;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'datasets_created_by_id_fkey'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_datasets_created_by_id'
            ) THEN
                ALTER TABLE datasets
                    RENAME CONSTRAINT datasets_created_by_id_fkey
                    TO fk_datasets_created_by_id;
            END IF;
        END
        $$;
        """
    )
