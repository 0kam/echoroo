"""Add search_query_embeddings table and link custom_models to search sessions and datasets.

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-10 00:00:00.000000

Extends the model training pipeline with query embedding persistence and
links custom models back to their originating search session and dataset:
- search_query_embeddings: persists the query vectors used during a search
  session so they can be reused as positive training examples.
- custom_models.search_session_id: FK to the search session that generated
  the training data.
- custom_models.dataset_id: FK to the dataset the model was applied to.
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create search_query_embeddings table and add FK columns to custom_models."""

    # --- search_query_embeddings -------------------------------------------
    op.create_table(
        "search_query_embeddings",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("search_session_id", sa.UUID(), nullable=False),
        sa.Column("species_key", sa.Text(), nullable=True),
        sa.Column("source_label", sa.Text(), nullable=True),
        sa.Column(
            "vector",
            Vector(1536),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["search_session_id"],
            ["search_sessions.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_search_query_embeddings_search_session_id",
        "search_query_embeddings",
        ["search_session_id"],
    )

    # --- custom_models: add search_session_id column -----------------------
    op.add_column(
        "custom_models",
        sa.Column(
            "search_session_id",
            sa.UUID(),
            nullable=True,
            comment="Source search session whose results were used as training data",
        ),
    )
    op.create_foreign_key(
        "fk_custom_models_search_session_id",
        "custom_models",
        "search_sessions",
        ["search_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_custom_models_search_session_id",
        "custom_models",
        ["search_session_id"],
    )

    # --- custom_models: add dataset_id column ------------------------------
    op.add_column(
        "custom_models",
        sa.Column(
            "dataset_id",
            sa.UUID(),
            nullable=True,
            comment="Dataset the model was applied to after training",
        ),
    )
    op.create_foreign_key(
        "fk_custom_models_dataset_id",
        "custom_models",
        "datasets",
        ["dataset_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Reverse all changes introduced in this migration."""
    op.drop_constraint("fk_custom_models_dataset_id", "custom_models", type_="foreignkey")
    op.drop_column("custom_models", "dataset_id")

    op.drop_index("ix_custom_models_search_session_id", table_name="custom_models")
    op.drop_constraint("fk_custom_models_search_session_id", "custom_models", type_="foreignkey")
    op.drop_column("custom_models", "search_session_id")

    op.drop_index(
        "ix_search_query_embeddings_search_session_id",
        table_name="search_query_embeddings",
    )
    op.drop_table("search_query_embeddings")
