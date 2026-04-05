"""Add custom_svm to detectionsource enum.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-02 00:00:00.000000

Adds 'custom_svm' as a new value to the detectionsource PostgreSQL enum type
so that annotations created by the custom SVM inference pipeline can be
distinguished from BirdNET/Perch ML detections and human annotations.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add 'custom_svm' value to the detectionsource enum."""
    op.execute("ALTER TYPE detectionsource ADD VALUE IF NOT EXISTS 'custom_svm'")


def downgrade() -> None:
    """Remove 'custom_svm' from detectionsource enum.

    PostgreSQL does not support removing enum values directly.
    A full enum recreation is required for a true downgrade.
    This downgrade is intentionally left as a no-op: the extra enum value
    causes no harm and removing it would require a table rewrite.
    """
