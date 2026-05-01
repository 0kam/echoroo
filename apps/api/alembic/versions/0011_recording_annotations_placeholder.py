"""Phase 13 P6 follow-up: materialise recording_annotations_DEFERRED placeholder.

Revision ID: 0011
Revises: 0010
Create Date: 2026-04-29 00:00:00.000000

P1.5 R2 introduced apps/api/echoroo/models/recording_annotation.py with
__tablename__ = "recording_annotations_DEFERRED" so any rich-shape detection
review query in services/detection.py would fail loudly with
``relation "recording_annotations_DEFERRED" does not exist`` rather than
silently degrade.

Phase 13 P6 browser-Gate-3 testing then revealed that the production
``GET /api/v1/projects/{id}/detections/species-summary`` endpoint hits this
service on first page-load even when a project has no detection runs yet.

This migration creates the placeholder table empty so the production query
returns 0 rows instead of 500. Phase 14+ replaces the contents and renames
the table to recording_annotations atomically.

The identifier is double-quoted so PostgreSQL preserves the mixed-case
suffix ``_DEFERRED`` instead of folding it to lowercase. Both SQLAlchemy
``__tablename__`` and the queries below quote the name; the parity test
confirms fresh-from-baseline DBs and incrementally upgraded dev DBs both
land on the same case-sensitive identifier.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


_TABLE = '"recording_annotations_DEFERRED"'


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            recording_id UUID NOT NULL
                REFERENCES recordings(id) ON DELETE CASCADE,
            tag_id UUID
                REFERENCES tags(id) ON DELETE SET NULL,
            detection_run_id UUID
                REFERENCES detection_runs(id) ON DELETE SET NULL,
            source detectionsource NOT NULL,
            status detectionstatus NOT NULL DEFAULT 'unreviewed',
            confidence DOUBLE PRECISION,
            start_time DOUBLE PRECISION NOT NULL,
            end_time DOUBLE PRECISION NOT NULL,
            freq_low DOUBLE PRECISION,
            freq_high DOUBLE PRECISION,
            reviewed_by_id UUID
                REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at TIMESTAMP WITH TIME ZONE,
            search_session_id UUID
                REFERENCES search_sessions(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_recording_annotations_recording "
        f"ON {_TABLE} (recording_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_recording_annotations_tag "
        f"ON {_TABLE} (tag_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_recording_annotations_run "
        f"ON {_TABLE} (detection_run_id)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_recording_annotations_status "
        f"ON {_TABLE} (status)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_recording_annotations_source "
        f"ON {_TABLE} (source)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_recording_annotations_confidence "
        f"ON {_TABLE} (confidence)"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_recording_annotations_DEFERRED_search_session_id "
        f"ON {_TABLE} (search_session_id)"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLE} CASCADE")


_ = sa  # keep sqlalchemy import for parity with sibling migrations
