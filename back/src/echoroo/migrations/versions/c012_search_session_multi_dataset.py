"""Add multi-dataset support to SearchSession and Annotation Project export.

Revision ID: c012_ss_multi_ds
Revises: c011_mlp_multi_ds
Create Date: 2026-01-03 12:00:00.000000

This migration adds:
1. search_session_dataset_scope table for tracking per-dataset search progress
2. search_session.search_all_scopes column for controlling search scope
3. search_result.saved_to_annotation_project_id for tracking exports
4. New enum values for search_result_label: positive_reference, negative_reference
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c012_ss_multi_ds"
down_revision: Union[str, None] = "c011_mlp_multi_ds"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add new enum values to search_result_label
    # First, we need to alter the enum type to add new values
    op.execute(
        """
        ALTER TYPE search_result_label ADD VALUE IF NOT EXISTS 'positive_reference';
        """
    )
    op.execute(
        """
        ALTER TYPE search_result_label ADD VALUE IF NOT EXISTS 'negative_reference';
        """
    )

    # 2. Add search_all_scopes column to search_session
    op.add_column(
        "search_session",
        sa.Column(
            "search_all_scopes",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # 3. Create search_session_dataset_scope table
    op.create_table(
        "search_session_dataset_scope",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_session_id", sa.Integer(), nullable=False),
        sa.Column("ml_project_dataset_scope_id", sa.Integer(), nullable=False),
        sa.Column(
            "clips_searched",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "results_found",
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
            ["search_session_id"],
            ["search_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ml_project_dataset_scope_id"],
            ["ml_project_dataset_scope.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "ml_project_dataset_scope_id",
            name="uq_search_session_dataset_scope",
        ),
    )
    op.create_index(
        "ix_search_session_dataset_scope_session_id",
        "search_session_dataset_scope",
        ["search_session_id"],
    )

    # 4. Add saved_to_annotation_project_id column to search_result
    op.add_column(
        "search_result",
        sa.Column(
            "saved_to_annotation_project_id",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_search_result_annotation_project",
        "search_result",
        "annotation_project",
        ["saved_to_annotation_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_search_result_saved_to_annotation_project_id",
        "search_result",
        ["saved_to_annotation_project_id"],
    )


def downgrade() -> None:
    # 1. Drop index and foreign key for saved_to_annotation_project_id
    op.drop_index(
        "ix_search_result_saved_to_annotation_project_id",
        table_name="search_result",
    )
    op.drop_constraint(
        "fk_search_result_annotation_project",
        "search_result",
        type_="foreignkey",
    )
    op.drop_column("search_result", "saved_to_annotation_project_id")

    # 2. Drop search_session_dataset_scope table
    op.drop_index(
        "ix_search_session_dataset_scope_session_id",
        table_name="search_session_dataset_scope",
    )
    op.drop_table("search_session_dataset_scope")

    # 3. Drop search_all_scopes column from search_session
    op.drop_column("search_session", "search_all_scopes")

    # Note: PostgreSQL does not support removing enum values easily.
    # The positive_reference and negative_reference values will remain
    # in the search_result_label enum type. They will simply not be used.
    # A full recreation of the enum would require migrating all data,
    # which is risky for a downgrade operation.
