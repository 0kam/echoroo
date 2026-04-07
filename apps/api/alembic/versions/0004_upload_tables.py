"""Upload feature: add upload_sessions and upload_files tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-03 00:00:00.000000

This migration adds the upload feature tables:
- upload_sessions: Tracks presigned URL issuance through import completion
- upload_files: Individual file records within an upload session

Also creates new enum types: uploadsessionstatus, uploadfilestatus
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create upload tables and enum types."""

    # ------------------------------------------------------------------
    # Step 1: Create new PostgreSQL enum types via raw SQL
    # ------------------------------------------------------------------

    op.execute(
        "CREATE TYPE uploadsessionstatus AS ENUM "
        "('issued', 'uploaded', 'validating', 'validated', 'importing', 'imported', 'failed')"
    )
    op.execute(
        "CREATE TYPE uploadfilestatus AS ENUM "
        "('pending', 'uploaded', 'valid', 'invalid', 'imported')"
    )

    # ------------------------------------------------------------------
    # Step 2: Create upload_sessions table
    # ------------------------------------------------------------------

    op.create_table(
        "upload_sessions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dataset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="issued",
        ),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("validated_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("imported_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Cast status column to use the enum type (drop default first to avoid cast error)
    op.execute("ALTER TABLE upload_sessions ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE upload_sessions ALTER COLUMN status TYPE uploadsessionstatus "
        "USING status::uploadsessionstatus"
    )
    op.execute("ALTER TABLE upload_sessions ALTER COLUMN status SET DEFAULT 'issued'::uploadsessionstatus")

    op.create_index("ix_upload_sessions_dataset_id", "upload_sessions", ["dataset_id"])
    op.create_index("ix_upload_sessions_status", "upload_sessions", ["status"])
    op.create_index("ix_upload_sessions_expires_at", "upload_sessions", ["expires_at"])
    op.create_index(
        "ix_upload_sessions_dataset_id_status",
        "upload_sessions",
        ["dataset_id", "status"],
    )

    # ------------------------------------------------------------------
    # Step 3: Create upload_files table
    # ------------------------------------------------------------------

    op.create_table(
        "upload_files",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("upload_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False, unique=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column(
            "status",
            sa.VARCHAR(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("samplerate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("bit_depth", sa.Integer(), nullable=True),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column(
            "recording_id",
            UUID(as_uuid=True),
            sa.ForeignKey("recordings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Cast status column to use the enum type (drop default first to avoid cast error)
    op.execute("ALTER TABLE upload_files ALTER COLUMN status DROP DEFAULT")
    op.execute(
        "ALTER TABLE upload_files ALTER COLUMN status TYPE uploadfilestatus "
        "USING status::uploadfilestatus"
    )
    op.execute("ALTER TABLE upload_files ALTER COLUMN status SET DEFAULT 'pending'::uploadfilestatus")

    op.create_index("ix_upload_files_session_id", "upload_files", ["session_id"])
    op.create_index(
        "ix_upload_files_object_key", "upload_files", ["object_key"], unique=True
    )
    op.create_index("ix_upload_files_status", "upload_files", ["status"])
    op.create_index("ix_upload_files_recording_id", "upload_files", ["recording_id"])


def downgrade() -> None:
    """Drop upload tables and enum types."""

    # Drop tables in reverse dependency order
    op.drop_table("upload_files")
    op.drop_table("upload_sessions")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS uploadfilestatus")
    op.execute("DROP TYPE IF EXISTS uploadsessionstatus")
