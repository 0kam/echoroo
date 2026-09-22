"""Add resumable-upload byte accounting and chunk metadata.

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-21

Resumable uploads need durable byte accounting and ordered chunk digests on
each upload file, plus a database guard allowing at most one active upload
session per dataset. The migration also heals any pre-launch duplicate active
sessions before creating that partial unique index.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "upload_files",
        sa.Column("received_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "upload_files",
        sa.Column("declared_size", sa.BigInteger(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE upload_files SET declared_size = file_size "
            "WHERE declared_size IS NULL"
        )
    )
    op.alter_column(
        "upload_files",
        "declared_size",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.add_column(
        "upload_files",
        sa.Column(
            "chunk_digests",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_upload_files_received_bytes_nonnegative",
        "upload_files",
        sa.text("received_bytes >= 0"),
    )
    op.create_check_constraint(
        "ck_upload_files_received_within_declared",
        "upload_files",
        sa.text("received_bytes <= declared_size"),
    )
    op.create_check_constraint(
        "ck_upload_files_chunk_digests_array",
        "upload_files",
        sa.text("jsonb_typeof(chunk_digests) = 'array'"),
    )
    op.execute(
        sa.text(
            """
            UPDATE upload_sessions AS s
            SET status = 'failed',
                error = 'Superseded: more than one active upload session for the dataset (migration 0038)'
            FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY dataset_id ORDER BY updated_at DESC, id DESC
                       ) AS rn
                FROM upload_sessions
                WHERE status IN ('issued', 'uploaded', 'validating', 'validated', 'importing')
            ) AS ranked
            WHERE s.id = ranked.id AND ranked.rn > 1
            """
        )
    )
    op.create_index(
        "ux_upload_sessions_active_dataset",
        "upload_sessions",
        ["dataset_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('issued', 'uploaded', 'validating', 'validated', 'importing')"
        ),
    )


def downgrade() -> None:
    op.drop_index("ux_upload_sessions_active_dataset", table_name="upload_sessions")
    op.drop_constraint(
        "ck_upload_files_chunk_digests_array", "upload_files", type_="check"
    )
    op.drop_constraint(
        "ck_upload_files_received_within_declared", "upload_files", type_="check"
    )
    op.drop_constraint(
        "ck_upload_files_received_bytes_nonnegative", "upload_files", type_="check"
    )
    op.drop_column("upload_files", "chunk_digests")
    op.drop_column("upload_files", "declared_size")
    op.drop_column("upload_files", "received_bytes")
