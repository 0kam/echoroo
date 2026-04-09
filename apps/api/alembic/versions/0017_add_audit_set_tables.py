"""Add audit_set_items table and audit_metrics column to custom_models.

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-09 00:00:00.000000

Extends the model training pipeline with audit set support:
- audit_set_items: score-stratified embeddings selected for human audit
- custom_models.audit_metrics: JSONB column storing evaluation results
  computed from the audited labels (accuracy, precision, recall, f1, etc.)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# Revision identifiers used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create audit_set_items table and add audit_metrics to custom_models."""

    # --- custom_models: add audit_metrics column ---------------------------
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
        "ix_audit_model",
        "audit_set_items",
        ["custom_model_id"],
    )


def downgrade() -> None:
    """Reverse all changes introduced in this migration."""
    op.drop_index("ix_audit_model", table_name="audit_set_items")
    op.drop_table("audit_set_items")
    op.drop_column("custom_models", "audit_metrics")
