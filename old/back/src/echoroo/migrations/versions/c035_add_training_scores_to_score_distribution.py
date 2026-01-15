"""Add training scores to score distribution.

Revision ID: c035
Revises: c034
Create Date: 2026-01-09 00:00:00.000000

Description:
-----------
Add training_positive_scores and training_negative_scores columns to
iteration_score_distribution table to enable histogram overlay visualization
of training data predictions alongside unlabeled data predictions.

This allows users to visually verify that the model is correctly separating
training samples, helping identify potential training issues.

New columns:
- training_positive_scores: Array of prediction scores for positive training samples
- training_negative_scores: Array of prediction scores for negative training samples
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c035"
down_revision: str | None = "c034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add training score columns to iteration_score_distribution."""
    # Add training_positive_scores column with empty array default
    op.add_column(
        "iteration_score_distribution",
        sa.Column(
            "training_positive_scores",
            postgresql.ARRAY(sa.Float()),
            nullable=False,
            server_default="{}",
        ),
    )

    # Add training_negative_scores column with empty array default
    op.add_column(
        "iteration_score_distribution",
        sa.Column(
            "training_negative_scores",
            postgresql.ARRAY(sa.Float()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    """Remove training score columns from iteration_score_distribution."""
    op.drop_column("iteration_score_distribution", "training_negative_scores")
    op.drop_column("iteration_score_distribution", "training_positive_scores")
