"""Add self_training_svm to custom_model_type enum.

Revision ID: c036_add_self_training_svm
Revises: c035_add_training_scores
Create Date: 2026-01-09 08:45:00.000000

This migration adds 'self_training_svm' to the custom_model_type enum.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c036"
down_revision: Union[str, None] = "c035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'self_training_svm' to custom_model_type enum."""
    # PostgreSQL doesn't support ALTER TYPE ADD VALUE in a transaction,
    # so we use op.execute with proper isolation
    op.execute(
        """
        ALTER TYPE custom_model_type ADD VALUE IF NOT EXISTS 'self_training_svm'
        """
    )


def downgrade() -> None:
    """Remove 'self_training_svm' from custom_model_type enum.

    Note: PostgreSQL doesn't support removing enum values directly.
    This would require recreating the enum type, which is complex.
    For now, we leave the value in the enum on downgrade.
    """
    # Cannot remove enum values in PostgreSQL without recreating the type
    # This is left as a no-op for safety
    pass
