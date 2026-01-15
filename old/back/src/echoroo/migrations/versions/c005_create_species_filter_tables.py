"""Create species filter tables.

Revision ID: c005_create_species_filter_tables
Revises: c004_dynamic_embeddings
Create Date: 2025-12-25 00:00:00.000000

Creates tables for species filtering based on geographic and occurrence data:
- species_occurrence_cache: Caches geo-filtered species occurrence data
- species_filter: Filter definitions (e.g., BirdNET geographic filter)
- species_filter_application: Tracks application of filters to model runs
- species_filter_mask: Per-prediction filter decisions
"""

from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c005_species_filters"
down_revision: Union[str, None] = "c004_dynamic_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM types
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'species_filter_type'
            ) THEN
                CREATE TYPE species_filter_type AS ENUM (
                    'geographic',
                    'occurrence',
                    'custom'
                );
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'species_filter_application_status'
            ) THEN
                CREATE TYPE species_filter_application_status AS ENUM (
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

    # Create species_occurrence_cache table
    op.create_table(
        "species_occurrence_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("latitude_bucket", sa.Integer(), nullable=False),
        sa.Column("longitude_bucket", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("original_label", sa.String(length=255), nullable=False),
        sa.Column("scientific_name", sa.String(length=255), nullable=False),
        sa.Column("occurrence_probability", sa.Float(), nullable=False),
        sa.Column("gbif_taxon_key", sa.String(length=64), nullable=True),
        sa.Column("gbif_canonical_name", sa.String(length=255), nullable=True),
        sa.Column(
            "gbif_resolution_status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("resolved_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "latitude_bucket",
            "longitude_bucket",
            "week",
            "original_label",
            name="uq_species_occurrence_cache_location_week_label",
        ),
    )
    op.create_index(
        "ix_species_occurrence_cache_location_week",
        "species_occurrence_cache",
        ["latitude_bucket", "longitude_bucket", "week"],
    )
    op.create_index(
        "ix_species_occurrence_cache_gbif_taxon_key",
        "species_occurrence_cache",
        ["gbif_taxon_key"],
    )

    # Create species_filter table
    op.create_table(
        "species_filter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("slug", sa.String(length=128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "filter_type",
            postgresql.ENUM(
                "geographic",
                "occurrence",
                "custom",
                name="species_filter_type",
                create_type=False,
            ),
            nullable=False,
            server_default="geographic",
        ),
        sa.Column(
            "default_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.03",
        ),
        sa.Column(
            "requires_location",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "requires_date",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
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
        sa.UniqueConstraint(
            "provider",
            "version",
            name="uq_species_filter_provider_version",
        ),
    )

    # Create species_filter_application table
    op.create_table(
        "species_filter_application",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("foundation_model_run_id", sa.Integer(), nullable=False),
        sa.Column("species_filter_id", sa.Integer(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False, server_default="0.03"),
        sa.Column(
            "apply_to_all_detections",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="species_filter_application_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_detections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filtered_detections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excluded_detections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("applied_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("started_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_on", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            ["species_filter_id"],
            ["species_filter.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["applied_by_id"],
            ["user.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "foundation_model_run_id",
            "species_filter_id",
            name="uq_species_filter_application_run_filter",
        ),
    )
    op.create_index(
        "ix_species_filter_application_run_id",
        "species_filter_application",
        ["foundation_model_run_id"],
    )
    op.create_index(
        "ix_species_filter_application_status",
        "species_filter_application",
        ["status"],
    )

    # Create species_filter_mask table
    op.create_table(
        "species_filter_mask",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("species_filter_application_id", sa.Integer(), nullable=False),
        sa.Column("clip_prediction_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("is_included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("occurrence_probability", sa.Float(), nullable=True),
        sa.Column("exclusion_reason", sa.String(length=255), nullable=True),
        sa.Column(
            "created_on",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["species_filter_application_id"],
            ["species_filter_application.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["clip_prediction_id"],
            ["clip_prediction.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["tag.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "species_filter_application_id",
            "clip_prediction_id",
            "tag_id",
            name="uq_species_filter_mask_application_prediction_tag",
        ),
    )
    op.create_index(
        "ix_species_filter_mask_application_id",
        "species_filter_mask",
        ["species_filter_application_id"],
    )
    op.create_index(
        "ix_species_filter_mask_application_included",
        "species_filter_mask",
        ["species_filter_application_id", "is_included"],
    )

    # Insert initial data for BirdNET geographic filter
    species_filter_table = sa.table(
        "species_filter",
        sa.column("uuid", postgresql.UUID()),
        sa.column("slug", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("version", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("filter_type", sa.String()),
        sa.column("default_threshold", sa.Float()),
        sa.column("requires_location", sa.Boolean()),
        sa.column("requires_date", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        species_filter_table,
        [
            {
                "uuid": str(uuid4()),
                "slug": "birdnet-geo-v2-4",
                "display_name": "BirdNET Geographic Filter",
                "provider": "birdnet",
                "version": "2.4",
                "description": "Species occurrence filter based on BirdNET geo model. Filters predictions based on geographic location and time of year.",
                "filter_type": "geographic",
                "default_threshold": 0.03,
                "requires_location": True,
                "requires_date": True,
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    # Drop tables in reverse order of creation
    op.drop_index(
        "ix_species_filter_mask_application_included",
        table_name="species_filter_mask",
    )
    op.drop_index(
        "ix_species_filter_mask_application_id",
        table_name="species_filter_mask",
    )
    op.drop_table("species_filter_mask")

    op.drop_index(
        "ix_species_filter_application_status",
        table_name="species_filter_application",
    )
    op.drop_index(
        "ix_species_filter_application_run_id",
        table_name="species_filter_application",
    )
    op.drop_table("species_filter_application")

    op.drop_table("species_filter")

    op.drop_index(
        "ix_species_occurrence_cache_gbif_taxon_key",
        table_name="species_occurrence_cache",
    )
    op.drop_index(
        "ix_species_occurrence_cache_location_week",
        table_name="species_occurrence_cache",
    )
    op.drop_table("species_occurrence_cache")

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS species_filter_application_status CASCADE")
    op.execute("DROP TYPE IF EXISTS species_filter_type CASCADE")
