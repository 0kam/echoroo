"""Integrate SpeciesDetectionJob into FoundationModelRun.

Revision ID: c028
Revises: c027
Create Date: 2026-01-06

This migration:
1. Adds new columns to foundation_model_run (migrated from species_detection_job)
2. Updates detection_review FK from species_detection_job_id to foundation_model_run_id
3. Drops species_detection_job table and related types

Note: All existing data will be dropped as per user requirements.
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c028"
down_revision: str | None = "c027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Integrate SpeciesDetectionJob into FoundationModelRun."""
    # Step 0: Ensure detection_review_status enum exists (may be missing in fresh install)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'detection_review_status') THEN
                CREATE TYPE detection_review_status AS ENUM ('unreviewed', 'confirmed', 'rejected', 'uncertain');
            END IF;
        END
        $$;
    """)

    # Step 1: Add new columns to foundation_model_run
    op.add_column(
        "foundation_model_run",
        sa.Column("name", sa.String(), nullable=True),
    )
    op.add_column(
        "foundation_model_run",
        sa.Column("model_name", sa.String(), nullable=False, server_default="birdnet"),
    )
    op.add_column(
        "foundation_model_run",
        sa.Column("model_version", sa.String(), nullable=False, server_default="latest"),
    )
    op.add_column(
        "foundation_model_run",
        sa.Column("overlap", sa.Float(), nullable=False, server_default="0.0"),
    )
    op.add_column(
        "foundation_model_run",
        sa.Column("locale", sa.String(16), nullable=False, server_default="ja"),
    )
    op.add_column(
        "foundation_model_run",
        sa.Column("use_metadata_filter", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "foundation_model_run",
        sa.Column("custom_species_list", postgresql.JSONB(), nullable=True),
    )

    # Step 2: Update detection_review - add new FK column
    op.add_column(
        "detection_review",
        sa.Column("foundation_model_run_id", sa.Integer(), nullable=True),
    )

    # Step 3: Migrate FK data if exists (from species_detection_job to foundation_model_run)
    op.execute("""
        UPDATE detection_review dr
        SET foundation_model_run_id = fmr.id
        FROM species_detection_job sdj
        JOIN foundation_model_run fmr ON fmr.species_detection_job_id = sdj.id
        WHERE dr.species_detection_job_id = sdj.id
    """)

    # Step 4: Add FK constraint for detection_review
    op.create_foreign_key(
        "fk_detection_review_foundation_model_run",
        "detection_review",
        "foundation_model_run",
        ["foundation_model_run_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Step 5: Drop old constraints and columns
    # Drop old unique constraint on detection_review
    op.execute("""
        ALTER TABLE detection_review
        DROP CONSTRAINT IF EXISTS detection_review_clip_prediction_id_species_detection_job_id_key
    """)

    # Drop old FK column from detection_review
    op.drop_column("detection_review", "species_detection_job_id")

    # Create new unique constraint
    op.create_unique_constraint(
        "uq_detection_review_clip_prediction_run",
        "detection_review",
        ["clip_prediction_id", "foundation_model_run_id"],
    )

    # Step 6: Drop species_detection_job_id from foundation_model_run
    op.drop_column("foundation_model_run", "species_detection_job_id")

    # Step 7: Drop species_detection_job table
    op.drop_table("species_detection_job")

    # Step 8: Drop species_detection_job_status enum type
    op.execute("DROP TYPE IF EXISTS species_detection_job_status")


def downgrade() -> None:
    """Revert integration - recreate species_detection_job table."""
    # Recreate enum type
    op.execute("""
        CREATE TYPE species_detection_job_status AS ENUM (
            'pending', 'running', 'completed', 'failed', 'cancelled'
        )
    """)

    # Recreate species_detection_job table
    op.create_table(
        "species_detection_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("uuid", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("dataset_id", sa.Integer(), sa.ForeignKey("dataset.id"), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False, server_default="latest"),
        sa.Column("confidence_threshold", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("overlap", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("locale", sa.String(16), nullable=False, server_default="en_us"),
        sa.Column("use_metadata_filter", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("custom_species_list", postgresql.JSONB(), nullable=True),
        sa.Column("recording_filters", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("pending", "running", "completed", "failed", "cancelled", name="species_detection_job_status", create_type=False),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("total_recordings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_recordings", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_clips", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_detections", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_on", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("model_run.id"), nullable=True),
    )

    # Add species_detection_job_id back to foundation_model_run
    op.add_column(
        "foundation_model_run",
        sa.Column("species_detection_job_id", sa.Integer(), sa.ForeignKey("species_detection_job.id"), nullable=True),
    )

    # Add species_detection_job_id back to detection_review
    op.add_column(
        "detection_review",
        sa.Column("species_detection_job_id", sa.Integer(), sa.ForeignKey("species_detection_job.id"), nullable=True),
    )

    # Drop new constraint
    op.drop_constraint("uq_detection_review_clip_prediction_run", "detection_review")

    # Drop new FK column
    op.drop_constraint("fk_detection_review_foundation_model_run", "detection_review")
    op.drop_column("detection_review", "foundation_model_run_id")

    # Recreate old unique constraint
    op.create_unique_constraint(
        "detection_review_clip_prediction_id_species_detection_job_id_key",
        "detection_review",
        ["clip_prediction_id", "species_detection_job_id"],
    )

    # Drop new columns from foundation_model_run
    op.drop_column("foundation_model_run", "name")
    op.drop_column("foundation_model_run", "model_name")
    op.drop_column("foundation_model_run", "model_version")
    op.drop_column("foundation_model_run", "overlap")
    op.drop_column("foundation_model_run", "locale")
    op.drop_column("foundation_model_run", "use_metadata_filter")
    op.drop_column("foundation_model_run", "custom_species_list")
