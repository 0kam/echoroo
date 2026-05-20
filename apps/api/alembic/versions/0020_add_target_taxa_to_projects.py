"""Restore target_taxa column on projects (Phase 7 oversight).

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-20

The initial schema had ``projects.target_taxa`` (VARCHAR(500), NULL) for
operator-typed comma-separated focus species. Phase 6-7 permissions
redesign dropped the column without an explicit deprecation entry; the
frontend kept the input on the project create/settings/detail surface
because operators relied on it. PR #89 (2026-05-20) then cleaned the
input off the frontend to match the missing column. This migration
brings the column back so the existing operator workflow is preserved
end-to-end.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("target_taxa", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("projects", "target_taxa")
