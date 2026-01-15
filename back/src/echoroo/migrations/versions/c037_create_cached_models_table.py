"""Create cached_models table for PostgreSQL-based model caching.

Revision ID: c037_create_cached_models
Revises: c036_add_self_training_svm
Create Date: 2026-01-10 00:00:00.000000

This migration creates a table to store cached machine learning models,
replacing the Redis-based caching mechanism with PostgreSQL storage.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c037"
down_revision: Union[str, None] = "c036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create cached_models table for model caching."""
    op.create_table(
        "cached_model",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_uuid", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("iteration", sa.Integer, nullable=False),
        sa.Column("model_data", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("session_uuid", "iteration", name="uq_cached_model_session_iteration"),
        sa.ForeignKeyConstraint(
            ["session_uuid"],
            ["search_session.uuid"],
            name="fk_cached_model_session_uuid",
            ondelete="CASCADE",
        ),
    )

    # Create index on created_at for potential cleanup queries
    op.create_index(
        "ix_cached_model_created_at",
        "cached_model",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop cached_models table."""
    op.drop_index("ix_cached_model_created_at", table_name="cached_model")
    op.drop_table("cached_model")
