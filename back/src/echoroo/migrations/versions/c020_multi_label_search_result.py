"""Add search_result_tag table for multi-label classification support.

Revision ID: c020
Revises: c019
Create Date: 2025-01-05

This migration adds a search_result_tag junction table to support
assigning multiple tags to a single search result (multi-label classification).
The existing assigned_tag_id column is kept for backward compatibility.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c020"
down_revision: str | None = "c019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create search_result_tag junction table
    op.create_table(
        "search_result_tag",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "search_result_id",
            sa.Integer(),
            sa.ForeignKey("search_result.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            sa.Integer(),
            sa.ForeignKey("tag.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_on",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "search_result_id", "tag_id", name="uq_search_result_tag"
        ),
    )

    # Create indexes for efficient querying
    op.create_index(
        "ix_search_result_tag_search_result_id",
        "search_result_tag",
        ["search_result_id"],
    )
    op.create_index(
        "ix_search_result_tag_tag_id",
        "search_result_tag",
        ["tag_id"],
    )

    # Migrate existing data: copy assigned_tag_id to search_result_tag
    # This is done using raw SQL for efficiency
    op.execute(
        """
        INSERT INTO search_result_tag (search_result_id, tag_id, created_on)
        SELECT id, assigned_tag_id, COALESCE(labeled_on, NOW())
        FROM search_result
        WHERE assigned_tag_id IS NOT NULL
        """
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Note: This will lose multi-label data, keeping only first tag
    # For safety, we don't try to reverse the data migration

    # Drop indexes
    op.drop_index("ix_search_result_tag_tag_id", table_name="search_result_tag")
    op.drop_index(
        "ix_search_result_tag_search_result_id", table_name="search_result_tag"
    )

    # Drop the junction table
    op.drop_table("search_result_tag")
