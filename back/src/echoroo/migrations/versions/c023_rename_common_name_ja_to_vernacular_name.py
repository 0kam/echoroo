"""Rename common_name_ja to vernacular_name in foundation_model_run_species.

Revision ID: c023
Revises: c022
Create Date: 2026-01-06

This migration makes the vernacular name field language-agnostic:
- Rename common_name_ja → vernacular_name in foundation_model_run_species table
- The field now stores vernacular names in any locale (not just Japanese)
- Aligns with Tag.vernacular_name for consistency
"""

from typing import Sequence

from alembic import op

revision: str = "c023"
down_revision: str | None = "c022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Rename common_name_ja to vernacular_name."""
    op.alter_column(
        "foundation_model_run_species",
        "common_name_ja",
        new_column_name="vernacular_name",
    )


def downgrade() -> None:
    """Revert vernacular_name back to common_name_ja."""
    op.alter_column(
        "foundation_model_run_species",
        "vernacular_name",
        new_column_name="common_name_ja",
    )
