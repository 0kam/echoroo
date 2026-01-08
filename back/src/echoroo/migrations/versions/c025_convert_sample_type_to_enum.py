"""Convert sample_type to ENUM type.

Revision ID: c025
Revises: c024
Create Date: 2026-01-06

This migration converts the sample_type column from VARCHAR to PostgreSQL ENUM.
Sample types represent how search results were selected for labeling:
- easy_positive: Top-k most similar clips
- boundary: Random samples from medium similarity range
- others: Diverse samples using farthest-first selection
- active_learning: Samples selected by the active learning iteration

This is a safe, non-breaking change that improves type safety.
"""

from typing import Sequence

from alembic import op

revision: str = "c025"
down_revision: str | None = "c024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Convert sample_type to ENUM."""
    # Create the ENUM type
    op.execute("""
        CREATE TYPE sample_type AS ENUM (
            'easy_positive',
            'boundary',
            'others',
            'active_learning'
        )
    """)

    # Convert the column to use the ENUM type
    op.execute("""
        ALTER TABLE search_result
        ALTER COLUMN sample_type
        TYPE sample_type
        USING sample_type::sample_type
    """)


def downgrade() -> None:
    """Revert sample_type to VARCHAR."""
    # Convert back to VARCHAR
    op.execute("""
        ALTER TABLE search_result
        ALTER COLUMN sample_type
        TYPE VARCHAR(50)
        USING sample_type::TEXT
    """)

    # Drop the ENUM type
    op.execute("DROP TYPE sample_type")
