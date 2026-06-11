"""Repoint sampling_round_items FK to recording_annotations; drop annotations.

Revision ID: 0030
Revises: 0029
Create Date: 2026-06-11

P4 (Slice 1) of the annotation-consolidation effort. The active-learning write
paths (seed sampling + AL iterations in ``echoroo.workers.classifier_tasks``)
create canonical :class:`RecordingAnnotation` rows and write their ids into
``sampling_round_items.annotation_id``. That column's foreign key, however,
still targeted the minimal ``annotations`` table (the same table P2/P3 already
abandoned for the vote / comment subsystems). The two id-spaces are disjoint, so
every active-learning run hit an instant FK violation.

This migration converges ``sampling_round_items.annotation_id`` onto the
canonical ``recording_annotations`` id-space and removes the now-unused minimal
``annotations`` table entirely. The minimal table has no production writers
(only e2e seed fixtures) and, after P2/P3, no remaining FK references it.

Pre-launch decision (legacy-data compat is low priority): the disjoint
id-spaces mean any existing ``sampling_round_items`` rows (e2e seed only) cannot
be remapped onto ``recording_annotations`` ids, so ``upgrade()`` purges them
first, then drops + recreates the FK.

Like migration 0025 (legacy AnnotationProject removal), this is a forward-only
schema reduction: the baseline migration / phase-13 supporting DDL still create
``annotations`` at baseline-time, and this migration drops it later in the
chain, so a fresh-from-migrations head schema matches a fresh
``Base.metadata.create_all`` of the updated models (no ``Annotation`` ORM, FK ->
``recording_annotations``).
"""

from __future__ import annotations

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Disjoint id-spaces: existing sampling_round_items rows (e2e seed only)
    # reference minimal-annotations ids that have no recording_annotations
    # counterpart. Pre-launch, legacy-data compat is low priority, so purge
    # them before repointing the FK.
    op.execute("DELETE FROM sampling_round_items;")

    # --- sampling_round_items.annotation_id -> recording_annotations.id ----- #
    op.execute(
        "ALTER TABLE sampling_round_items "
        "DROP CONSTRAINT sampling_round_items_annotation_id_fkey;"
    )
    op.execute(
        "ALTER TABLE sampling_round_items "
        "ADD CONSTRAINT sampling_round_items_annotation_id_fkey "
        "FOREIGN KEY (annotation_id) "
        "REFERENCES recording_annotations (id) ON DELETE CASCADE;"
    )

    # --- Drop the now-unused minimal annotations table --------------------- #
    # Its index (ix_annotations_detection) drops with the table. The
    # ``annotationsource`` enum type is intentionally left in place (Postgres
    # does not drop it with the table, downgrade recreates the table against
    # it, and dropping it is out of scope for this slice).
    op.execute("DROP TABLE annotations;")


def downgrade() -> None:
    # NOTE: the sampling_round_items rows DELETEd in upgrade() are NOT restored
    # here — they were e2e seed fixtures only and cannot be reconstructed.

    # --- Recreate the minimal annotations table (baseline 0001 shape) ------ #
    # Mirrors apps/api/alembic/versions/0001_baseline_permissions_redesign.py
    # (the ``annotations`` create + its detection index). The
    # ``annotationsource`` enum was never dropped, so it is referenced here.
    op.execute(
        """
        CREATE TABLE annotations (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            detection_id UUID NOT NULL,
            user_id UUID,
            source annotationsource NOT NULL,
            taxon_id VARCHAR(64),
            label VARCHAR(200),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            PRIMARY KEY (id),
            FOREIGN KEY(detection_id) REFERENCES detections (id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users (id)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_annotations_detection ON annotations (detection_id);"
    )

    # --- Repoint sampling_round_items.annotation_id back to annotations.id -- #
    op.execute("DELETE FROM sampling_round_items;")
    op.execute(
        "ALTER TABLE sampling_round_items "
        "DROP CONSTRAINT sampling_round_items_annotation_id_fkey;"
    )
    op.execute(
        "ALTER TABLE sampling_round_items "
        "ADD CONSTRAINT sampling_round_items_annotation_id_fkey "
        "FOREIGN KEY (annotation_id) "
        "REFERENCES annotations (id) ON DELETE CASCADE;"
    )
