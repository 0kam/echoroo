"""Add signal_quality column to annotation_votes table.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-06 00:00:00.000000

Adds signal_quality enum column to annotation_votes to capture how prominently
the target species appears in the audio clip. Only applicable when vote is 'agree'.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | None = None
depends_on: str | None = None

# Enum definition
signalquality_enum = sa.Enum(
    "solo",
    "dominant",
    "mixed",
    name="signalquality",
)


def upgrade() -> None:
    """Add signalquality enum type and signal_quality column."""
    signalquality_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "annotation_votes",
        sa.Column(
            "signal_quality",
            signalquality_enum,
            nullable=True,
            comment="Signal quality assessment (only applicable when vote is 'agree')",
        ),
    )


def downgrade() -> None:
    """Remove signal_quality column and signalquality enum type."""
    op.drop_column("annotation_votes", "signal_quality")
    signalquality_enum.drop(op.get_bind(), checkfirst=True)
