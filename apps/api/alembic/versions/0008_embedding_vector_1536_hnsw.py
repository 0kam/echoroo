"""Upgrade embeddings to 1536-dimensional vectors and switch to HNSW index.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-06 00:00:00.000000

Perch v2.0 uses 1536-dimensional embeddings (vs the original 1024-dimensional
vectors from Perch v1). This migration:
- Clears all existing embeddings (derived data; safe to truncate)
- Alters the vector column from vector(1024) to vector(1536)
- Replaces the IVFFlat index with an HNSW index for cosine similarity
  (HNSW gives better recall with no need for a separate training step)
- Adds an index on model_name for per-model queries
- Adds 'perch' to the detectionsource enum for direct Perch inference runs
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Migrate embeddings table to 1536-dim vectors with HNSW index."""

    # ------------------------------------------------------------------
    # Step 1: Clear existing embeddings (derived data; safe to truncate)
    # ------------------------------------------------------------------

    op.execute("DELETE FROM embeddings")

    # ------------------------------------------------------------------
    # Step 2: Drop the old IVFFlat vector index (if it exists)
    # ------------------------------------------------------------------

    op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_ivfflat")

    # ------------------------------------------------------------------
    # Step 3: Alter vector column from vector(1024) to vector(1536)
    # ------------------------------------------------------------------

    op.execute("ALTER TABLE embeddings ALTER COLUMN vector TYPE vector(1536)")

    # ------------------------------------------------------------------
    # Step 4: Create HNSW index for cosine similarity search
    # m=16 / ef_construction=64 are the standard balanced defaults
    # ------------------------------------------------------------------

    op.execute(
        "CREATE INDEX ix_embeddings_vector_hnsw "
        "ON embeddings USING hnsw (vector vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # ------------------------------------------------------------------
    # Step 5: Add model_name index for per-model queries
    # ------------------------------------------------------------------

    op.create_index("ix_embeddings_model_name", "embeddings", ["model_name"])

    # ------------------------------------------------------------------
    # Step 6: Add 'perch' value to detectionsource enum
    # IF NOT EXISTS prevents errors if the value was already added manually
    # ------------------------------------------------------------------

    op.execute("ALTER TYPE detectionsource ADD VALUE IF NOT EXISTS 'perch'")


def downgrade() -> None:
    """Revert embeddings table to 1024-dim vectors."""

    # Drop HNSW vector index
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_hnsw")

    # Drop model_name index
    op.execute("DROP INDEX IF EXISTS ix_embeddings_model_name")

    # Clear embeddings before altering column type
    op.execute("DELETE FROM embeddings")

    # Revert vector column from vector(1536) to vector(1024)
    op.execute("ALTER TABLE embeddings ALTER COLUMN vector TYPE vector(1024)")

    # Note: PostgreSQL does not support removing enum values once added,
    # so 'perch' remains in the detectionsource enum after downgrade.
