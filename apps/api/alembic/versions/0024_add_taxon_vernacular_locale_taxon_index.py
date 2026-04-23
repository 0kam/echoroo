"""Add composite ``(locale, taxon_id)`` index on ``taxon_vernacular_names``.

Revision ID: 0024
Revises: 0023
Create Date: 2026-04-23 00:00:00.000000

The Detection and Tag APIs resolve vernacular names via a batched query of
the form::

    SELECT ... FROM taxon_vernacular_names
    WHERE locale = :locale AND taxon_id IN (...)

A single-column ``ix_taxon_vernacular_names_taxon_id`` already exists, but
PostgreSQL can use the composite index to satisfy the locale equality and
the taxon_id membership check in one access path, which is meaningfully
faster once the table grows (typical species vocabularies are ~10k rows
per locale). Leading with ``locale`` also keeps the index small and useful
for the ``WHERE locale = :locale`` prefix that every batch resolution uses.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the composite (locale, taxon_id) index."""
    op.create_index(
        "ix_taxon_vernacular_names_locale_taxon_id",
        "taxon_vernacular_names",
        ["locale", "taxon_id"],
    )


def downgrade() -> None:
    """Drop the composite (locale, taxon_id) index."""
    op.drop_index(
        "ix_taxon_vernacular_names_locale_taxon_id",
        table_name="taxon_vernacular_names",
    )
