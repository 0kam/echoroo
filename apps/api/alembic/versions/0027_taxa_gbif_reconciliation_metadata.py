"""Add GBIF-backbone reconciliation metadata columns to taxa.

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-11

Adds six NULLABLE metadata columns to ``taxa`` so a taxon's GBIF match can be
re-reconciled against a newer backbone version without disturbing the local
UUID identity. The columns are additive only: no existing column is renamed or
dropped, and the new columns are not exposed by any API yet (later PRs populate
and surface them).

Columns added:
1. ``gbif_accepted_usage_key INTEGER`` — GBIF accepted usageKey when this taxon
   is a synonym.
2. ``gbif_match_type VARCHAR(20)`` — GBIF /species/match matchType
   (EXACT/FUZZY/HIGHERRANK/NONE).
3. ``gbif_match_confidence DOUBLE PRECISION`` — match confidence (0..100).
4. ``gbif_backbone_version VARCHAR(20)`` — GBIF/COL backbone version pinned at
   match time.
5. ``verbatim_scientific_name VARCHAR(300)`` — original name as supplied
   (BirdNET/user) before normalization.
6. ``accepted_scientific_name VARCHAR(300)`` — GBIF canonical/accepted name.

Fully reversible: ``downgrade()`` drops the six columns in reverse order.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "taxa",
        sa.Column("gbif_accepted_usage_key", sa.Integer(), nullable=True),
    )
    op.add_column(
        "taxa",
        sa.Column("gbif_match_type", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "taxa",
        sa.Column("gbif_match_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "taxa",
        sa.Column("gbif_backbone_version", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "taxa",
        sa.Column("verbatim_scientific_name", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "taxa",
        sa.Column("accepted_scientific_name", sa.String(length=300), nullable=True),
    )


def downgrade() -> None:
    # Reverse order of upgrade().
    op.drop_column("taxa", "accepted_scientific_name")
    op.drop_column("taxa", "verbatim_scientific_name")
    op.drop_column("taxa", "gbif_backbone_version")
    op.drop_column("taxa", "gbif_match_confidence")
    op.drop_column("taxa", "gbif_match_type")
    op.drop_column("taxa", "gbif_accepted_usage_key")
