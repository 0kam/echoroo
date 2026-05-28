"""Re-seed default recorder master rows.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-28

The original seed for the ``recorders`` master lived in
``0003_seed_default_recorders`` but was dropped from the active migration
chain during the spec/006 permissions redesign baseline rebuild
(``0001_baseline_permissions_redesign`` collapsed the schema, and the
old 0003 seed was moved under ``versions/.archive/``). Long-lived
databases still carry the rows; freshly-built environments end up with
an empty ``recorders`` table, so ``/admin/recorders`` shows nothing and
the dataset-create flow cannot pick a recorder model.

This migration restores the 5 well-known recorder models that the
archived 0003 seed used to install. ``INSERT ... ON CONFLICT (id) DO
NOTHING`` keeps the migration safe for databases that already carry
those rows (anything created before the baseline rebuild).
"""

from __future__ import annotations

import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_DEFAULT_RECORDER_IDS: list[str] = [
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
    """Insert default recorder rows; idempotent via ON CONFLICT DO NOTHING."""

    now = datetime.datetime.now(datetime.timezone.utc)
    conn = op.get_bind()
    stmt = sa.text(
        "INSERT INTO recorders "
        "(id, manufacturer, recorder_name, version, created_at, updated_at) "
        "VALUES (:id, :manufacturer, :recorder_name, :version, :created_at, :updated_at) "
        "ON CONFLICT (id) DO NOTHING"
    )
    for r in _DEFAULT_RECORDERS:
        conn.execute(
            stmt,
            {
                "id": r["id"],
                "manufacturer": r["manufacturer"],
                "recorder_name": r["recorder_name"],
                "version": r["version"],
                "created_at": now,
                "updated_at": now,
            },
        )


def downgrade() -> None:
    """Delete the seeded default recorder rows by id."""

    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM recorders WHERE id = ANY(:ids)"),
        {"ids": _DEFAULT_RECORDER_IDS},
    )
