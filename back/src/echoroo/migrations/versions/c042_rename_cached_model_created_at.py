"""Rename created_at to created_on in cached_model table.

Revision ID: c042
Revises: c041
Create Date: 2026-01-11 00:00:00.000000

This migration renames the created_at column to created_on to match
the Base class convention used by all other models.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c042"
down_revision: Union[str, None] = "c041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename created_at to created_on in cached_model table."""
    # Drop the old index
    op.drop_index("ix_cached_model_created_at", table_name="cached_model")

    # Rename the column
    op.alter_column(
        "cached_model",
        "created_at",
        new_column_name="created_on",
    )

    # Create new index with the correct name
    op.create_index(
        "ix_cached_model_created_on",
        "cached_model",
        ["created_on"],
    )


def downgrade() -> None:
    """Rename created_on back to created_at in cached_model table."""
    # Drop the new index
    op.drop_index("ix_cached_model_created_on", table_name="cached_model")

    # Rename the column back
    op.alter_column(
        "cached_model",
        "created_on",
        new_column_name="created_at",
    )

    # Create old index
    op.create_index(
        "ix_cached_model_created_at",
        "cached_model",
        ["created_at"],
    )
