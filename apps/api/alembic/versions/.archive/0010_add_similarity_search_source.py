"""Add similarity_search to detectionsource enum.

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-10 00:00:00.000000

Adds 'similarity_search' as a new value to the detectionsource PostgreSQL enum
type so that annotations created via the vector similarity search feature can be
distinguished from BirdNET/Perch ML detections and human annotations.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add 'similarity_search' value to the detectionsource enum."""
    op.execute("ALTER TYPE detectionsource ADD VALUE IF NOT EXISTS 'similarity_search'")


def downgrade() -> None:
    """Remove 'similarity_search' from detectionsource enum.

    PostgreSQL does not support removing enum values directly.
    A full enum recreation is required for a true downgrade.
    This downgrade is intentionally left as a no-op: the extra enum value
    causes no harm and removing it would require a table rewrite.
    """
