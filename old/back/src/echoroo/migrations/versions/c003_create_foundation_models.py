"""Create foundation model tables.

Revision ID: c003_create_foundation_models
Revises: c002_create_species_detection
Create Date: 2025-12-07 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c003_create_foundation_models"
down_revision: Union[str, None] = "c002_create_species_detection"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'foundation_model_run_status'
            ) THEN
                CREATE TYPE foundation_model_run_status AS ENUM (
                    'queued',
                    'running',
                    'post_processing',
                    'completed',
                    'failed',
                    'cancelled'
                );
            END IF;
        END
        $$;
        """
    )

    op.create_table(
        "foundation_model",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("slug", sa.String(length=128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "default_confidence_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.1",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("provider", "version", name="uq_foundation_model_provider_version"),
    )

    op.create_table(
        "foundation_model_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("foundation_model_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("species_detection_job_id", sa.Integer(), nullable=True),
        sa.Column("model_run_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "queued",
                "running",
                "post_processing",
                "completed",
                "failed",
                "cancelled",
                name="foundation_model_run_status",
                create_type=False,
            ),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("confidence_threshold", sa.Float(), nullable=False, server_default="0.1"),
        sa.Column("scope", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_recordings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_recordings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_clips", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_detections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("classification_csv_path", sa.Text(), nullable=True),
        sa.Column("embedding_store_key", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["foundation_model_id"],
            ["foundation_model.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["dataset.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["user.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["species_detection_job_id"],
            ["species_detection_job.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"],
            ["model_run.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_foundation_model_run_dataset",
        "foundation_model_run",
        ["dataset_id"],
    )
    op.create_index(
        "ix_foundation_model_run_model",
        "foundation_model_run",
        ["foundation_model_id"],
    )
    op.create_index(
        "ix_foundation_model_run_status",
        "foundation_model_run",
        ["status"],
    )
    op.create_index(
        "ix_foundation_model_run_job",
        "foundation_model_run",
        ["species_detection_job_id"],
    )

    op.create_table(
        "foundation_model_run_species",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("foundation_model_run_id", sa.Integer(), nullable=False),
        sa.Column("gbif_taxon_id", sa.String(length=64), nullable=True),
        sa.Column("annotation_tag_id", sa.Integer(), nullable=True),
        sa.Column("scientific_name", sa.String(length=255), nullable=False),
        sa.Column("common_name_ja", sa.String(length=255), nullable=True),
        sa.Column("detection_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["foundation_model_run_id"],
            ["foundation_model_run.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["annotation_tag_id"],
            ["tag.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "foundation_model_run_id",
            "gbif_taxon_id",
            name="uq_foundation_model_run_species_taxon",
        ),
    )
    op.create_index(
        "ix_foundation_model_run_species_run",
        "foundation_model_run_species",
        ["foundation_model_run_id"],
    )

    foundation_model_table = sa.table(
        "foundation_model",
        sa.column("uuid", postgresql.UUID()),
        sa.column("slug", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("version", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("default_confidence_threshold", sa.Float()),
    )
    op.bulk_insert(
        foundation_model_table,
        [
            {
                "uuid": str(uuid4()),
                "slug": "birdnet-v2-4",
                "display_name": "BirdNET",
                "provider": "birdnet",
                "version": "2.4",
                "description": "BirdNET foundation classifier v2.4",
                "default_confidence_threshold": 0.1,
            },
            {
                "uuid": str(uuid4()),
                "slug": "perch-v2-0",
                "display_name": "Perch",
                "provider": "perch",
                "version": "2.0",
                "description": "Perch large bioacoustic foundation model v2.0",
                "default_confidence_threshold": 0.1,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_foundation_model_run_species_run", table_name="foundation_model_run_species")
    op.drop_table("foundation_model_run_species")
    op.drop_index("ix_foundation_model_run_job", table_name="foundation_model_run")
    op.drop_index("ix_foundation_model_run_status", table_name="foundation_model_run")
    op.drop_index("ix_foundation_model_run_model", table_name="foundation_model_run")
    op.drop_index("ix_foundation_model_run_dataset", table_name="foundation_model_run")
    op.drop_table("foundation_model_run")
    op.drop_table("foundation_model")

    op.execute("DROP TYPE IF EXISTS foundation_model_run_status CASCADE")
