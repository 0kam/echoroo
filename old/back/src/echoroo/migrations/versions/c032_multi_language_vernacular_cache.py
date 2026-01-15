"""Multi-language vernacular name cache.

Revision ID: c032
Revises: c031
Create Date: 2026-01-06

This migration optimizes the species_cache table to store vernacular names
for all languages in a single record, eliminating redundant GBIF API calls.

Changes:
- Add vernacular_names_json JSONB column to store all languages
- Remove locale from unique constraint (scientific_name only)
- Drop locale and vernacular_name columns (replaced by JSON storage)
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "c032"
down_revision: str | None = "c031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade to multi-language vernacular name cache."""
    # Add JSONB column for storing all vernacular names
    op.add_column(
        "species_cache",
        sa.Column("vernacular_names_json", JSONB, nullable=True),
    )

    # Drop old unique constraint (scientific_name, locale)
    op.drop_constraint(
        "uq_species_cache_name_locale",
        "species_cache",
        type_="unique",
    )

    # Drop old lookup index (scientific_name, locale)
    op.drop_index(
        "ix_species_cache_lookup",
        table_name="species_cache",
    )

    # Drop locale and vernacular_name columns (no longer needed)
    op.drop_column("species_cache", "locale")
    op.drop_column("species_cache", "vernacular_name")

    # Add new unique constraint on scientific_name only
    op.create_unique_constraint(
        "uq_species_cache_scientific_name",
        "species_cache",
        ["scientific_name"],
    )

    # Add new lookup index on scientific_name
    op.create_index(
        "ix_species_cache_scientific_name",
        "species_cache",
        ["scientific_name"],
    )


def downgrade() -> None:
    """Downgrade from multi-language cache."""
    # Drop new index and constraint
    op.drop_index("ix_species_cache_scientific_name", table_name="species_cache")
    op.drop_constraint(
        "uq_species_cache_scientific_name",
        "species_cache",
        type_="unique",
    )

    # Restore locale and vernacular_name columns
    op.add_column(
        "species_cache",
        sa.Column("locale", sa.String(10), nullable=False, server_default="ja"),
    )
    op.add_column(
        "species_cache",
        sa.Column("vernacular_name", sa.String(255), nullable=True),
    )

    # Restore old unique constraint
    op.create_unique_constraint(
        "uq_species_cache_name_locale",
        "species_cache",
        ["scientific_name", "locale"],
    )

    # Restore old index
    op.create_index(
        "ix_species_cache_lookup",
        "species_cache",
        ["scientific_name", "locale"],
    )

    # Drop JSONB column
    op.drop_column("species_cache", "vernacular_names_json")
