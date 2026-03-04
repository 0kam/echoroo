"""ML pipeline: add embeddings table for Perch feature vectors.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-04 00:00:00.000000

This migration adds the embeddings table for storing ML feature vectors:
- embeddings: Perch/BirdNET embedding vectors per time window of a recording

Also enables the pgvector extension and creates an IVFFlat index for ANN search.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Enable pgvector and create embeddings table."""

    # ------------------------------------------------------------------
    # Step 1: Enable pgvector extension
    # ------------------------------------------------------------------

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ------------------------------------------------------------------
    # Step 2: Create embeddings table
    # ------------------------------------------------------------------

    op.create_table(
        "embeddings",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "recording_id",
            UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "detection_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("detection_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column(
            "vector",
            sa.Text(),  # placeholder column; replaced with vector(1024) type below
            nullable=True,  # temporarily nullable during type migration
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Replace placeholder text column with the proper pgvector type (1024 dimensions for Perch)
    op.execute("ALTER TABLE embeddings DROP COLUMN vector")
    op.execute("ALTER TABLE embeddings ADD COLUMN vector vector(1024) NOT NULL")

    # ------------------------------------------------------------------
    # Step 3: Create indexes
    # ------------------------------------------------------------------

    op.create_index("ix_embeddings_recording_id", "embeddings", ["recording_id"])
    op.create_index("ix_embeddings_detection_run_id", "embeddings", ["detection_run_id"])

    # IVFFlat index for approximate nearest-neighbour search (cosine distance)
    # lists=100 is a reasonable default for up to ~1M vectors
    op.execute(
        "CREATE INDEX ix_embeddings_vector_ivfflat "
        "ON embeddings USING ivfflat (vector vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    """Drop embeddings table."""

    op.drop_table("embeddings")
    # Note: we intentionally do NOT drop the vector extension as other tables may use it.
