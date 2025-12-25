"""Create Species Detection tables.

Revision ID: c002_create_species_detection
Revises: c001_create_ml_project
Create Date: 2025-12-06 12:00:00.000000

This migration creates the Species Detection feature tables:
- species_detection_job: Tracks BirdNET/Perch analysis jobs
- detection_review: Tracks review status for detection results
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c002_create_species_detection"
down_revision: Union[str, None] = "c001_create_ml_project"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create ENUM types
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'species_detection_job_status') THEN
                CREATE TYPE species_detection_job_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'detection_review_status') THEN
                CREATE TYPE detection_review_status AS ENUM ('unreviewed', 'confirmed', 'rejected', 'uncertain');
            END IF;
        END
        $$;
    """)

    # Create species_detection_job table
    op.execute("""
        CREATE TABLE species_detection_job (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,
            name VARCHAR NOT NULL,
            dataset_id INTEGER NOT NULL REFERENCES dataset(id) ON DELETE CASCADE,
            created_by_id UUID REFERENCES "user"(id) ON DELETE SET NULL,

            -- Model configuration
            model_name VARCHAR NOT NULL,
            model_version VARCHAR NOT NULL DEFAULT 'latest',
            confidence_threshold FLOAT NOT NULL DEFAULT 0.5,
            overlap FLOAT NOT NULL DEFAULT 0.0,
            use_metadata_filter BOOLEAN NOT NULL DEFAULT true,
            custom_species_list JSONB,

            -- Recording filters
            recording_filters JSONB,

            -- Status tracking
            status species_detection_job_status NOT NULL DEFAULT 'pending',
            progress FLOAT NOT NULL DEFAULT 0.0,
            total_recordings INTEGER NOT NULL DEFAULT 0,
            processed_recordings INTEGER NOT NULL DEFAULT 0,
            total_clips INTEGER NOT NULL DEFAULT 0,
            total_detections INTEGER NOT NULL DEFAULT 0,

            -- Error handling
            error_message TEXT,

            -- Timestamps
            started_on TIMESTAMPTZ,
            completed_on TIMESTAMPTZ,
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            -- Result link
            model_run_id INTEGER REFERENCES model_run(id) ON DELETE SET NULL
        )
    """)
    op.execute("CREATE INDEX ix_species_detection_job_dataset_id ON species_detection_job(dataset_id)")
    op.execute("CREATE INDEX ix_species_detection_job_created_by_id ON species_detection_job(created_by_id)")
    op.execute("CREATE INDEX ix_species_detection_job_status ON species_detection_job(status)")
    op.execute("CREATE INDEX ix_species_detection_job_model_name ON species_detection_job(model_name)")
    op.execute("CREATE INDEX ix_species_detection_job_model_run_id ON species_detection_job(model_run_id)")

    # Create detection_review table
    op.execute("""
        CREATE TABLE detection_review (
            id SERIAL PRIMARY KEY,
            uuid UUID NOT NULL UNIQUE,

            -- Links
            clip_prediction_id INTEGER NOT NULL REFERENCES clip_prediction(id) ON DELETE CASCADE,
            species_detection_job_id INTEGER NOT NULL REFERENCES species_detection_job(id) ON DELETE CASCADE,

            -- Review info
            status detection_review_status NOT NULL DEFAULT 'unreviewed',
            reviewed_by_id UUID REFERENCES "user"(id) ON DELETE SET NULL,
            reviewed_on TIMESTAMPTZ,
            notes TEXT,

            -- Conversion tracking
            converted_to_annotation BOOLEAN NOT NULL DEFAULT false,
            clip_annotation_id INTEGER REFERENCES clip_annotation(id) ON DELETE SET NULL,

            -- Timestamps
            created_on TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            UNIQUE (clip_prediction_id, species_detection_job_id)
        )
    """)
    op.execute("CREATE INDEX ix_detection_review_clip_prediction_id ON detection_review(clip_prediction_id)")
    op.execute("CREATE INDEX ix_detection_review_species_detection_job_id ON detection_review(species_detection_job_id)")
    op.execute("CREATE INDEX ix_detection_review_status ON detection_review(status)")
    op.execute("CREATE INDEX ix_detection_review_reviewed_by_id ON detection_review(reviewed_by_id)")
    op.execute("CREATE INDEX ix_detection_review_converted_to_annotation ON detection_review(converted_to_annotation)")
    op.execute("CREATE INDEX ix_detection_review_clip_annotation_id ON detection_review(clip_annotation_id)")
    op.execute("CREATE INDEX ix_detection_review_job_status ON detection_review(species_detection_job_id, status)")


def downgrade() -> None:
    # Drop tables in reverse order
    op.execute("DROP TABLE IF EXISTS detection_review CASCADE")
    op.execute("DROP TABLE IF EXISTS species_detection_job CASCADE")

    # Drop ENUM types
    op.execute("DROP TYPE IF EXISTS detection_review_status CASCADE")
    op.execute("DROP TYPE IF EXISTS species_detection_job_status CASCADE")
