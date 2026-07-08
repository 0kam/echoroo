"""Drop the dead ``detections.taxon_id`` column (taxonomy WS-A PR6).

Revision ID: 0033
Revises: 0032
Create Date: 2026-07-08

``detections.taxon_id`` was a legacy ``VARCHAR(64)`` column holding a
stringified GBIF taxon key. The canonical species reference on a detection is
via ``tag_id`` -> ``tags`` (whose ``taxon_id`` is a UUID FK to ``taxa.id``), so
the string column has been dead: no router, service, Celery task, or serializer
reads or writes it at runtime (the only writer was an e2e seed fixture, removed
in this same change). The annotation-side ``taxon_id`` columns were already
retired in migration 0030; this completes the cleanup on the detection side.

Scope note: the masking-pipeline columns ``taxon_sensitivities.taxon_id`` and
``project_taxon_sensitivity_overrides.taxon_id`` are INTENTIONAL GBIF string
keys and are deliberately left untouched by this migration.

The column's composite index ``ix_detections_project_taxon`` (``project_id``,
``taxon_id``) is dropped alongside the column. ``downgrade()`` re-adds the
nullable ``VARCHAR(64)`` column and recreates the index, but does not (and
cannot) restore any previously stored values.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.drop_index("ix_detections_project_taxon", table_name="detections")
    op.drop_column("detections", "taxon_id")


def downgrade() -> None:
    # Re-add the column nullable (data is not restored) and recreate the
    # composite index that previously covered ``(project_id, taxon_id)``.
    op.add_column(
        "detections",
        sa.Column("taxon_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_detections_project_taxon",
        "detections",
        ["project_id", "taxon_id"],
    )
