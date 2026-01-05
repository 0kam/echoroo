"""Add iteration_score_distribution table.

Revision ID: c017
Revises: c016
Create Date: 2026-01-05

This migration adds the iteration_score_distribution table to store
score distributions computed during each active learning iteration.
This enables visualization of model confidence and progress tracking.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c017"
down_revision: Union[str, None] = "c016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create iteration_score_distribution table."""
    op.create_table(
        "iteration_score_distribution",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "search_session_id",
            sa.Integer(),
            sa.ForeignKey("search_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tag.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("bin_counts", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("bin_edges", postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column("positive_count", sa.Integer(), nullable=False),
        sa.Column("negative_count", sa.Integer(), nullable=False),
        sa.Column("mean_score", sa.Float(), nullable=False),
        sa.Column(
            "created_on",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Create indexes for common queries
    op.create_index(
        "ix_iteration_score_distribution_search_session_id",
        "iteration_score_distribution",
        ["search_session_id"],
    )
    op.create_index(
        "ix_iteration_score_distribution_tag_id",
        "iteration_score_distribution",
        ["tag_id"],
    )
    op.create_index(
        "ix_iteration_score_distribution_session_tag_iteration",
        "iteration_score_distribution",
        ["search_session_id", "tag_id", "iteration"],
        unique=True,
    )


def downgrade() -> None:
    """Drop iteration_score_distribution table."""
    op.drop_index(
        "ix_iteration_score_distribution_session_tag_iteration",
        table_name="iteration_score_distribution",
    )
    op.drop_index(
        "ix_iteration_score_distribution_tag_id",
        table_name="iteration_score_distribution",
    )
    op.drop_index(
        "ix_iteration_score_distribution_search_session_id",
        table_name="iteration_score_distribution",
    )
    op.drop_table("iteration_score_distribution")
