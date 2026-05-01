"""Add custom_models table and composite index on embeddings.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-02 00:00:00.000000

Creates the custom_models table to persist user-trained SVM classifiers
built from confirmed/rejected similarity search session results. Also adds
a composite index on embeddings(recording_id, model_name) for faster lookups.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create custommodelstatus enum, custom_models table, and embeddings composite index."""
    # Create the custommodelstatus enum type
    op.execute(
        "CREATE TYPE custommodelstatus AS ENUM "
        "('draft', 'training', 'trained', 'deployed', 'failed', 'archived')"
    )

    # Create custom_models table
    op.create_table(
        "custom_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "target_tag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model_type", sa.String(100), nullable=False, server_default="self_training_svm"),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft",
                "training",
                "trained",
                "deployed",
                "failed",
                "archived",
                name="custommodelstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("training_session_ids", postgresql.JSONB(), nullable=True),
        sa.Column("hyperparameters", postgresql.JSONB(), nullable=True),
        sa.Column("metrics", postgresql.JSONB(), nullable=True),
        sa.Column("training_stats", postgresql.JSONB(), nullable=True),
        sa.Column("model_artifact_key", sa.String(500), nullable=True),
        sa.Column("embedding_model_name", sa.String(100), nullable=False, server_default="perch"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Create indexes on custom_models
    op.create_index("ix_custom_models_project_id", "custom_models", ["project_id"])
    op.create_index("ix_custom_models_user_id", "custom_models", ["user_id"])
    op.create_index("ix_custom_models_status", "custom_models", ["status"])
    op.create_index("ix_custom_models_target_tag_id", "custom_models", ["target_tag_id"])
    op.create_index("ix_custom_models_created_at", "custom_models", ["created_at"])

    # Add composite index on embeddings for faster recording+model lookups
    op.create_index(
        "ix_embeddings_recording_model",
        "embeddings",
        ["recording_id", "model_name"],
    )


def downgrade() -> None:
    """Drop custom_models table, indexes, and custommodelstatus enum."""
    # Drop composite index on embeddings
    op.drop_index("ix_embeddings_recording_model", table_name="embeddings")

    # Drop indexes on custom_models
    op.drop_index("ix_custom_models_created_at", table_name="custom_models")
    op.drop_index("ix_custom_models_target_tag_id", table_name="custom_models")
    op.drop_index("ix_custom_models_status", table_name="custom_models")
    op.drop_index("ix_custom_models_user_id", table_name="custom_models")
    op.drop_index("ix_custom_models_project_id", table_name="custom_models")

    # Drop custom_models table
    op.drop_table("custom_models")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS custommodelstatus")
