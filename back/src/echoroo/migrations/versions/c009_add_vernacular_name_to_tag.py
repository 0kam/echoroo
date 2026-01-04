"""Add vernacular_name column to tag.

Revision ID: c009_vernacular_name
Revises: c008_add_locale
Create Date: 2026-01-03 00:00:00.000000

This migration adds vernacular_name support to tags:
- Add vernacular_name column to tag table (nullable, for species tags)

The vernacular_name stores the common name for species tags in the
locale specified during species detection, fetched from GBIF API.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c009_vernacular_name"
down_revision: Union[str, None] = "c008_add_locale"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add vernacular_name column to tag table
    op.add_column(
        "tag",
        sa.Column(
            "vernacular_name",
            sa.String(length=255),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Remove vernacular_name column from tag table
    op.drop_column("tag", "vernacular_name")
