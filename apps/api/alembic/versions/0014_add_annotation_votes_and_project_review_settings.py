"""Add annotation_votes table and project review settings.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-06 00:00:00.000000

Adds the annotation_votes table for team-based iNaturalist-style voting on
detection annotations, and adds review_min_votes / review_consensus_threshold
columns to the projects table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create annotation_votes table and add project review settings columns."""

    # Create the votetype enum using raw SQL to support IF NOT EXISTS
    op.execute("CREATE TYPE votetype AS ENUM ('agree', 'disagree', 'unsure')")

    # Create annotation_votes table
    op.create_table(
        "annotation_votes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "annotation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("annotations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vote",
            postgresql.ENUM(
                "agree",
                "disagree",
                "unsure",
                name="votetype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "suggested_tag_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "note",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "annotation_id",
            "user_id",
            name="uq_annotation_vote_user",
        ),
    )

    # Add indexes
    op.create_index(
        "ix_annotation_votes_annotation_id",
        "annotation_votes",
        ["annotation_id"],
    )
    op.create_index(
        "ix_annotation_votes_user_id",
        "annotation_votes",
        ["user_id"],
    )

    # Add review settings columns to projects table
    op.add_column(
        "projects",
        sa.Column(
            "review_min_votes",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "review_consensus_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.667",
        ),
    )


def downgrade() -> None:
    """Drop annotation_votes table and remove project review settings columns."""

    # Remove project columns
    op.drop_column("projects", "review_consensus_threshold")
    op.drop_column("projects", "review_min_votes")

    # Drop annotation_votes table (indexes dropped automatically)
    op.drop_index("ix_annotation_votes_user_id", table_name="annotation_votes")
    op.drop_index("ix_annotation_votes_annotation_id", table_name="annotation_votes")
    op.drop_table("annotation_votes")

    # Drop enum type
    op.execute("DROP TYPE IF EXISTS votetype")
