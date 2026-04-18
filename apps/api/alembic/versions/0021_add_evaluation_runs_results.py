"""Add cross-model evaluation tables (spec 003-annotation, Phase A3).

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-17 00:00:00.000000

Introduces persistence for cross-model evaluation runs that score detection
models (BirdNET, Perch, Custom) against a ground-truth :class:`AnnotationSet`
using the symmetric-overlap rule from ``specs/003-annotation/research.md``
§4.

Creates:

- ``evaluation_run_status`` enum (``pending | running | completed | failed``).
- ``evaluation_runs`` — one row per evaluation request with a JSONB list of
  requested model references and lifecycle metadata.
- ``evaluation_results`` — one aggregated row per ``(run, model_ref, taxon)``.
  ``taxon_id IS NULL`` denotes the overall (all-species) bucket.

Indexes:

- ``ix_evaluation_runs_annotation_set_id`` / ``ix_evaluation_runs_status`` /
  ``ix_evaluation_runs_created_at``.
- ``ix_evaluation_results_run_id`` and composite
  ``ix_evaluation_results_run_taxon``.

Downgrade drops both tables and the enum type.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | None = None
depends_on: str | None = None


EVALUATION_RUN_STATUS_NAME = "evaluation_run_status"


def upgrade() -> None:
    """Create the evaluation_runs and evaluation_results tables."""

    # --- Enum --------------------------------------------------------------
    op.execute(
        "CREATE TYPE evaluation_run_status AS ENUM "
        "('pending', 'running', 'completed', 'failed')"
    )

    # --- evaluation_runs ---------------------------------------------------
    op.create_table(
        "evaluation_runs",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("annotation_set_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "completed",
                "failed",
                name=EVALUATION_RUN_STATUS_NAME,
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("requested_model_refs", JSONB(), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
    )
    op.create_index(
        "ix_evaluation_runs_annotation_set_id",
        "evaluation_runs",
        ["annotation_set_id"],
    )
    op.create_index(
        "ix_evaluation_runs_status",
        "evaluation_runs",
        ["status"],
    )
    op.create_index(
        "ix_evaluation_runs_created_at",
        "evaluation_runs",
        ["created_at"],
    )

    # --- evaluation_results ------------------------------------------------
    op.create_table(
        "evaluation_results",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("evaluation_run_id", sa.UUID(), nullable=False),
        sa.Column("model_ref", JSONB(), nullable=False),
        sa.Column("taxon_id", sa.UUID(), nullable=True),
        sa.Column(
            "tp_precision", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column("fp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "tp_recall", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column("fn", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "precision", sa.Float(), nullable=False, server_default="0",
        ),
        sa.Column("recall", sa.Float(), nullable=False, server_default="0"),
        sa.Column("f1", sa.Float(), nullable=False, server_default="0"),
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
            ["evaluation_run_id"],
            ["evaluation_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxon_id"], ["taxa.id"], ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_evaluation_results_run_id",
        "evaluation_results",
        ["evaluation_run_id"],
    )
    op.create_index(
        "ix_evaluation_results_run_taxon",
        "evaluation_results",
        ["evaluation_run_id", "taxon_id"],
    )


def downgrade() -> None:
    """Drop the evaluation_* tables and the enum type."""

    op.drop_index(
        "ix_evaluation_results_run_taxon", table_name="evaluation_results",
    )
    op.drop_index(
        "ix_evaluation_results_run_id", table_name="evaluation_results",
    )
    op.drop_table("evaluation_results")

    op.drop_index(
        "ix_evaluation_runs_created_at", table_name="evaluation_runs",
    )
    op.drop_index("ix_evaluation_runs_status", table_name="evaluation_runs")
    op.drop_index(
        "ix_evaluation_runs_annotation_set_id", table_name="evaluation_runs",
    )
    op.drop_table("evaluation_runs")

    op.execute("DROP TYPE evaluation_run_status")
