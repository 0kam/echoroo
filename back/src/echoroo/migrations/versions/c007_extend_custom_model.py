"""Extend custom model for standalone operation.

Revision ID: c007_extend_custom_model
Revises: c006_sound_search
Create Date: 2025-12-26 12:00:00.000000

This migration extends the custom model feature to support:
1. Standalone operation (independent of ML Project)
2. Multiple datasets for training data collection
3. Multiple training data sources (search sessions, sound searches, annotation projects)
4. Multiple datasets for inference

Changes:
- Add project_id to custom_model (for access control on standalone models)
- Make ml_project_id nullable in custom_model
- Create custom_model_dataset_scope table
- Create custom_model_training_source table
- Add project_id to inference_batch (for standalone batches)
- Make ml_project_id nullable in inference_batch
- Create inference_batch_dataset_scope table
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c007_extend_custom_model"
down_revision: Union[str, None] = "c006_sound_search"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM type for training_data_source
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'training_data_source'
            ) THEN
                CREATE TYPE training_data_source AS ENUM (
                    'search_session',
                    'sound_search',
                    'annotation_project'
                );
            END IF;
        END
        $$;
        """
    )

    # Modify custom_model table
    # Add project_id column
    op.add_column(
        "custom_model",
        sa.Column(
            "project_id",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_custom_model_project_id",
        "custom_model",
        "project",
        ["project_id"],
        ["project_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_custom_model_project_id",
        "custom_model",
        ["project_id"],
    )

    # Make ml_project_id nullable
    op.alter_column(
        "custom_model",
        "ml_project_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # Backfill project_id from ml_project for existing records
    op.execute(
        """
        UPDATE custom_model
        SET project_id = ml_project.project_id
        FROM ml_project
        WHERE custom_model.ml_project_id = ml_project.id
        AND custom_model.project_id IS NULL
        """
    )

    # Create custom_model_dataset_scope table
    op.create_table(
        "custom_model_dataset_scope",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("custom_model_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("foundation_model_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["custom_model_id"],
            ["custom_model.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["dataset.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["foundation_model_run_id"],
            ["foundation_model_run.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "custom_model_id",
            "dataset_id",
            name="uq_custom_model_dataset_scope_model_dataset",
        ),
    )
    op.create_index(
        "ix_custom_model_dataset_scope_model_id",
        "custom_model_dataset_scope",
        ["custom_model_id"],
    )

    # Create custom_model_training_source table
    op.create_table(
        "custom_model_training_source",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("custom_model_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM(
                "search_session",
                "sound_search",
                "annotation_project",
                name="training_data_source",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("source_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_positive",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("tag_uuid", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "sample_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["custom_model_id"],
            ["custom_model.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "custom_model_id",
            "source_type",
            "source_uuid",
            name="uq_custom_model_training_source_model_type_uuid",
        ),
    )
    op.create_index(
        "ix_custom_model_training_source_model_id",
        "custom_model_training_source",
        ["custom_model_id"],
    )

    # Modify inference_batch table
    # Add project_id column
    op.add_column(
        "inference_batch",
        sa.Column(
            "project_id",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_inference_batch_project_id",
        "inference_batch",
        "project",
        ["project_id"],
        ["project_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_inference_batch_project_id",
        "inference_batch",
        ["project_id"],
    )

    # Make ml_project_id nullable
    op.alter_column(
        "inference_batch",
        "ml_project_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # Backfill project_id from ml_project for existing records
    op.execute(
        """
        UPDATE inference_batch
        SET project_id = ml_project.project_id
        FROM ml_project
        WHERE inference_batch.ml_project_id = ml_project.id
        AND inference_batch.project_id IS NULL
        """
    )

    # Create inference_batch_dataset_scope table
    op.create_table(
        "inference_batch_dataset_scope",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("inference_batch_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("foundation_model_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "clips_processed",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "positive_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["inference_batch_id"],
            ["inference_batch.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["dataset.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["foundation_model_run_id"],
            ["foundation_model_run.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "inference_batch_id",
            "dataset_id",
            name="uq_inference_batch_dataset_scope_batch_dataset",
        ),
    )
    op.create_index(
        "ix_inference_batch_dataset_scope_batch_id",
        "inference_batch_dataset_scope",
        ["inference_batch_id"],
    )


def downgrade() -> None:
    # Drop inference_batch_dataset_scope table
    op.drop_index(
        "ix_inference_batch_dataset_scope_batch_id",
        table_name="inference_batch_dataset_scope",
    )
    op.drop_table("inference_batch_dataset_scope")

    # Revert inference_batch changes
    op.drop_index(
        "ix_inference_batch_project_id",
        table_name="inference_batch",
    )
    op.drop_constraint(
        "fk_inference_batch_project_id",
        "inference_batch",
        type_="foreignkey",
    )
    op.drop_column("inference_batch", "project_id")
    op.alter_column(
        "inference_batch",
        "ml_project_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Drop custom_model_training_source table
    op.drop_index(
        "ix_custom_model_training_source_model_id",
        table_name="custom_model_training_source",
    )
    op.drop_table("custom_model_training_source")

    # Drop custom_model_dataset_scope table
    op.drop_index(
        "ix_custom_model_dataset_scope_model_id",
        table_name="custom_model_dataset_scope",
    )
    op.drop_table("custom_model_dataset_scope")

    # Revert custom_model changes
    op.drop_index(
        "ix_custom_model_project_id",
        table_name="custom_model",
    )
    op.drop_constraint(
        "fk_custom_model_project_id",
        "custom_model",
        type_="foreignkey",
    )
    op.drop_column("custom_model", "project_id")
    op.alter_column(
        "custom_model",
        "ml_project_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # Drop ENUM type
    op.execute("DROP TYPE IF EXISTS training_data_source CASCADE")
