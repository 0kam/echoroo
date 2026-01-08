"""Remove assigned_tag_id from search_result (use multi-label instead).

Revision ID: c026
Revises: c025
Create Date: 2026-01-06

This migration removes the deprecated assigned_tag_id column from search_result.
Multi-label support is now handled exclusively through the search_result_tag table.

All existing data was migrated to search_result_tag in migration c020.

This is a BREAKING change:
- API endpoints using assigned_tag_id filter will need updates
- Clients must use assigned_tag_ids instead
"""

from typing import Sequence

from alembic import op

revision: str = "c026"
down_revision: str | None = "c025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove assigned_tag_id column."""
    # Drop foreign key constraint first
    op.drop_constraint("search_result_assigned_tag_id_fkey", "search_result", type_="foreignkey")

    # Drop the column
    op.drop_column("search_result", "assigned_tag_id")


def downgrade() -> None:
    """Restore assigned_tag_id column."""
    # Add column back
    op.execute("""
        ALTER TABLE search_result
        ADD COLUMN assigned_tag_id INTEGER
    """)

    # Add foreign key constraint
    op.create_foreign_key(
        "search_result_assigned_tag_id_fkey",
        "search_result",
        "tag",
        ["assigned_tag_id"],
        ["id"],
        ondelete="SET NULL"
    )

    # Migrate data back from search_result_tag (use first tag only)
    op.execute("""
        UPDATE search_result sr
        SET assigned_tag_id = (
            SELECT tag_id
            FROM search_result_tag srt
            WHERE srt.search_result_id = sr.id
            ORDER BY srt.labeled_on ASC
            LIMIT 1
        )
    """)
