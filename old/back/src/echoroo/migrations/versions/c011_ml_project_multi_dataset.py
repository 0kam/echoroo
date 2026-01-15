"""Add multi-dataset support to ML Projects.

Revision ID: c011_mlp_multi_ds
Revises: c010_add_source
Create Date: 2026-01-03 00:00:00.000000

This migration adds support for multiple datasets in ML Projects:
- Creates ml_project_dataset_scope table for linking datasets with embedding runs
- Adds foundation_model_id to ml_project for specifying the embedding model
- Makes ml_project.dataset_id nullable (existing data preserved)
- Migrates existing dataset_id values to dataset_scopes as primary datasets

The dataset_scopes relationship allows ML projects to work across multiple
datasets, each with its own foundation model run providing embeddings.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c011_mlp_multi_ds"
down_revision: Union[str, None] = "c010_add_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ml_project_dataset_scope table
    op.create_table(
        "ml_project_dataset_scope",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("ml_project_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("foundation_model_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["ml_project_id"],
            ["ml_project.id"],
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
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "ml_project_id",
            "dataset_id",
            name="uq_ml_project_dataset_scope_project_dataset",
        ),
    )
    op.create_index(
        "ix_ml_project_dataset_scope_ml_project_id",
        "ml_project_dataset_scope",
        ["ml_project_id"],
    )

    # 2. Add foundation_model_id column to ml_project
    op.add_column(
        "ml_project",
        sa.Column(
            "foundation_model_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_ml_project_foundation_model_id",
        "ml_project",
        "foundation_model",
        ["foundation_model_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 3. Make dataset_id nullable
    op.alter_column(
        "ml_project",
        "dataset_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # 4. Migrate existing dataset_id to dataset_scopes
    # For each ml_project with a dataset_id, create a dataset_scope entry
    # We need to find a foundation_model_run for the dataset
    op.execute(
        """
        INSERT INTO ml_project_dataset_scope (uuid, ml_project_id, dataset_id, foundation_model_run_id, is_primary, created_on)
        SELECT
            gen_random_uuid(),
            mp.id,
            mp.dataset_id,
            (
                SELECT fmr.id
                FROM foundation_model_run fmr
                WHERE fmr.dataset_id = mp.dataset_id
                ORDER BY fmr.created_on DESC
                LIMIT 1
            ),
            true,
            NOW()
        FROM ml_project mp
        WHERE mp.dataset_id IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM foundation_model_run fmr
            WHERE fmr.dataset_id = mp.dataset_id
        )
        """
    )

    # 5. Set foundation_model_id on ml_project based on the migrated run's model
    op.execute(
        """
        UPDATE ml_project mp
        SET foundation_model_id = (
            SELECT fmr.foundation_model_id
            FROM ml_project_dataset_scope mpds
            JOIN foundation_model_run fmr ON mpds.foundation_model_run_id = fmr.id
            WHERE mpds.ml_project_id = mp.id
            AND mpds.is_primary = true
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1 FROM ml_project_dataset_scope mpds
            WHERE mpds.ml_project_id = mp.id
            AND mpds.is_primary = true
        )
        """
    )


def downgrade() -> None:
    # 1. Drop foreign key and column for foundation_model_id
    op.drop_constraint(
        "fk_ml_project_foundation_model_id",
        "ml_project",
        type_="foreignkey",
    )
    op.drop_column("ml_project", "foundation_model_id")

    # 2. Make dataset_id non-nullable again
    # First, ensure all rows have a dataset_id from their primary scope
    op.execute(
        """
        UPDATE ml_project mp
        SET dataset_id = (
            SELECT mpds.dataset_id
            FROM ml_project_dataset_scope mpds
            WHERE mpds.ml_project_id = mp.id
            AND mpds.is_primary = true
            LIMIT 1
        )
        WHERE mp.dataset_id IS NULL
        AND EXISTS (
            SELECT 1 FROM ml_project_dataset_scope mpds
            WHERE mpds.ml_project_id = mp.id
            AND mpds.is_primary = true
        )
        """
    )

    # For any remaining NULL dataset_ids, pick the first dataset from scopes
    op.execute(
        """
        UPDATE ml_project mp
        SET dataset_id = (
            SELECT mpds.dataset_id
            FROM ml_project_dataset_scope mpds
            WHERE mpds.ml_project_id = mp.id
            ORDER BY mpds.created_on
            LIMIT 1
        )
        WHERE mp.dataset_id IS NULL
        AND EXISTS (
            SELECT 1 FROM ml_project_dataset_scope mpds
            WHERE mpds.ml_project_id = mp.id
        )
        """
    )

    # Delete any ml_projects that still have NULL dataset_id
    op.execute(
        """
        DELETE FROM ml_project
        WHERE dataset_id IS NULL
        """
    )

    # Now make the column non-nullable
    op.alter_column(
        "ml_project",
        "dataset_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    # 3. Drop the ml_project_dataset_scope table
    op.drop_index(
        "ix_ml_project_dataset_scope_ml_project_id",
        table_name="ml_project_dataset_scope",
    )
    op.drop_table("ml_project_dataset_scope")
