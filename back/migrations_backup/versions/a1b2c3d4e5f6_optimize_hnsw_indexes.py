"""Optimize HNSW indexes for vector search.

This migration optimizes the HNSW indexes on embedding tables by:
- Dropping existing default HNSW indexes
- Creating new HNSW indexes with tuned parameters:
  - m = 16 (connections per layer for better recall)
  - ef_construction = 64 (build-time search width for quality)
  - vector_cosine_ops for cosine similarity search

The optimized parameters provide a good balance between:
- Search accuracy (recall)
- Index build time
- Query performance
- Memory usage

Revision ID: a1b2c3d4e5f6
Revises: 6dfeb8d1860f
Create Date: 2025-12-04

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "6dfeb8d1860f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Only apply to PostgreSQL (pgvector is PostgreSQL-specific)
    if dialect_name != "postgresql":
        return

    # Drop existing HNSW indexes (created without optimized parameters)
    op.execute("DROP INDEX IF EXISTS clip_embedding_hnsw_idx")
    op.execute("DROP INDEX IF EXISTS sound_event_embedding_hnsw_idx")

    # Create optimized HNSW index for clip embeddings
    # Parameters:
    #   m = 16: Number of connections per layer (higher = better recall, more memory)
    #   ef_construction = 64: Build-time search width (higher = better quality, slower build)
    op.execute(
        """
        CREATE INDEX ix_clip_embedding_vector_hnsw
        ON clip_embedding
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )

    # Create optimized HNSW index for sound event embeddings
    op.execute(
        """
        CREATE INDEX ix_sound_event_embedding_vector_hnsw
        ON sound_event_embedding
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Only apply to PostgreSQL
    if dialect_name != "postgresql":
        return

    # Drop optimized HNSW indexes
    op.execute("DROP INDEX IF EXISTS ix_clip_embedding_vector_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_sound_event_embedding_vector_hnsw")

    # Recreate original HNSW indexes (without parameters, using defaults)
    op.execute(
        """
        CREATE INDEX clip_embedding_hnsw_idx
        ON clip_embedding
        USING hnsw (embedding vector_cosine_ops)
        """
    )

    op.execute(
        """
        CREATE INDEX sound_event_embedding_hnsw_idx
        ON sound_event_embedding
        USING hnsw (embedding vector_cosine_ops)
        """
    )
