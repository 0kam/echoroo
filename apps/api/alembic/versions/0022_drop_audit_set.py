"""Drop audit_set_items table, custom_models.audit_metrics column, and the
``audit_set`` value from the ``detectionsource`` enum.

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-17 00:00:00.000000

The Audit Set feature (score-stratified blind audit for custom classifiers)
has been superseded by the AnnotationSet / EvaluationRun based evaluation
introduced in specs/003-annotation (Phases A-C). This migration removes all
backend schema artefacts that backed the old feature:

- ``audit_set_items`` table.
- ``custom_models.audit_metrics`` column (JSONB).
- ``audit_set`` value from the ``detectionsource`` enum.

PostgreSQL does not support dropping an enum value directly, so the enum is
recreated without the ``audit_set`` value. Any residual annotations sourced
from ``audit_set`` would block the rewrite, so they are removed first.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# Revision identifiers used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | None = None
depends_on: str | None = None


_DETECTIONSOURCE_KEEP_VALUES = (
    "birdnet",
    "perch",
    "perch_search",
    "similarity_search",
    "custom_svm",
    "human",
    "sampling_round",
)


def upgrade() -> None:
    """Remove audit_set artefacts from the schema."""

    # --- audit_set_items ---------------------------------------------------
    # Drop indexes defensively — 0017 created ``ix_audit_model``; any
    # SQLAlchemy-generated composite names from the model are covered by
    # ``IF EXISTS`` to keep the downgrade safe across environments.
    op.execute("DROP INDEX IF EXISTS ix_audit_model")
    op.execute("DROP INDEX IF EXISTS ix_audit_set_items_custom_model_id")
    op.execute("DROP INDEX IF EXISTS ix_audit_set_items_embedding_id")
    op.execute("DROP INDEX IF EXISTS ix_audit_set_items_annotation_id")
    op.drop_table("audit_set_items")

    # --- custom_models.audit_metrics --------------------------------------
    op.drop_column("custom_models", "audit_metrics")

    # --- detectionsource enum: remove ``audit_set`` ------------------------
    # Clean up any stray annotations that still reference the value before
    # rewriting the enum type. No rows are expected in production because the
    # audit_set_items cascade would have been dropped already, but we do a
    # safety pass for any orphan rows.
    op.execute(
        "DELETE FROM annotations WHERE source::text = 'audit_set'"
    )

    # Rebuild the enum without ``audit_set``.
    new_values = ", ".join(f"'{v}'" for v in _DETECTIONSOURCE_KEEP_VALUES)
    op.execute("ALTER TYPE detectionsource RENAME TO detectionsource_old")
    op.execute(f"CREATE TYPE detectionsource AS ENUM ({new_values})")
    op.execute(
        "ALTER TABLE annotations "
        "ALTER COLUMN source TYPE detectionsource "
        "USING source::text::detectionsource"
    )
    op.execute("DROP TYPE detectionsource_old")


def downgrade() -> None:
    """Re-create audit_set_items, audit_metrics, and the audit_set enum value.

    The recreated schema matches migration 0017. Any previously stored audit
    data is not recoverable — the table is created empty.
    """

    # --- detectionsource enum: add ``audit_set`` back ---------------------
    op.execute("ALTER TYPE detectionsource ADD VALUE IF NOT EXISTS 'audit_set'")

    # --- custom_models.audit_metrics --------------------------------------
    op.add_column(
        "custom_models",
        sa.Column(
            "audit_metrics",
            JSONB(),
            nullable=True,
            comment="Evaluation metrics computed from human-audited audit set labels",
        ),
    )

    # --- audit_set_items ---------------------------------------------------
    op.create_table(
        "audit_set_items",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("custom_model_id", sa.UUID(), nullable=False),
        sa.Column("embedding_id", sa.UUID(), nullable=False),
        sa.Column("recording_id", sa.UUID(), nullable=False),
        sa.Column("predicted_proba", sa.Float(), nullable=True),
        sa.Column("annotation_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["custom_model_id"],
            ["custom_models.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_id"],
            ["embeddings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"],
            ["recordings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["annotation_id"],
            ["annotations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("custom_model_id", "embedding_id"),
    )
    op.create_index(
        "ix_audit_set_items_custom_model_id",
        "audit_set_items",
        ["custom_model_id"],
    )
    op.create_index(
        "ix_audit_set_items_embedding_id",
        "audit_set_items",
        ["embedding_id"],
    )
    op.create_index(
        "ix_audit_set_items_annotation_id",
        "audit_set_items",
        ["annotation_id"],
    )
