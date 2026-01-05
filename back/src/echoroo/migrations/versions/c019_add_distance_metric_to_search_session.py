"""Add distance_metric to search_session table.

Revision ID: c019
Revises: c018
Create Date: 2025-01-05

This migration adds a distance_metric column to the search_session table
to support both cosine and euclidean distance metrics for similarity search.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c019"
down_revision: str | None = "c018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Add distance_metric column with default 'cosine'
    op.add_column(
        "search_session",
        sa.Column(
            "distance_metric",
            sa.String(),
            nullable=False,
            server_default="cosine",
        ),
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Remove distance_metric column
    op.drop_column("search_session", "distance_metric")
