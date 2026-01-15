"""Fix Perch logit scores.

Revision ID: c033
Revises: c032
Create Date: 2026-01-06 13:50:00.000000

Description:
-----------
Perch model was storing logit values (range: -inf to +inf) instead of
probabilities (range: 0 to 1) in the clip_prediction_tag.score column.

This migration applies sigmoid transformation to convert existing logit
values to probabilities for all Perch predictions:
sigmoid(x) = 1 / (1 + exp(-x))

Only scores > 1.0 are transformed (as they are likely logits).
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c033"
down_revision: str | None = "c032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply sigmoid to Perch logit scores."""
    # Update scores that are > 1.0 (logits) to probabilities using sigmoid
    # 1 / (1 + exp(-score))
    op.execute(
        """
        UPDATE clip_prediction_tag cpt
        SET score = 1.0 / (1.0 + EXP(-score))
        WHERE score > 1.0
        AND EXISTS (
            SELECT 1
            FROM clip_prediction cp
            JOIN model_run_prediction mrp ON cp.id = mrp.clip_prediction_id
            JOIN model_run mr ON mrp.model_run_id = mr.id
            JOIN foundation_model_run fmr ON mr.id = fmr.model_run_id
            JOIN foundation_model fm ON fmr.foundation_model_id = fm.id
            WHERE cp.id = cpt.clip_prediction_id
            AND fm.slug LIKE 'perch_%'
        )
        """
    )


def downgrade() -> None:
    """Downgrade not supported (logit values cannot be recovered from probabilities)."""
    pass
