"""ToriTore (とりトレ) proficiency integration (preview-only).

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-08 00:00:00.000000

Adds the schema surface for the ToriTore integration (internal research
preview):

New tables
* ``toritore_test_results`` — one row per uploaded ToriTore test, owned by
  the uploading Echoroo user. Unique on
  ``(user_id, source_timestamp, test_number)`` for idempotent re-upload.
* ``toritore_species_scores`` — one row per species per test, CASCADE on
  the owning test, best-effort FK to ``taxa`` by GBIF key.

Column additions (preserved annotation-set side)
* ``annotation_sets.min_total_score`` (FLOAT NULL) — participation-gate
  threshold; NULL = no requirement.
* ``time_range_annotations.annotator_species_score`` (FLOAT NULL),
  ``annotator_total_score`` (FLOAT NULL),
  ``annotator_test_reference`` (VARCHAR(200) NULL) — per-annotation
  proficiency snapshot taken at creation time.

``downgrade`` reverses every change so the preview branch can be reset.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create ToriTore tables and add gate/snapshot columns."""

    # --- toritore_test_results ------------------------------------------------
    op.create_table(
        "toritore_test_results",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("toritore_user_id", sa.String(length=100), nullable=True),
        sa.Column("toritore_user_name", sa.String(length=200), nullable=True),
        sa.Column("toritore_project_id", sa.String(length=100), nullable=True),
        sa.Column("toritore_project_name", sa.String(length=200), nullable=True),
        sa.Column(
            "source_timestamp",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("test_number", sa.Integer(), nullable=False),
        sa.Column("test_timestamp", sa.String(length=100), nullable=True),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_json", pg.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "user_id",
            "source_timestamp",
            "test_number",
            name="uq_toritore_test_results_user_source_test",
        ),
    )
    op.create_index(
        "ix_toritore_test_results_user_id",
        "toritore_test_results",
        ["user_id"],
    )

    # --- toritore_species_scores ----------------------------------------------
    op.create_table(
        "toritore_species_scores",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "test_result_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("toritore_test_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gbif_taxon_key", sa.Integer(), nullable=True),
        sa.Column("species_name", sa.String(length=300), nullable=True),
        sa.Column("is_correct", sa.SmallInteger(), nullable=False),
        sa.Column(
            "taxon_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("taxa.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_toritore_species_scores_test_result_id",
        "toritore_species_scores",
        ["test_result_id"],
    )
    op.create_index(
        "ix_toritore_species_scores_gbif_taxon_key",
        "toritore_species_scores",
        ["gbif_taxon_key"],
    )

    # --- annotation_sets.min_total_score --------------------------------------
    op.add_column(
        "annotation_sets",
        sa.Column("min_total_score", sa.Float(), nullable=True),
    )

    # --- time_range_annotations snapshot columns ------------------------------
    op.add_column(
        "time_range_annotations",
        sa.Column("annotator_species_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "time_range_annotations",
        sa.Column("annotator_total_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "time_range_annotations",
        sa.Column(
            "annotator_test_reference", sa.String(length=200), nullable=True
        ),
    )


def downgrade() -> None:
    """Drop ToriTore tables and remove gate/snapshot columns."""

    op.drop_column("time_range_annotations", "annotator_test_reference")
    op.drop_column("time_range_annotations", "annotator_total_score")
    op.drop_column("time_range_annotations", "annotator_species_score")

    op.drop_column("annotation_sets", "min_total_score")

    op.drop_index(
        "ix_toritore_species_scores_gbif_taxon_key",
        table_name="toritore_species_scores",
    )
    op.drop_index(
        "ix_toritore_species_scores_test_result_id",
        table_name="toritore_species_scores",
    )
    op.drop_table("toritore_species_scores")

    op.drop_index(
        "ix_toritore_test_results_user_id",
        table_name="toritore_test_results",
    )
    op.drop_table("toritore_test_results")
