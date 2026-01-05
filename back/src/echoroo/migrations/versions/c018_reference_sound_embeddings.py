"""Add reference_sound_embeddings table with sliding window support.

Revision ID: c018
Revises: c017
Create Date: 2025-01-05

This migration:
1. Creates a new reference_sound_embeddings table to store multiple embeddings per reference sound
2. Migrates existing embeddings from reference_sounds.embedding to the new table
3. Removes the embedding column from reference_sounds table

Each reference sound can now have multiple embeddings generated using a sliding window approach,
allowing for better matching against the selected audio segment.
"""

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "c018"
down_revision: str | None = "c017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create reference_sound_embeddings table
    op.create_table(
        "reference_sound_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_sound_id", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),  # Variable dimensions (1024 BirdNET, 1536 Perch)
        sa.Column("window_start_time", sa.Float(), nullable=False),
        sa.Column("window_end_time", sa.Float(), nullable=False),
        sa.Column("created_on", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["reference_sound_id"],
            ["reference_sound.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indices for better query performance
    op.create_index(
        "ix_reference_sound_embeddings_reference_sound_id",
        "reference_sound_embeddings",
        ["reference_sound_id"],
    )

    # Note: Cannot create IVFFlat index on variable-dimension vector column.
    # Similarity searches will use cosine distance operator directly.
    # If performance becomes an issue, consider using HNSW index which supports
    # some optimizations, or ensure all embeddings have the same dimension.

    # Migrate existing embeddings from reference_sound to reference_sound_embeddings
    # For existing embeddings, use the full time range (start_time to end_time)
    op.execute(
        """
        INSERT INTO reference_sound_embeddings (reference_sound_id, embedding, window_start_time, window_end_time)
        SELECT id, embedding, start_time, end_time
        FROM reference_sound
        WHERE embedding IS NOT NULL
        """
    )

    # Remove embedding column from reference_sound
    op.drop_column("reference_sound", "embedding")


def downgrade() -> None:
    """Downgrade database schema."""
    # Add embedding column back to reference_sound
    op.add_column(
        "reference_sound",
        sa.Column("embedding", Vector(), nullable=True),
    )

    # Migrate embeddings back (take the first embedding for each reference sound)
    # Note: This will lose additional embeddings if multiple exist
    op.execute(
        """
        UPDATE reference_sound rs
        SET embedding = (
            SELECT rse.embedding
            FROM reference_sound_embeddings rse
            WHERE rse.reference_sound_id = rs.id
            ORDER BY rse.id
            LIMIT 1
        )
        """
    )

    # Drop indices
    op.drop_index("ix_reference_sound_embeddings_reference_sound_id")

    # Drop table
    op.drop_table("reference_sound_embeddings")
