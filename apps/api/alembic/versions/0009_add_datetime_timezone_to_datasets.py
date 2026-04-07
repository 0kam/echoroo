"""Add datetime_timezone column to datasets table.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-09 00:00:00.000000

Adds an IANA timezone field to the datasets table so that naive datetimes
extracted from recording filenames can be interpreted correctly before storage.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Add datetime_timezone column to datasets."""
    op.add_column(
        "datasets",
        sa.Column(
            "datetime_timezone",
            sa.String(50),
            nullable=True,
            comment="IANA timezone for datetime parsing (e.g., 'Asia/Tokyo', 'UTC')",
        ),
    )


def downgrade() -> None:
    """Remove datetime_timezone column from datasets."""
    op.drop_column("datasets", "datetime_timezone")
