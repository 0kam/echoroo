"""Fix species_cache created_on and updated_on default values.

Revision ID: c031
Revises: c030
Create Date: 2026-01-06

This migration adds missing server default values for created_on and updated_on
columns in the species_cache table. The original migration c021 specified these
defaults but they were not applied correctly to the database schema.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c031"
down_revision: str | None = "c030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add default values to created_on and updated_on columns."""
    # Add server default for created_on
    op.alter_column(
        "species_cache",
        "created_on",
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    # Add server default for updated_on
    op.alter_column(
        "species_cache",
        "updated_on",
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def downgrade() -> None:
    """Remove default values from created_on and updated_on columns."""
    op.alter_column(
        "species_cache",
        "created_on",
        server_default=None,
    )

    op.alter_column(
        "species_cache",
        "updated_on",
        server_default=None,
    )
