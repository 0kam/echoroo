"""Add search_sessions table and search_session_id to annotations.

Revision ID: 0011
Revises: 0010
Create Date: 2026-03-12 00:00:00.000000

Creates the search_sessions table to persist batch similarity search sessions,
and adds a search_session_id foreign key column to the annotations table so
annotations created via search sessions can be traced back to their origin.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create searchsessionstatus enum, search_sessions table, and update annotations."""
    # Create search_sessions table; sa.Enum will create the searchsessionstatus type automatically
    op.create_table(
        "search_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                name="searchsessionstatus",
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column("species_config", postgresql.JSONB(), nullable=True),
        sa.Column("results", postgresql.JSONB(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("celery_job_id", sa.String(100), nullable=True),
        sa.Column("reference_audio_keys", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Create indexes on search_sessions
    op.create_index("ix_search_sessions_project_id", "search_sessions", ["project_id"])
    op.create_index("ix_search_sessions_user_id", "search_sessions", ["user_id"])
    op.create_index("ix_search_sessions_status", "search_sessions", ["status"])
    op.create_index("ix_search_sessions_created_at", "search_sessions", ["created_at"])

    # Add search_session_id column to annotations table
    op.add_column(
        "annotations",
        sa.Column(
            "search_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("search_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Create index on annotations.search_session_id
    op.create_index(
        "ix_annotations_search_session_id",
        "annotations",
        ["search_session_id"],
    )


def downgrade() -> None:
    """Remove search_session_id from annotations and drop search_sessions table."""
    # Remove index and column from annotations
    op.drop_index("ix_annotations_search_session_id", table_name="annotations")
    op.drop_column("annotations", "search_session_id")

    # Drop search_sessions table and indexes
    op.drop_index("ix_search_sessions_created_at", table_name="search_sessions")
    op.drop_index("ix_search_sessions_status", table_name="search_sessions")
    op.drop_index("ix_search_sessions_user_id", table_name="search_sessions")
    op.drop_index("ix_search_sessions_project_id", table_name="search_sessions")
    op.drop_table("search_sessions")

    # Drop the enum type
    op.execute("DROP TYPE IF EXISTS searchsessionstatus")
