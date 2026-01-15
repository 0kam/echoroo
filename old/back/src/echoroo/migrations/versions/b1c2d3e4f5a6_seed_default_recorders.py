"""Seed default recorders.

Revision ID: b1c2d3e4f5a6
Revises: a5549d9ba13d
Create Date: 2025-12-05 17:50:00.000000

"""

from __future__ import annotations

import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a5549d9ba13d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RECORDER_IDS = ["am120", "smmicro2", "smmini2li", "smmini2aa", "sm4"]

recorder_table = sa.table(
    "recorder",
    sa.column("recorder_id", sa.String(length=255)),
    sa.column("manufacturer", sa.String(length=255)),
    sa.column("recorder_name", sa.String(length=255)),
    sa.column("version", sa.String(length=255)),
    sa.column(
        "created_on",
        sa.DateTime().with_variant(sa.TIMESTAMP(timezone=True), "postgresql"),
    ),
)

DEFAULT_RECORDERS = [
    {
        "recorder_id": "am120",
        "manufacturer": "Open Acoustic Devices",
        "recorder_name": "AudioMoth",
        "version": "1.2.0",
    },
    {
        "recorder_id": "smmicro2",
        "manufacturer": "Wildlife Acoustics",
        "recorder_name": "Song Meter Micro2",
        "version": None,
    },
    {
        "recorder_id": "smmini2li",
        "manufacturer": "Wildlife Acoustics",
        "recorder_name": "Song Meter Mini2 Li-ion",
        "version": None,
    },
    {
        "recorder_id": "smmini2aa",
        "manufacturer": "Wildlife Acoustics",
        "recorder_name": "Song Meter Mini2 AA",
        "version": None,
    },
    {
        "recorder_id": "sm4",
        "manufacturer": "Wildlife Acoustics",
        "recorder_name": "Song Meter SM4",
        "version": None,
    },
]


def upgrade() -> None:
    conn = op.get_bind()
    existing_ids = {
        row.recorder_id
        for row in conn.execute(sa.select(recorder_table.c.recorder_id))
    }
    now = datetime.datetime.now(datetime.timezone.utc)
    to_insert: list[dict[str, object]] = []
    for recorder in DEFAULT_RECORDERS:
        if recorder["recorder_id"] not in existing_ids:
            to_insert.append({**recorder, "created_on": now})
    if to_insert:
        op.bulk_insert(recorder_table, to_insert)


def downgrade() -> None:
    op.execute(
        recorder_table.delete().where(
            recorder_table.c.recorder_id.in_(RECORDER_IDS),
        ),
    )
