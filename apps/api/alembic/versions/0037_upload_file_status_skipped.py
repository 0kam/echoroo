"""Add the ``skipped`` upload-file status.

Revision ID: 0037
Revises: 0036
Create Date: 2026-09-21

A file the uploader chose to leave out of a partial import (storage migration
slice 2, decision 4 in ``docs/architecture/storage-lustre-migration.md``)
needs its own PostgreSQL enum label. This is a separate revision because
``ALTER TYPE ... ADD VALUE`` cannot share a transaction with statements using
the value.
"""

from __future__ import annotations

from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE uploadfilestatus ADD VALUE IF NOT EXISTS 'skipped'")


def downgrade() -> None:
    """No-op: PostgreSQL does not support ``ALTER TYPE ... DROP VALUE``."""

    return None
