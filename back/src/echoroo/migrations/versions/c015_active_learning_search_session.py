"""Active Learning support for Search Session.

Revision ID: c015
Revises: c014
Create Date: 2026-01-04

This migration restructures the search session tables to support Active Learning:

Changes to search_session:
- Removes target_tag_id (replaced by search_session_target_tag table)
- Removes similarity_threshold
- Adds easy_positive_k, boundary_n, boundary_m, others_p for sampling parameters
- Adds current_iteration for tracking active learning progress

Changes to search_result:
- Removes label enum field
- Adds assigned_tag_id (FK to tag) for positive labels
- Adds is_negative, is_uncertain, is_skipped boolean flags
- Adds sample_type, iteration_added, model_score for sampling metadata
- Adds source_tag_id (FK to tag) for tracking sample origin

New table search_session_target_tag:
- Links search sessions to multiple target tags
- Includes shortcut_key (1-9) for quick labeling

Migration strategy: Drop and recreate tables (existing data will be deleted).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c015"
down_revision: Union[str, None] = "c014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing tables in reverse dependency order
    # 1. Drop search_result (depends on search_session)
    op.drop_index(
        "ix_search_result_saved_to_annotation_project_id",
        table_name="search_result",
        if_exists=True,
    )
    op.drop_table("search_result")

    # 2. Drop search_session_dataset_scope (depends on search_session)
    op.drop_index(
        "ix_search_session_dataset_scope_session_id",
        table_name="search_session_dataset_scope",
        if_exists=True,
    )
    op.drop_table("search_session_dataset_scope")

    # 3. Drop search_session_reference_sound (depends on search_session)
    op.drop_table("search_session_reference_sound")

    # 4. Drop search_session
    op.drop_table("search_session")

    # 5. Drop the search_result_label enum type
    op.execute("DROP TYPE IF EXISTS search_result_label CASCADE")

    # Create new search_session table with Active Learning fields
    op.create_table(
        "search_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ml_project_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Active Learning sampling parameters
        sa.Column(
            "easy_positive_k",
            sa.Integer(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "boundary_n",
            sa.Integer(),
            nullable=False,
            server_default="200",
        ),
        sa.Column(
            "boundary_m",
            sa.Integer(),
            nullable=False,
            server_default="10",
        ),
        sa.Column(
            "others_p",
            sa.Integer(),
            nullable=False,
            server_default="20",
        ),
        sa.Column(
            "current_iteration",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_results",
            sa.Integer(),
            nullable=False,
            server_default="1000",
        ),
        sa.Column("filter_config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "is_search_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_labeling_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "search_all_scopes",
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
            ["ml_project_id"],
            ["ml_project.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_search_session_ml_project_id",
        "search_session",
        ["ml_project_id"],
    )

    # Create search_session_target_tag table (new)
    op.create_table(
        "search_session_target_tag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_session_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("shortcut_key", sa.Integer(), nullable=False),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["search_session_id"],
            ["search_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tag.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "tag_id",
            name="uq_search_session_target_tag_session_tag",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "shortcut_key",
            name="uq_search_session_target_tag_session_shortcut",
        ),
    )
    op.create_index(
        "ix_search_session_target_tag_search_session_id",
        "search_session_target_tag",
        ["search_session_id"],
    )

    # Create search_session_reference_sound table
    op.create_table(
        "search_session_reference_sound",
        sa.Column("search_session_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("reference_sound_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["search_session_id"],
            ["search_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_sound_id"],
            ["reference_sound.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "reference_sound_id",
            name="uq_search_session_reference_sound",
        ),
    )

    # Create search_session_dataset_scope table
    op.create_table(
        "search_session_dataset_scope",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_session_id", sa.Integer(), nullable=False),
        sa.Column("ml_project_dataset_scope_id", sa.Integer(), nullable=False),
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
            ["search_session_id"],
            ["search_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ml_project_dataset_scope_id"],
            ["ml_project_dataset_scope.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "ml_project_dataset_scope_id",
            name="uq_search_session_dataset_scope",
        ),
    )
    op.create_index(
        "ix_search_session_dataset_scope_session_id",
        "search_session_dataset_scope",
        ["search_session_id"],
    )

    # Create new search_result table with Active Learning fields
    op.create_table(
        "search_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("search_session_id", sa.Integer(), nullable=False),
        sa.Column("clip_id", sa.Integer(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        # Labeling fields (replaces enum-based label)
        sa.Column("assigned_tag_id", sa.Integer(), nullable=True),
        sa.Column(
            "is_negative",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_uncertain",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_skipped",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        # Sampling metadata
        sa.Column("sample_type", sa.String(length=50), nullable=True),
        sa.Column("iteration_added", sa.Integer(), nullable=True),
        sa.Column("model_score", sa.Float(), nullable=True),
        sa.Column("source_tag_id", sa.Integer(), nullable=True),
        # User tracking
        sa.Column("labeled_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("labeled_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("saved_to_annotation_project_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["search_session_id"],
            ["search_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clip_id"],
            ["clip.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_tag_id"],
            ["tag.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_tag_id"],
            ["tag.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["labeled_by_id"],
            ["user.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["saved_to_annotation_project_id"],
            ["annotation_project.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "clip_id",
            name="uq_search_result_session_clip",
        ),
    )
    op.create_index(
        "ix_search_result_search_session_id",
        "search_result",
        ["search_session_id"],
    )
    op.create_index(
        "ix_search_result_similarity",
        "search_result",
        ["search_session_id", "similarity"],
    )
    op.create_index(
        "ix_search_result_rank",
        "search_result",
        ["search_session_id", "rank"],
    )
    op.create_index(
        "ix_search_result_sample_type",
        "search_result",
        ["search_session_id", "sample_type"],
    )
    op.create_index(
        "ix_search_result_iteration_added",
        "search_result",
        ["search_session_id", "iteration_added"],
    )
    op.create_index(
        "ix_search_result_saved_to_annotation_project_id",
        "search_result",
        ["saved_to_annotation_project_id"],
    )


def downgrade() -> None:
    # Drop new tables
    op.drop_index("ix_search_result_saved_to_annotation_project_id", table_name="search_result")
    op.drop_index("ix_search_result_iteration_added", table_name="search_result")
    op.drop_index("ix_search_result_sample_type", table_name="search_result")
    op.drop_index("ix_search_result_rank", table_name="search_result")
    op.drop_index("ix_search_result_similarity", table_name="search_result")
    op.drop_index("ix_search_result_search_session_id", table_name="search_result")
    op.drop_table("search_result")

    op.drop_index("ix_search_session_dataset_scope_session_id", table_name="search_session_dataset_scope")
    op.drop_table("search_session_dataset_scope")

    op.drop_table("search_session_reference_sound")

    op.drop_index("ix_search_session_target_tag_search_session_id", table_name="search_session_target_tag")
    op.drop_table("search_session_target_tag")

    op.drop_index("ix_search_session_ml_project_id", table_name="search_session")
    op.drop_table("search_session")

    # Recreate search_result_label enum type
    op.execute(
        """
        CREATE TYPE search_result_label AS ENUM (
            'unlabeled',
            'positive',
            'negative',
            'uncertain',
            'skipped',
            'positive_reference',
            'negative_reference'
        )
        """
    )

    # Recreate original search_session table
    op.create_table(
        "search_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ml_project_id", sa.Integer(), nullable=False),
        sa.Column("target_tag_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "similarity_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.7",
        ),
        sa.Column(
            "max_results",
            sa.Integer(),
            nullable=False,
            server_default="1000",
        ),
        sa.Column("filter_config", postgresql.JSONB(), nullable=True),
        sa.Column(
            "is_search_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_labeling_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "search_all_scopes",
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
            ["ml_project_id"],
            ["ml_project.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["target_tag_id"],
            ["tag.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["user.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_search_session_ml_project_id",
        "search_session",
        ["ml_project_id"],
    )

    # Recreate search_session_reference_sound table
    op.create_table(
        "search_session_reference_sound",
        sa.Column("search_session_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("reference_sound_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["search_session_id"],
            ["search_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reference_sound_id"],
            ["reference_sound.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "reference_sound_id",
        ),
    )

    # Recreate search_session_dataset_scope table
    op.create_table(
        "search_session_dataset_scope",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("search_session_id", sa.Integer(), nullable=False),
        sa.Column("ml_project_dataset_scope_id", sa.Integer(), nullable=False),
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
            ["search_session_id"],
            ["search_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ml_project_dataset_scope_id"],
            ["ml_project_dataset_scope.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "ml_project_dataset_scope_id",
            name="uq_search_session_dataset_scope",
        ),
    )
    op.create_index(
        "ix_search_session_dataset_scope_session_id",
        "search_session_dataset_scope",
        ["search_session_id"],
    )

    # Recreate original search_result table
    op.create_table(
        "search_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("search_session_id", sa.Integer(), nullable=False),
        sa.Column("clip_id", sa.Integer(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column(
            "label",
            postgresql.ENUM(
                "unlabeled",
                "positive",
                "negative",
                "uncertain",
                "skipped",
                "positive_reference",
                "negative_reference",
                name="search_result_label",
                create_type=False,
            ),
            nullable=False,
            server_default="unlabeled",
        ),
        sa.Column("labeled_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("labeled_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("saved_to_annotation_project_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["search_session_id"],
            ["search_session.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clip_id"],
            ["clip.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["labeled_by_id"],
            ["user.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["saved_to_annotation_project_id"],
            ["annotation_project.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "search_session_id",
            "clip_id",
        ),
    )
    op.create_index(
        "ix_search_result_saved_to_annotation_project_id",
        "search_result",
        ["saved_to_annotation_project_id"],
    )
