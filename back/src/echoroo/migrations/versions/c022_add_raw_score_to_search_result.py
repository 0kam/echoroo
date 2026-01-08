"""Add raw_score column to search_result table.

Revision ID: c022
Revises: c021
Create Date: 2026-01-06

This migration adds a raw_score column to store the original distance/similarity
value before normalization. This allows displaying both percentile rank and
the actual raw value (cosine similarity or euclidean distance) in the UI.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c022"
down_revision: str | None = "c021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.add_column(
        "search_result",
        sa.Column("raw_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_column("search_result", "raw_score")
