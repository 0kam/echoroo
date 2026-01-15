"""Add dataset processing status tracking.

Revision ID: c034
Revises: c033
Create Date: 2026-01-08 00:00:00.000000

Description:
-----------
Add status tracking columns to the dataset table to support asynchronous
dataset creation with progress reporting. This enables background processing
of large datasets with real-time status updates.

New columns:
- status: Track dataset processing lifecycle (pending/scanning/processing/completed/failed)
- processing_progress: Integer 0-100 for progress bar display
- processing_error: Store error messages if processing fails
- total_files: Number of audio files discovered during scanning
- processed_files: Number of files successfully processed
"""
from typing import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c034"
down_revision: str | None = "c033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add dataset processing status columns."""
    # Create enum type for dataset status
    op.execute(
        """
        CREATE TYPE dataset_status AS ENUM (
            'pending',
            'scanning',
            'processing',
            'completed',
            'failed'
        )
        """
    )

    # Add status column with default 'completed' for existing datasets
    op.add_column(
        "dataset",
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "scanning",
                "processing",
                "completed",
                "failed",
                name="dataset_status",
            ),
            nullable=False,
            server_default="completed",
        ),
    )

    # Add processing progress column (0-100)
    op.add_column(
        "dataset",
        sa.Column(
            "processing_progress",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )

    # Add processing error column
    op.add_column(
        "dataset",
        sa.Column(
            "processing_error",
            sa.Text(),
            nullable=True,
        ),
    )

    # Add total files column
    op.add_column(
        "dataset",
        sa.Column(
            "total_files",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Add processed files column
    op.add_column(
        "dataset",
        sa.Column(
            "processed_files",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Remove dataset processing status columns."""
    op.drop_column("dataset", "processed_files")
    op.drop_column("dataset", "total_files")
    op.drop_column("dataset", "processing_error")
    op.drop_column("dataset", "processing_progress")
    op.drop_column("dataset", "status")
    op.execute("DROP TYPE dataset_status")
