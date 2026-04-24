"""Detection review: add annotation, confirmed_region, and detection_run tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-02 00:00:00.000000

This migration adds the detection review feature tables:
- detection_runs: ML detection job tracking
- annotations: Detection annotations (new, separate from clip/sound_event annotations)
- confirmed_regions: Verified time segments in recordings

Also creates new enum types: detectionsource, detectionstatus, detectionrunstatus
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create detection review tables and enum types."""

    # ------------------------------------------------------------------
    # Step 1: Create new PostgreSQL enum types via raw SQL
    # ------------------------------------------------------------------

    op.execute("CREATE TYPE detectionsource AS ENUM ('birdnet', 'perch_search', 'human')")
    op.execute("CREATE TYPE detectionstatus AS ENUM ('unreviewed', 'confirmed', 'rejected')")
    op.execute("CREATE TYPE detectionrunstatus AS ENUM ('pending', 'running', 'completed', 'failed')")

    # ------------------------------------------------------------------
    # Step 2: Create detection_runs table (referenced by annotations)
    # ------------------------------------------------------------------

    op.create_table(
        "detection_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(50), nullable=False),
        sa.Column("parameters", JSONB, nullable=True),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("annotation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Cast status column to use the enum type
    op.execute("ALTER TABLE detection_runs ALTER COLUMN status TYPE detectionrunstatus USING status::detectionrunstatus")

    op.create_index("ix_detection_runs_project_id", "detection_runs", ["project_id"])
    op.create_index("ix_detection_runs_dataset_id", "detection_runs", ["dataset_id"])
    op.create_index("ix_detection_runs_status", "detection_runs", ["status"])
    op.create_index("ix_detection_runs_created_at", "detection_runs", ["created_at"])

    # ------------------------------------------------------------------
    # Step 3: Create annotations table
    # ------------------------------------------------------------------

    op.create_table(
        "annotations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "recording_id",
            UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tags.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "detection_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("detection_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.VARCHAR(20), nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="unreviewed",
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("freq_low", sa.Float(), nullable=True),
        sa.Column("freq_high", sa.Float(), nullable=True),
        sa.Column(
            "reviewed_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Cast columns to use enum types
    op.execute("ALTER TABLE annotations ALTER COLUMN source TYPE detectionsource USING source::detectionsource")
    op.execute("ALTER TABLE annotations ALTER COLUMN status TYPE detectionstatus USING status::detectionstatus")

    op.create_index("ix_annotations_recording_id", "annotations", ["recording_id"])
    op.create_index("ix_annotations_tag_id", "annotations", ["tag_id"])
    op.create_index("ix_annotations_detection_run_id", "annotations", ["detection_run_id"])
    op.create_index("ix_annotations_status", "annotations", ["status"])
    op.create_index("ix_annotations_source", "annotations", ["source"])
    op.create_index("ix_annotations_confidence", "annotations", ["confidence"])
    op.create_index("ix_annotations_created_at", "annotations", ["created_at"])

    # ------------------------------------------------------------------
    # Step 4: Create confirmed_regions table
    # ------------------------------------------------------------------

    op.create_table(
        "confirmed_regions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "recording_id",
            UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column(
            "reviewed_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_confirmed_regions_recording_id", "confirmed_regions", ["recording_id"])
    op.create_index("ix_confirmed_regions_reviewed_by_id", "confirmed_regions", ["reviewed_by_id"])
    op.create_index("ix_confirmed_regions_created_at", "confirmed_regions", ["created_at"])


def downgrade() -> None:
    """Drop detection review tables and enum types."""

    # Drop tables in reverse dependency order
    op.drop_table("confirmed_regions")
    op.drop_table("annotations")
    op.drop_table("detection_runs")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS detectionrunstatus")
    op.execute("DROP TYPE IF EXISTS detectionstatus")
    op.execute("DROP TYPE IF EXISTS detectionsource")
