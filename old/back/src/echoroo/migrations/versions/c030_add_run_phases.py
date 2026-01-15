"""Add run_embeddings and run_predictions flags to foundation_model_run.

Revision ID: c030
Revises: c029
Create Date: 2026-01-06

This migration adds two boolean flags to control two-phase execution:
- run_embeddings: Whether to generate embeddings (default=True)
- run_predictions: Whether to generate predictions (default=True)

This allows splitting foundation model runs into separate phases to reduce
GPU memory usage by avoiding multiple TensorFlow initializations.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c030"
down_revision: str | None = "c029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add run phase control flags to foundation_model_run."""
    # Add run_embeddings column with default=True
    op.add_column(
        "foundation_model_run",
        sa.Column(
            "run_embeddings",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )

    # Add run_predictions column with default=True
    op.add_column(
        "foundation_model_run",
        sa.Column(
            "run_predictions",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    """Remove run phase control flags from foundation_model_run."""
    op.drop_column("foundation_model_run", "run_predictions")
    op.drop_column("foundation_model_run", "run_embeddings")
