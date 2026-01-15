"""Add locale column to species_detection_job.

Revision ID: c008_add_locale
Revises: c007_extend_custom_model
Create Date: 2025-12-31 00:00:00.000000

This migration adds locale support for BirdNET species detection:
- Add locale column to species_detection_job table (default='en_us')

The locale is used to control the language of common names returned
by BirdNET during inference.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c008_add_locale"
down_revision: Union[str, None] = "c007_extend_custom_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add locale column to species_detection_job table
    op.add_column(
        "species_detection_job",
        sa.Column(
            "locale",
            sa.String(length=16),
            nullable=False,
            server_default="en_us",
        ),
    )


def downgrade() -> None:
    # Remove locale column from species_detection_job table
    op.drop_column("species_detection_job", "locale")
