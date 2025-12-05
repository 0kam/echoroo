"""Add inference job and embedding tables.

This migration adds support for:
- InferenceJob: Tracks ML inference jobs with status and progress
- ClipEmbedding: Stores embedding vectors for audio clips
- SoundEventEmbedding: Stores embedding vectors for sound events

The embedding tables use pgvector for efficient vector similarity search.

Revision ID: 6dfeb8d1860f
Revises: 7ea39f3ee58d
Create Date: 2025-12-04

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "6dfeb8d1860f"
down_revision: Union[str, None] = "7ea39f3ee58d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Enable pgvector extension (PostgreSQL only)
    if dialect_name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create inference_job table
    op.create_table(
        "inference_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "model_run_id",
            sa.Integer(),
            sa.ForeignKey("model_run.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "dataset_id",
            sa.Integer(),
            sa.ForeignKey("dataset.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recording_id",
            sa.Integer(),
            sa.ForeignKey("recording.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(),
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
            "total_items",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "processed_items",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "started_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=True,
        ),
        sa.Column(
            "completed_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inference_job")),
    )

    # Create clip_embedding table
    op.create_table(
        "clip_embedding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "clip_id",
            sa.Integer(),
            sa.ForeignKey("clip.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_run_id",
            sa.Integer(),
            sa.ForeignKey("model_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clip_embedding")),
        sa.UniqueConstraint(
            "clip_id",
            "model_run_id",
            name=op.f("uq_clip_embedding_clip_id"),
        ),
    )

    # Create sound_event_embedding table
    op.create_table(
        "sound_event_embedding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "sound_event_id",
            sa.Integer(),
            sa.ForeignKey("sound_event.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_run_id",
            sa.Integer(),
            sa.ForeignKey("model_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column(
            "created_on",
            sa.DateTime().with_variant(
                sa.TIMESTAMP(timezone=True),
                "postgresql",
            ),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sound_event_embedding")),
        sa.UniqueConstraint(
            "sound_event_id",
            "model_run_id",
            name=op.f("uq_sound_event_embedding_sound_event_id"),
        ),
    )

    # Create HNSW indexes for fast vector similarity search (PostgreSQL only)
    if dialect_name == "postgresql":
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

    # Create standard indexes for foreign keys
    op.create_index(
        op.f("ix_inference_job_model_run_id"),
        "inference_job",
        ["model_run_id"],
    )
    op.create_index(
        op.f("ix_inference_job_dataset_id"),
        "inference_job",
        ["dataset_id"],
    )
    op.create_index(
        op.f("ix_inference_job_recording_id"),
        "inference_job",
        ["recording_id"],
    )
    op.create_index(
        op.f("ix_inference_job_status"),
        "inference_job",
        ["status"],
    )
    op.create_index(
        op.f("ix_clip_embedding_clip_id"),
        "clip_embedding",
        ["clip_id"],
    )
    op.create_index(
        op.f("ix_clip_embedding_model_run_id"),
        "clip_embedding",
        ["model_run_id"],
    )
    op.create_index(
        op.f("ix_sound_event_embedding_sound_event_id"),
        "sound_event_embedding",
        ["sound_event_id"],
    )
    op.create_index(
        op.f("ix_sound_event_embedding_model_run_id"),
        "sound_event_embedding",
        ["model_run_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Drop indexes
    op.drop_index(
        op.f("ix_sound_event_embedding_model_run_id"),
        table_name="sound_event_embedding",
    )
    op.drop_index(
        op.f("ix_sound_event_embedding_sound_event_id"),
        table_name="sound_event_embedding",
    )
    op.drop_index(
        op.f("ix_clip_embedding_model_run_id"),
        table_name="clip_embedding",
    )
    op.drop_index(
        op.f("ix_clip_embedding_clip_id"),
        table_name="clip_embedding",
    )
    op.drop_index(
        op.f("ix_inference_job_status"),
        table_name="inference_job",
    )
    op.drop_index(
        op.f("ix_inference_job_recording_id"),
        table_name="inference_job",
    )
    op.drop_index(
        op.f("ix_inference_job_dataset_id"),
        table_name="inference_job",
    )
    op.drop_index(
        op.f("ix_inference_job_model_run_id"),
        table_name="inference_job",
    )

    # Drop HNSW indexes (PostgreSQL only)
    if dialect_name == "postgresql":
        op.execute("DROP INDEX IF EXISTS sound_event_embedding_hnsw_idx")
        op.execute("DROP INDEX IF EXISTS clip_embedding_hnsw_idx")

    # Drop tables
    op.drop_table("sound_event_embedding")
    op.drop_table("clip_embedding")
    op.drop_table("inference_job")
