"""Add segment_mode to annotation_sets and relax segment_length_sec.

Revision ID: 0026
Revises: 0025
Create Date: 2026-06-09

Adds a ``segment_mode`` discriminator to ``annotation_sets`` so a set can be
materialized either as fixed-length sliding-window slots (the existing,
default behaviour) or as one full-length segment per recording
(``whole_recording``).

A plain ``VARCHAR`` + CHECK constraint is used instead of a native PostgreSQL
enum: the value set is small and additive, and a string column avoids the
``ALTER TYPE`` / type-drop overhead a native enum would impose on future
changes.

Operations:
1. Add ``segment_mode VARCHAR(20) NOT NULL DEFAULT 'fixed'`` (existing rows
   backfill to ``'fixed'`` via the server default).
2. Add a CHECK constraint restricting ``segment_mode`` to the known values.
3. Make ``segment_length_sec`` nullable (whole-recording sets store NULL).
4. Replace the old ``ck_annotation_sets_segment_length_min`` constraint with a
   conditional one: a length >= 10 is required only when
   ``segment_mode <> 'whole_recording'``.

Forward-only is acceptable, but a sane downgrade is provided (the legacy
neighbours that refuse downgrade do so because they are destructive; this
migration is reversible as long as no whole-recording sets exist).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # 1. Add segment_mode with a server default so existing rows backfill to
    #    'fixed' without a separate UPDATE.
    op.add_column(
        "annotation_sets",
        sa.Column(
            "segment_mode",
            sa.String(length=20),
            nullable=False,
            server_default="fixed",
        ),
    )

    # 2. Restrict segment_mode to the known value set.
    op.create_check_constraint(
        "ck_annotation_sets_segment_mode_valid",
        "annotation_sets",
        "segment_mode IN ('fixed', 'whole_recording')",
    )

    # 3. Allow NULL segment_length_sec (whole-recording sets do not use it).
    op.alter_column(
        "annotation_sets",
        "segment_length_sec",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # 4. Replace the unconditional length check with a mode-aware one.
    op.drop_constraint(
        "ck_annotation_sets_segment_length_min",
        "annotation_sets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_annotation_sets_segment_length_min",
        "annotation_sets",
        "segment_mode = 'whole_recording' OR segment_length_sec >= 10",
    )


def downgrade() -> None:
    # Reverse order. NOTE: this will fail if any whole_recording sets exist
    # (their segment_length_sec is NULL and cannot satisfy the restored
    # NOT NULL / >= 10 constraint). Resolve such rows before downgrading.
    op.drop_constraint(
        "ck_annotation_sets_segment_length_min",
        "annotation_sets",
        type_="check",
    )
    op.create_check_constraint(
        "ck_annotation_sets_segment_length_min",
        "annotation_sets",
        "segment_length_sec >= 10",
    )

    op.alter_column(
        "annotation_sets",
        "segment_length_sec",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.drop_constraint(
        "ck_annotation_sets_segment_mode_valid",
        "annotation_sets",
        type_="check",
    )
    op.drop_column("annotation_sets", "segment_mode")
