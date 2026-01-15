"""Create sound search tables.

Revision ID: c006_create_sound_search_tables
Revises: c005_species_filters
Create Date: 2025-12-26 00:00:00.000000

Creates tables for Sound Explorer feature - embedding-based similarity search:
- sound_search: Main search entity
- sound_search_dataset_scope: Links searches to datasets and their embeddings
- sound_search_reference_sound: Links reference sounds to searches
- sound_search_result: Stores search results with similarity scores
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c006_sound_search"
down_revision: Union[str, None] = "c005_species_filters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM type for sound_search_status
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'sound_search_status'
            ) THEN
                CREATE TYPE sound_search_status AS ENUM (
                    'pending',
                    'running',
                    'completed',
                    'failed',
                    'cancelled'
                );
            END IF;
        END
        $$;
        """
    )

    # Create sound_search table
    op.create_table(
        "sound_search",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("foundation_model_id", sa.Integer(), nullable=False),
        sa.Column(
            "similarity_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.7",
        ),
        sa.Column(
            "max_results_per_dataset",
            sa.Integer(),
            nullable=False,
            server_default="1000",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="sound_search_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "progress",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "total_results",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.project_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["foundation_model_id"],
            ["foundation_model.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_sound_search_project_id",
        "sound_search",
        ["project_id"],
    )
    op.create_index(
        "ix_sound_search_status",
        "sound_search",
        ["status"],
    )
    op.create_index(
        "ix_sound_search_created_by_id",
        "sound_search",
        ["created_by_id"],
    )

    # Create sound_search_dataset_scope table
    op.create_table(
        "sound_search_dataset_scope",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sound_search_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("foundation_model_run_id", sa.Integer(), nullable=False),
        sa.Column(
            "clips_searched",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "results_found",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["sound_search_id"],
            ["sound_search.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["dataset.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["foundation_model_run_id"],
            ["foundation_model_run.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "sound_search_id",
            "dataset_id",
            name="uq_sound_search_dataset_scope_search_dataset",
        ),
    )
    op.create_index(
        "ix_sound_search_dataset_scope_search_id",
        "sound_search_dataset_scope",
        ["sound_search_id"],
    )

    # Create sound_search_reference_sound table
    op.create_table(
        "sound_search_reference_sound",
        sa.Column("sound_search_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("reference_sound_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "weight",
            sa.Float(),
            nullable=False,
            server_default="1.0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["sound_search_id"],
            ["sound_search.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_sound_id"],
            ["reference_sound.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "sound_search_id",
            "reference_sound_id",
            name="uq_sound_search_reference_sound_search_ref",
        ),
    )
    op.create_index(
        "ix_sound_search_reference_sound_search_id",
        "sound_search_reference_sound",
        ["sound_search_id"],
    )

    # Create sound_search_result table
    op.create_table(
        "sound_search_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("sound_search_id", sa.Integer(), nullable=False),
        sa.Column("clip_id", sa.Integer(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column(
            "saved_as_annotation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("sound_event_annotation_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["sound_search_id"],
            ["sound_search.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clip_id"],
            ["clip.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sound_event_annotation_id"],
            ["sound_event_annotation.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "sound_search_id",
            "clip_id",
            name="uq_sound_search_result_search_clip",
        ),
    )
    op.create_index(
        "ix_sound_search_result_search_id",
        "sound_search_result",
        ["sound_search_id"],
    )
    op.create_index(
        "ix_sound_search_result_similarity",
        "sound_search_result",
        ["sound_search_id", "similarity"],
    )
    op.create_index(
        "ix_sound_search_result_rank",
        "sound_search_result",
        ["sound_search_id", "rank"],
    )


def downgrade() -> None:
    # Drop tables in reverse order of creation
    op.drop_index(
        "ix_sound_search_result_rank",
        table_name="sound_search_result",
    )
    op.drop_index(
        "ix_sound_search_result_similarity",
        table_name="sound_search_result",
    )
    op.drop_index(
        "ix_sound_search_result_search_id",
        table_name="sound_search_result",
    )
    op.drop_table("sound_search_result")

    op.drop_index(
        "ix_sound_search_reference_sound_search_id",
        table_name="sound_search_reference_sound",
    )
    op.drop_table("sound_search_reference_sound")

    op.drop_index(
        "ix_sound_search_dataset_scope_search_id",
        table_name="sound_search_dataset_scope",
    )
    op.drop_table("sound_search_dataset_scope")

    op.drop_index(
        "ix_sound_search_created_by_id",
        table_name="sound_search",
    )
    op.drop_index(
        "ix_sound_search_status",
        table_name="sound_search",
    )
    op.drop_index(
        "ix_sound_search_project_id",
        table_name="sound_search",
    )
    op.drop_table("sound_search")

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS sound_search_status CASCADE")
