"""Seed default recorder types into the recorders table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-03 00:00:00.000000

This migration inserts 5 well-known audio recorder models as default seed data:
- AudioMoth 1.2.0 (Open Acoustic Devices)
- Song Meter Micro2 (Wildlife Acoustics)
- Song Meter Mini2 Li-ion (Wildlife Acoustics)
- Song Meter Mini2 AA (Wildlife Acoustics)
- Song Meter SM4 (Wildlife Acoustics)

Rows are inserted with ON CONFLICT DO NOTHING so re-running the migration
on a database that already has these records is safe.
"""

import datetime

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

# Default recorder seed data.
_DEFAULT_RECORDER_IDS = [
    "am120",
    "smmicro2",
    "smmini2li",
    "smmini2aa",
    "sm4",
]

_DEFAULT_RECORDERS: list[dict[str, str | None]] = [
    {
        "id": "am120",
        "manufacturer": "Open Acoustic Devices",
        "recorder_name": "AudioMoth",
        "version": "1.2.0",
    },
    {
        "id": "smmicro2",
        "manufacturer": "Wildlife Acoustics",
        "recorder_name": "Song Meter Micro2",
        "version": None,
    },
    {
        "id": "smmini2li",
        "manufacturer": "Wildlife Acoustics",
        "recorder_name": "Song Meter Mini2 Li-ion",
        "version": None,
    },
    {
        "id": "smmini2aa",
        "manufacturer": "Wildlife Acoustics",
        "recorder_name": "Song Meter Mini2 AA",
        "version": None,
    },
    {
        "id": "sm4",
        "manufacturer": "Wildlife Acoustics",
        "recorder_name": "Song Meter SM4",
        "version": None,
    },
]


def upgrade() -> None:
    """Insert default recorder rows with ON CONFLICT DO NOTHING."""

    now = datetime.datetime.now(datetime.UTC)

    rows = [
        {
            "id": r["id"],
            "manufacturer": r["manufacturer"],
            "recorder_name": r["recorder_name"],
            "version": r["version"],
            "created_at": now,
            "updated_at": now,
        }
        for r in _DEFAULT_RECORDERS
    ]

    # Use raw SQL to support ON CONFLICT DO NOTHING, which bulk_insert() does
    # not expose directly.  The parameters are bound safely via SQLAlchemy's
    # text() interface so there is no risk of SQL injection.
    conn = op.get_bind()
    for row in rows:
        conn.execute(
            sa.text(
                "INSERT INTO recorders (id, manufacturer, recorder_name, version, created_at, updated_at) "
                "VALUES (:id, :manufacturer, :recorder_name, :version, :created_at, :updated_at) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            row,
        )


def downgrade() -> None:
    """Delete the seeded default recorder rows."""

    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM recorders WHERE id = ANY(:ids)"),
        {"ids": _DEFAULT_RECORDER_IDS},
    )
