"""Add Catalogue of Life XR identity columns to taxa.

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-23

WS-A v2 slice 3. GBIF's legacy backbone is frozen, so a taxon's re-matchable
external identity moves to the **Catalogue of Life XR** checklist (served via
``GET https://api.gbif.org/v2/species/match?checklistKey=xcol``). This migration
adds the NULLABLE columns that hold one COL XR resolution per taxon, plus the
release the resolution was pinned to, so a later re-resolution against a newer
COL release is a pure data refresh — the local ``taxa.id`` UUID stays the
immutable identity and no existing column is renamed or dropped.

For birds the bundled AviList crosswalk remains the *name* authority; COL XR is
cross-domain *identity* only.

Columns added:
1.  ``col_xr_id VARCHAR(16)`` — COL XR usage key of the matched name (the name
    as we store it, which may be a synonym). NULL when the match was rejected.
2.  ``col_xr_accepted_id VARCHAR(16)`` — COL XR usage key of the ACCEPTED name
    (equals ``col_xr_id`` when the match is not a synonym).
3.  ``col_xr_accepted_rank VARCHAR(20)`` — rank of the accepted usage. COL
    lumps sometimes make this ``SUBSPECIES`` even for a species-rank query.
4.  ``col_xr_status VARCHAR(32)`` — COL usage status (ACCEPTED / SYNONYM / ...).
5.  ``col_xr_match_type VARCHAR(20)`` — EXACT / VARIANT / FUZZY / HIGHERRANK /
    NONE. Recorded for *every* processed taxon, including rejects.
6.  ``col_xr_match_confidence SMALLINT`` — 0..100 confidence. Meaningless for
    ``NONE`` (the API reports 100), so it is only stored for real matches.
7.  ``col_xr_release VARCHAR(32)`` — COL release alias pinned at match time
    (e.g. ``COL26.6 XR``).
8.  ``col_xr_clb_dataset_key INTEGER`` — the checklistbank dataset key of that
    release, read once per batch run.
9.  ``col_xr_resolved_at TIMESTAMPTZ`` — when the resolution ran. Stamped on
    every processed row (accept, review AND reject) so a batch never reprocesses
    the same taxon.
10. ``authorship VARCHAR(200)`` — authorship of the matched name.
11. ``accepted_authorship VARCHAR(200)`` — authorship of the accepted name.
12. ``col_xr_classification JSONB`` — ``{rank: {key, name}}`` for the accepted
    lineage, filtered to the seven principal ranks.

The accepted *canonical name* reuses the existing ``accepted_scientific_name``
column (added by 0027 and never written until now).

Two NON-unique indexes support "everything that resolved to this COL usage"
lookups. They are deliberately non-unique: several BirdNET labels legitimately
collapse onto the same COL usage (taxonomic lumps).

Fully reversible: ``downgrade()`` drops the indexes and the twelve columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

TABLE = "taxa"

#: ``(name, type)`` in creation order. ``downgrade()`` drops them in reverse.
_COLUMNS: tuple[tuple[str, sa.types.TypeEngine[object]], ...] = (
    ("col_xr_id", sa.String(length=16)),
    ("col_xr_accepted_id", sa.String(length=16)),
    ("col_xr_accepted_rank", sa.String(length=20)),
    ("col_xr_status", sa.String(length=32)),
    ("col_xr_match_type", sa.String(length=20)),
    ("col_xr_match_confidence", sa.SmallInteger()),
    ("col_xr_release", sa.String(length=32)),
    ("col_xr_clb_dataset_key", sa.Integer()),
    ("col_xr_resolved_at", sa.DateTime(timezone=True)),
    ("authorship", sa.String(length=200)),
    ("accepted_authorship", sa.String(length=200)),
    ("col_xr_classification", postgresql.JSONB(astext_type=sa.Text())),
)

_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_taxa_col_xr_id", "col_xr_id"),
    ("ix_taxa_col_xr_accepted_id", "col_xr_accepted_id"),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column(TABLE, sa.Column(name, type_, nullable=True))

    for index_name, column_name in _INDEXES:
        # Non-unique on purpose: taxonomic lumps map several taxa onto one
        # COL XR usage key.
        op.create_index(index_name, TABLE, [column_name], unique=False)


def downgrade() -> None:
    for index_name, _ in reversed(_INDEXES):
        op.drop_index(index_name, table_name=TABLE)

    for name, _ in reversed(_COLUMNS):
        op.drop_column(TABLE, name)
