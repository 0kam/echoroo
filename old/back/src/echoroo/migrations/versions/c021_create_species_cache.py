"""Create species_cache table for GBIF resolution caching.

Revision ID: c021
Revises: c020
Create Date: 2026-01-06

This migration creates a species_cache table to store GBIF species resolution
results. The cache improves performance by avoiding redundant API calls for
the same species names across multiple detection jobs.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c021"
down_revision: str | None = "c020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.create_table(
        "species_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scientific_name", sa.String(255), nullable=False),
        sa.Column("locale", sa.String(10), nullable=False, server_default="ja"),
        sa.Column("gbif_taxon_id", sa.String(64), nullable=True),
        sa.Column("canonical_name", sa.String(255), nullable=False),
        sa.Column("vernacular_name", sa.String(255), nullable=True),
        sa.Column(
            "is_non_species", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column(
            "created_on",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_on",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "scientific_name", "locale", name="uq_species_cache_name_locale"
        ),
    )

    # Create indexes for efficient lookups
    op.create_index(
        "ix_species_cache_gbif_taxon_id",
        "species_cache",
        ["gbif_taxon_id"],
    )
    op.create_index(
        "ix_species_cache_lookup",
        "species_cache",
        ["scientific_name", "locale"],
    )


def downgrade() -> None:
    """Downgrade database schema."""
    op.drop_index("ix_species_cache_lookup", table_name="species_cache")
    op.drop_index("ix_species_cache_gbif_taxon_id", table_name="species_cache")
    op.drop_table("species_cache")
