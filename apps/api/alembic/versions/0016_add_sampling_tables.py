"""Add sampling_rounds and sampling_round_items tables for model training pipeline.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-09 00:00:00.000000

Adds sampling pipeline tables to support the model training overhaul:
- sampling_rounds: tracks each round of sample selection tied to a custom model
- sampling_round_items: individual embeddings selected within a round
Also extends custom_models with training_config and removes the deprecated
training_session_ids column, and enforces NOT NULL on target_tag_id.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create sampling tables and update custom_models schema."""

    # --- sampling_rounds ---------------------------------------------------
    op.create_table(
        "sampling_rounds",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("custom_model_id", sa.UUID(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("round_type", sa.String(20), nullable=False),
        sa.Column("sampling_config", sa.JSON(), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("job_id", sa.String(255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
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
        sa.UniqueConstraint("custom_model_id", "round_number"),
        sa.CheckConstraint(
            "round_type IN ('seed', 'active_learning')",
            name="ck_sampling_rounds_round_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_sampling_rounds_status",
        ),
    )
    op.create_index(
        "ix_sampling_rounds_model",
        "sampling_rounds",
        ["custom_model_id"],
    )

    # --- sampling_round_items ----------------------------------------------
    op.create_table(
        "sampling_round_items",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("sampling_round_id", sa.UUID(), nullable=False),
        sa.Column("embedding_id", sa.UUID(), nullable=False),
        sa.Column("sample_type", sa.String(20), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("decision_distance", sa.Float(), nullable=True),
        sa.Column("annotation_id", sa.UUID(), nullable=False),
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
            ["sampling_round_id"],
            ["sampling_rounds.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["embedding_id"],
            ["embeddings.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["annotation_id"],
            ["annotations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("sampling_round_id", "embedding_id"),
        sa.CheckConstraint(
            "sample_type IN ('easy_positive', 'boundary', 'others', 'active_learning')",
            name="ck_sampling_round_items_sample_type",
        ),
    )
    op.create_index(
        "ix_sri_round",
        "sampling_round_items",
        ["sampling_round_id"],
    )
    op.create_index(
        "ix_sri_annotation",
        "sampling_round_items",
        ["annotation_id"],
    )

    # --- custom_models: add training_config --------------------------------
    op.add_column(
        "custom_models",
        sa.Column(
            "training_config",
            sa.JSON(),
            nullable=True,
            comment="Training hyperparameters and configuration for this model",
        ),
    )

    # --- custom_models: make target_tag_id NOT NULL ------------------------
    # Delete any rows whose target_tag_id is NULL — they have no target species
    # and cannot be used for training or inference, so they are not recoverable.
    op.execute("DELETE FROM custom_models WHERE target_tag_id IS NULL")
    op.alter_column("custom_models", "target_tag_id", nullable=False)

    # --- custom_models: fix target_tag_id FK to RESTRICT (was SET NULL) ----
    # The column is now NOT NULL so SET NULL would be contradictory: deleting a
    # Tag that still has dependent CustomModels must be blocked instead.
    op.drop_constraint(
        "custom_models_target_tag_id_fkey",
        "custom_models",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "custom_models_target_tag_id_fkey",
        "custom_models",
        "tags",
        ["target_tag_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # --- custom_models: drop deprecated training_session_ids ---------------
    op.drop_column("custom_models", "training_session_ids")

    # --- detectionsource enum: add sampling_round and audit_set values -----
    op.execute("ALTER TYPE detectionsource ADD VALUE IF NOT EXISTS 'sampling_round'")
    op.execute("ALTER TYPE detectionsource ADD VALUE IF NOT EXISTS 'audit_set'")


def downgrade() -> None:
    """Reverse all changes introduced in this migration."""

    # Restore training_session_ids column
    op.add_column(
        "custom_models",
        sa.Column(
            "training_session_ids",
            sa.JSON(),
            nullable=True,
            comment="Legacy list of training session IDs",
        ),
    )

    # Restore target_tag_id FK to SET NULL (original definition in 0012)
    op.drop_constraint(
        "custom_models_target_tag_id_fkey",
        "custom_models",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "custom_models_target_tag_id_fkey",
        "custom_models",
        "tags",
        ["target_tag_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Make target_tag_id nullable again
    op.alter_column("custom_models", "target_tag_id", nullable=True)

    # Remove training_config column
    op.drop_column("custom_models", "training_config")

    # Drop indexes and tables in dependency order
    op.drop_index("ix_sri_annotation", table_name="sampling_round_items")
    op.drop_index("ix_sri_round", table_name="sampling_round_items")
    op.drop_table("sampling_round_items")

    op.drop_index("ix_sampling_rounds_model", table_name="sampling_rounds")
    op.drop_table("sampling_rounds")
