"""Seed foundation models.

Revision ID: c029
Revises: c028
Create Date: 2026-01-06

This migration seeds the foundation_model table with default models.
Uses INSERT ... ON CONFLICT DO NOTHING to be idempotent.
"""

from typing import Sequence

from alembic import op


revision: str = "c029"
down_revision: str | None = "c028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Seed foundation models."""
    op.execute("""
        INSERT INTO foundation_model (uuid, slug, display_name, provider, version, description, default_confidence_threshold, is_active, created_on)
        VALUES
            (gen_random_uuid(), 'birdnet_v2_4', 'BirdNET v2.4', 'birdnet', '2.4', 'BirdNET foundation classifier v2.4', 0.1, true, NOW()),
            (gen_random_uuid(), 'perch_v2_0', 'Perch v2.0', 'perch', '2.0', 'Perch large bioacoustic foundation model v2.0', 0.1, true, NOW())
        ON CONFLICT (slug) DO NOTHING;
    """)


def downgrade() -> None:
    """Remove seeded foundation models."""
    op.execute("""
        DELETE FROM foundation_model
        WHERE slug IN ('birdnet_v2_4', 'perch_v2_0');
    """)
