"""Add prediction statistics to inference_batch table.

Revision ID: c038_add_prediction_statistics
Revises: c037_create_cached_models
Create Date: 2026-01-10 00:00:00.000000

This migration adds prediction statistics fields to the inference_batch table
to track positive/negative prediction counts and average confidence scores.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c038"
down_revision: Union[str, None] = "c037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add prediction statistics fields to inference_batch table."""
    op.add_column(
        "inference_batch",
        sa.Column(
            "positive_predictions_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "inference_batch",
        sa.Column(
            "negative_predictions_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "inference_batch",
        sa.Column(
            "average_confidence",
            sa.Float,
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove prediction statistics fields from inference_batch table."""
    op.drop_column("inference_batch", "average_confidence")
    op.drop_column("inference_batch", "negative_predictions_count")
    op.drop_column("inference_batch", "positive_predictions_count")
