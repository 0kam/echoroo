"""Repoint annotation_votes / annotation_comments FKs to recording_annotations.

Revision ID: 0028
Revises: 0027
Create Date: 2026-06-11

P2 of the annotation-consolidation effort (the launch-unblocker). The vote
and comment subsystems key on ``annotation_id`` but their foreign keys pointed
at the minimal ``annotations`` table, whereas every production writer (the
detection review grid and the search-results review screen) emits and POSTs a
``"recording_annotations_DEFERRED"`` id. The minimal ``annotations`` table has
no production writers (only e2e seed fixtures), so the two id-spaces are
disjoint and votes against real detections could never satisfy the FK.

This migration converges the FKs onto the canonical
``"recording_annotations_DEFERRED"`` id-space so detection voting / commenting
actually work end-to-end.

Pre-launch decision (legacy-data compat is low priority): the disjoint
id-spaces mean existing ``annotation_votes`` / ``annotation_comments`` rows
(only e2e seed fixtures) cannot be remapped onto ``recording_annotations`` ids,
so ``upgrade()`` DELETEs them first, then drops + recreates the FKs.

Identifier note: the target table is the transitional double-quoted mixed-case
identifier ``"recording_annotations_DEFERRED"``; raw SQL below preserves it
verbatim so PostgreSQL keeps the casing.
"""

from __future__ import annotations

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Disjoint id-spaces: existing vote/comment rows (e2e seed only) cannot map
    # onto recording_annotations ids. Pre-launch, legacy-data compat is low
    # priority, so purge them before repointing the FKs.
    op.execute("DELETE FROM annotation_votes;")
    op.execute("DELETE FROM annotation_comments;")

    # --- annotation_votes.annotation_id -> recording_annotations_DEFERRED.id --
    op.execute(
        "ALTER TABLE annotation_votes "
        "DROP CONSTRAINT annotation_votes_annotation_id_fkey;"
    )
    op.execute(
        "ALTER TABLE annotation_votes "
        "ADD CONSTRAINT annotation_votes_annotation_id_fkey "
        'FOREIGN KEY (annotation_id) '
        'REFERENCES "recording_annotations_DEFERRED" (id) ON DELETE CASCADE;'
    )

    # --- annotation_comments.annotation_id -> recording_annotations_DEFERRED.id
    op.execute(
        "ALTER TABLE annotation_comments "
        "DROP CONSTRAINT annotation_comments_annotation_id_fkey;"
    )
    op.execute(
        "ALTER TABLE annotation_comments "
        "ADD CONSTRAINT annotation_comments_annotation_id_fkey "
        'FOREIGN KEY (annotation_id) '
        'REFERENCES "recording_annotations_DEFERRED" (id) ON DELETE CASCADE;'
    )


def downgrade() -> None:
    # NOTE: the vote/comment rows DELETEd in upgrade() are NOT restored here —
    # they were e2e seed fixtures only and cannot be reconstructed. This
    # downgrade reverses only the FK repoint, returning the constraints to the
    # minimal ``annotations`` table.

    # --- annotation_comments.annotation_id -> annotations.id ----------------
    op.execute(
        "ALTER TABLE annotation_comments "
        "DROP CONSTRAINT annotation_comments_annotation_id_fkey;"
    )
    op.execute(
        "ALTER TABLE annotation_comments "
        "ADD CONSTRAINT annotation_comments_annotation_id_fkey "
        "FOREIGN KEY (annotation_id) "
        "REFERENCES annotations (id) ON DELETE CASCADE;"
    )

    # --- annotation_votes.annotation_id -> annotations.id -------------------
    op.execute(
        "ALTER TABLE annotation_votes "
        "DROP CONSTRAINT annotation_votes_annotation_id_fkey;"
    )
    op.execute(
        "ALTER TABLE annotation_votes "
        "ADD CONSTRAINT annotation_votes_annotation_id_fkey "
        "FOREIGN KEY (annotation_id) "
        "REFERENCES annotations (id) ON DELETE CASCADE;"
    )
