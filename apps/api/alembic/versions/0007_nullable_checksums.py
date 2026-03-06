"""Make checksum columns nullable for HTTP environments without crypto.subtle.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-05 00:00:00.000000

When the frontend runs over plain HTTP, crypto.subtle is unavailable and
checksum_sha256 cannot be computed.  This migration makes the checksum
columns nullable so uploads still succeed without a client-side hash.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # upload_files.checksum_sha256: NOT NULL -> nullable
    op.alter_column(
        "upload_files",
        "checksum_sha256",
        existing_type=sa.String(64),
        nullable=True,
    )
    # recordings.hash: NOT NULL -> nullable
    op.alter_column(
        "recordings",
        "hash",
        existing_type=sa.String(64),
        nullable=True,
    )


def downgrade() -> None:
    # Revert recordings.hash to NOT NULL (backfill empty string for NULLs)
    op.execute("UPDATE recordings SET hash = '' WHERE hash IS NULL")
    op.alter_column(
        "recordings",
        "hash",
        existing_type=sa.String(64),
        nullable=False,
    )
    # Revert upload_files.checksum_sha256 to NOT NULL
    op.execute("UPDATE upload_files SET checksum_sha256 = '' WHERE checksum_sha256 IS NULL")
    op.alter_column(
        "upload_files",
        "checksum_sha256",
        existing_type=sa.String(64),
        nullable=False,
    )
