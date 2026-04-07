"""Taxa system: add global taxon taxonomy tables.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-05 00:00:00.000000

This migration adds the taxa system tables:
- taxa: Global taxon records linked to GBIF taxonomy
- taxon_vernacular_names: Multilingual common names for taxa
- tags.taxon_id: FK linking project tags to global taxon records

Also performs a data migration to populate taxa from existing species tags.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create taxa tables and link existing species tags."""

    # ------------------------------------------------------------------
    # Step 1: Create taxa table
    # ------------------------------------------------------------------

    op.create_table(
        "taxa",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("scientific_name", sa.String(300), nullable=False),
        sa.Column("gbif_taxon_key", sa.Integer(), nullable=True),
        sa.Column("rank", sa.String(50), nullable=True),
        sa.Column("is_non_biological", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("gbif_metadata", JSONB, nullable=True),
        sa.Column("gbif_resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("scientific_name", name="uq_taxa_scientific_name"),
    )

    op.create_index("ix_taxa_scientific_name", "taxa", ["scientific_name"])
    op.create_index("ix_taxa_is_non_biological", "taxa", ["is_non_biological"])
    op.create_index(
        "ix_taxa_gbif_taxon_key",
        "taxa",
        ["gbif_taxon_key"],
        unique=True,
        postgresql_where=sa.text("gbif_taxon_key IS NOT NULL"),
    )
    op.create_index("ix_taxa_created_at", "taxa", ["created_at"])

    # ------------------------------------------------------------------
    # Step 2: Create taxon_vernacular_names table
    # ------------------------------------------------------------------

    op.create_table(
        "taxon_vernacular_names",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "taxon_id",
            UUID(as_uuid=True),
            sa.ForeignKey("taxa.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(10), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "taxon_id", "locale", "source",
            name="uq_taxon_vernacular_locale_source",
        ),
    )

    op.create_index("ix_taxon_vernacular_names_taxon_id", "taxon_vernacular_names", ["taxon_id"])
    op.create_index("ix_taxon_vernacular_names_created_at", "taxon_vernacular_names", ["created_at"])

    # ------------------------------------------------------------------
    # Step 3: Add taxon_id column to tags table
    # ------------------------------------------------------------------

    op.add_column(
        "tags",
        sa.Column(
            "taxon_id",
            UUID(as_uuid=True),
            sa.ForeignKey("taxa.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tags_taxon_id", "tags", ["taxon_id"])

    # ------------------------------------------------------------------
    # Step 4: Data migration - link existing species tags to taxa
    # ------------------------------------------------------------------

    op.execute("""
        INSERT INTO taxa (id, scientific_name, is_non_biological, created_at, updated_at)
        SELECT DISTINCT gen_random_uuid(), t.scientific_name, false,
               now(), now()
        FROM tags t
        WHERE t.category = 'species'
          AND t.scientific_name IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM taxa tx WHERE tx.scientific_name = t.scientific_name
          )
    """)

    op.execute("""
        UPDATE tags
        SET taxon_id = tx.id
        FROM taxa tx
        WHERE tags.scientific_name = tx.scientific_name
          AND tags.category = 'species'
    """)


def downgrade() -> None:
    """Drop taxa tables and remove taxon_id from tags."""

    # Remove taxon_id from tags
    op.drop_index("ix_tags_taxon_id", table_name="tags")
    op.drop_column("tags", "taxon_id")

    # Drop taxon_vernacular_names
    op.drop_index("ix_taxon_vernacular_names_created_at", table_name="taxon_vernacular_names")
    op.drop_index("ix_taxon_vernacular_names_taxon_id", table_name="taxon_vernacular_names")
    op.drop_table("taxon_vernacular_names")

    # Drop taxa
    op.drop_index("ix_taxa_created_at", table_name="taxa")
    op.drop_index("ix_taxa_is_non_biological", table_name="taxa")
    op.drop_index("ix_taxa_gbif_taxon_key", table_name="taxa")
    op.drop_index("ix_taxa_scientific_name", table_name="taxa")
    op.drop_table("taxa")
