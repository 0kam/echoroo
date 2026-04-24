"""Add ground-truth annotation tables (spec 003-annotation).

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-17 00:00:00.000000

Introduces the ground-truth annotation subsystem used for cross-model
evaluation (BirdNET / Perch / Custom). Creates:

- ``annotation_sets`` — top-level reference collection scoped to a project +
  dataset with sampling parameters and lifecycle status.
- ``annotation_set_species_palette`` — M2M link to ``taxa`` for per-set
  palette curation (UI filter only; not an integrity boundary).
- ``annotation_segments`` — materialized fixed-length segments of recordings
  with ``is_empty`` marker and per-segment lifecycle status.
- ``time_range_annotations`` — ``[start, end]`` intervals inside a segment
  tagged with a single taxon (species). ``ON DELETE RESTRICT`` on taxon to
  protect ground-truth integrity.
- ``annotation_segment_notes`` / ``time_range_annotation_notes`` — secondary
  tables linking to the existing ``notes`` table.

Also performs two compatibility changes on the existing ``notes`` table:

- Adds the nullable-default-false ``is_issue`` boolean column required by
  the new note-attachment flows.
- Relaxes the legacy XOR CHECK constraint ``ck_note_exactly_one_parent``
  into ``ck_note_not_both_parents`` so that rows attached only via the new
  secondary tables (with both legacy FKs NULL) are permitted.

The existing detection-review ``Annotation`` / ``AnnotationVote`` tables are
intentionally left untouched; the new entity is named ``TimeRangeAnnotation``
to avoid any naming collision.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | None = None
depends_on: str | None = None


# ---------------------------------------------------------------------------
# Enum type names (shared between upgrade/downgrade)
# ---------------------------------------------------------------------------

ANNOTATION_SET_STATUS_NAME = "annotation_set_status"
ANNOTATION_SEGMENT_STATUS_NAME = "annotation_segment_status"


def upgrade() -> None:
    """Create annotation-set tables, indexes, enums, and touch ``notes``."""

    # --- Enum types --------------------------------------------------------
    # Use raw DDL (matching the pattern in 0012) so that the subsequent
    # ``create_type=False`` ENUM references below do not attempt to re-create
    # the type via checkfirst under async alembic.
    op.execute(
        "CREATE TYPE annotation_set_status AS ENUM "
        "('sampling', 'ready', 'in_progress', 'completed')"
    )
    op.execute(
        "CREATE TYPE annotation_segment_status AS ENUM "
        "('unannotated', 'annotated', 'skipped')"
    )

    # --- annotation_sets ---------------------------------------------------
    op.create_table(
        "annotation_sets",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("filter_date_range", JSONB(), nullable=True),
        sa.Column("filter_time_of_day_range", JSONB(), nullable=True),
        sa.Column("segment_length_sec", sa.Integer(), nullable=False),
        sa.Column("num_segments", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "sampling",
                "ready",
                "in_progress",
                "completed",
                name=ANNOTATION_SET_STATUS_NAME,
                create_type=False,
            ),
            nullable=False,
            server_default="sampling",
        ),
        sa.Column("sampling_warning", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.UniqueConstraint(
            "project_id", "name", name="uq_annotation_sets_project_name",
        ),
        sa.CheckConstraint(
            "segment_length_sec >= 10",
            name="ck_annotation_sets_segment_length_min",
        ),
        sa.CheckConstraint(
            "num_segments >= 1",
            name="ck_annotation_sets_num_segments_min",
        ),
    )
    op.create_index(
        "ix_annotation_sets_project_id", "annotation_sets", ["project_id"],
    )
    op.create_index(
        "ix_annotation_sets_dataset_id", "annotation_sets", ["dataset_id"],
    )
    op.create_index(
        "ix_annotation_sets_status", "annotation_sets", ["status"],
    )
    op.create_index(
        "ix_annotation_sets_project_status",
        "annotation_sets",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_annotation_sets_created_at", "annotation_sets", ["created_at"],
    )

    # --- annotation_set_species_palette ------------------------------------
    op.create_table(
        "annotation_set_species_palette",
        sa.Column("annotation_set_id", sa.UUID(), nullable=False),
        sa.Column("taxon_id", sa.UUID(), nullable=False),
        sa.Column(
            "position", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.PrimaryKeyConstraint("annotation_set_id", "taxon_id"),
        sa.ForeignKeyConstraint(
            ["annotation_set_id"],
            ["annotation_sets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxon_id"], ["taxa.id"], ondelete="CASCADE",
        ),
    )

    # --- annotation_segments ----------------------------------------------
    op.create_table(
        "annotation_segments",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("annotation_set_id", sa.UUID(), nullable=False),
        sa.Column("recording_id", sa.UUID(), nullable=False),
        sa.Column("start_time_sec", sa.Float(), nullable=False),
        sa.Column("end_time_sec", sa.Float(), nullable=False),
        sa.Column(
            "is_empty", sa.Boolean(), nullable=False, server_default=sa.false(),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "unannotated",
                "annotated",
                "skipped",
                name=ANNOTATION_SEGMENT_STATUS_NAME,
                create_type=False,
            ),
            nullable=False,
            server_default="unannotated",
        ),
        sa.Column("annotated_by_id", sa.UUID(), nullable=True),
        sa.Column("annotated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["annotation_set_id"],
            ["annotation_sets.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["recordings.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["annotated_by_id"], ["users.id"], ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "start_time_sec >= 0",
            name="ck_annotation_segments_start_nonneg",
        ),
        sa.CheckConstraint(
            "end_time_sec > start_time_sec",
            name="ck_annotation_segments_end_after_start",
        ),
    )
    op.create_index(
        "ix_annotation_segments_set_id",
        "annotation_segments",
        ["annotation_set_id"],
    )
    op.create_index(
        "ix_annotation_segments_recording_id",
        "annotation_segments",
        ["recording_id"],
    )
    op.create_index(
        "ix_annotation_segments_status", "annotation_segments", ["status"],
    )
    op.create_index(
        "ix_annotation_segments_set_status",
        "annotation_segments",
        ["annotation_set_id", "status"],
    )
    op.create_index(
        "ix_annotation_segments_created_at",
        "annotation_segments",
        ["created_at"],
    )

    # --- time_range_annotations -------------------------------------------
    op.create_table(
        "time_range_annotations",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("segment_id", sa.UUID(), nullable=False),
        sa.Column("start_time_sec", sa.Float(), nullable=False),
        sa.Column("end_time_sec", sa.Float(), nullable=False),
        sa.Column("taxon_id", sa.UUID(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["annotation_segments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxon_id"], ["taxa.id"], ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.CheckConstraint(
            "start_time_sec >= 0",
            name="ck_time_range_annotations_start_nonneg",
        ),
        sa.CheckConstraint(
            "end_time_sec > start_time_sec",
            name="ck_time_range_annotations_end_after_start",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_time_range_annotations_confidence_unit",
        ),
    )
    op.create_index(
        "ix_time_range_annotations_segment_id",
        "time_range_annotations",
        ["segment_id"],
    )
    op.create_index(
        "ix_time_range_annotations_taxon_id",
        "time_range_annotations",
        ["taxon_id"],
    )
    op.create_index(
        "ix_time_range_annotations_created_at",
        "time_range_annotations",
        ["created_at"],
    )

    # --- annotation_segment_notes -----------------------------------------
    op.create_table(
        "annotation_segment_notes",
        sa.Column("segment_id", sa.UUID(), nullable=False),
        sa.Column("note_id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("segment_id", "note_id"),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["annotation_segments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["note_id"], ["notes.id"], ondelete="CASCADE",
        ),
    )

    # --- time_range_annotation_notes --------------------------------------
    op.create_table(
        "time_range_annotation_notes",
        sa.Column("annotation_id", sa.UUID(), nullable=False),
        sa.Column("note_id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("annotation_id", "note_id"),
        sa.ForeignKeyConstraint(
            ["annotation_id"],
            ["time_range_annotations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["note_id"], ["notes.id"], ondelete="CASCADE",
        ),
    )

    # --- notes: is_issue + relaxed parent constraint ----------------------
    op.add_column(
        "notes",
        sa.Column(
            "is_issue",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=(
                "Quality-concern flag for ground-truth annotation notes "
                "(spec 003-annotation)."
            ),
        ),
    )
    op.drop_constraint(
        "ck_note_exactly_one_parent", "notes", type_="check",
    )
    op.create_check_constraint(
        "ck_note_not_both_parents",
        "notes",
        "NOT (clip_annotation_id IS NOT NULL AND sound_event_annotation_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Reverse all changes introduced in this migration."""

    # --- notes: restore legacy XOR constraint, drop is_issue --------------
    op.drop_constraint(
        "ck_note_not_both_parents", "notes", type_="check",
    )
    op.create_check_constraint(
        "ck_note_exactly_one_parent",
        "notes",
        (
            "(clip_annotation_id IS NOT NULL AND sound_event_annotation_id IS NULL) OR "
            "(clip_annotation_id IS NULL AND sound_event_annotation_id IS NOT NULL)"
        ),
    )
    op.drop_column("notes", "is_issue")

    # --- Association tables ------------------------------------------------
    op.drop_table("time_range_annotation_notes")
    op.drop_table("annotation_segment_notes")

    # --- TimeRangeAnnotations ---------------------------------------------
    op.drop_index(
        "ix_time_range_annotations_created_at",
        table_name="time_range_annotations",
    )
    op.drop_index(
        "ix_time_range_annotations_taxon_id",
        table_name="time_range_annotations",
    )
    op.drop_index(
        "ix_time_range_annotations_segment_id",
        table_name="time_range_annotations",
    )
    op.drop_table("time_range_annotations")

    # --- AnnotationSegments -----------------------------------------------
    op.drop_index(
        "ix_annotation_segments_created_at", table_name="annotation_segments",
    )
    op.drop_index(
        "ix_annotation_segments_set_status", table_name="annotation_segments",
    )
    op.drop_index(
        "ix_annotation_segments_status", table_name="annotation_segments",
    )
    op.drop_index(
        "ix_annotation_segments_recording_id",
        table_name="annotation_segments",
    )
    op.drop_index(
        "ix_annotation_segments_set_id", table_name="annotation_segments",
    )
    op.drop_table("annotation_segments")

    # --- Palette -----------------------------------------------------------
    op.drop_table("annotation_set_species_palette")

    # --- AnnotationSets ----------------------------------------------------
    op.drop_index(
        "ix_annotation_sets_created_at", table_name="annotation_sets",
    )
    op.drop_index(
        "ix_annotation_sets_project_status", table_name="annotation_sets",
    )
    op.drop_index(
        "ix_annotation_sets_status", table_name="annotation_sets",
    )
    op.drop_index(
        "ix_annotation_sets_dataset_id", table_name="annotation_sets",
    )
    op.drop_index(
        "ix_annotation_sets_project_id", table_name="annotation_sets",
    )
    op.drop_table("annotation_sets")

    # --- Enum types --------------------------------------------------------
    op.execute("DROP TYPE IF EXISTS annotation_segment_status")
    op.execute("DROP TYPE IF EXISTS annotation_set_status")
