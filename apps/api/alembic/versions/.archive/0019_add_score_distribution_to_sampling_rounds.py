"""Add score_distribution JSONB column to sampling_rounds.

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-16 00:00:00.000000

Stores a 20-bin histogram of sigmoid(decision_distance) computed over all
unlabeled embeddings scored during an active-learning iteration. Users can
compare the distribution across rounds to decide when to stop sampling and
kick off training.

The column is nullable because seed rounds and legacy rounds will not have
this field populated.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add nullable score_distribution JSONB column to sampling_rounds."""
    op.add_column(
        "sampling_rounds",
        sa.Column(
            "score_distribution",
            JSONB(),
            nullable=True,
            comment=(
                "Histogram of sigmoid(decision_distance) over all scored "
                "unlabeled embeddings for this AL iteration."
            ),
        ),
    )


def downgrade() -> None:
    """Drop the score_distribution column from sampling_rounds."""
    op.drop_column("sampling_rounds", "score_distribution")
