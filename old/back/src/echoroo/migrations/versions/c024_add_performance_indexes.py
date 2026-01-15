"""Add performance indexes for ML Project queries.

Revision ID: c024
Revises: c023
Create Date: 2026-01-06

This migration adds database indexes to improve query performance for:
- Search result filtering (session-based labeling queries)
- Clip embedding lookups (similarity search)

These are non-breaking changes that only improve performance.
"""

from typing import Sequence

from alembic import op

revision: str = "c024"
down_revision: str | None = "c023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add performance indexes."""
    # Index for search result filtering queries
    # Used in active learning iteration, result filtering, and progress tracking
    op.create_index(
        "ix_search_result_session_labeling",
        "search_result",
        ["search_session_id", "is_negative", "is_uncertain", "is_skipped"],
        unique=False,
    )

    # Index for clip embedding lookups
    # Used in similarity search and active learning
    op.create_index(
        "ix_clip_embedding_clip_model",
        "clip_embedding",
        ["clip_id", "model_run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove performance indexes."""
    op.drop_index("ix_clip_embedding_clip_model", table_name="clip_embedding")
    op.drop_index("ix_search_result_session_labeling", table_name="search_result")
