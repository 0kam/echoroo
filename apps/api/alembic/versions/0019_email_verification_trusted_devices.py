"""Email verification and trusted devices.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-18 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "email_verification_tokens",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email_normalized", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_ip_hash", sa.String(64), nullable=True),
        sa.Column("created_user_agent_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_email_verification_tokens_active_token_hash",
        "email_verification_tokens",
        ["token_hash"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL AND superseded_at IS NULL"),
    )
    op.create_index(
        "ix_email_verification_tokens_active_user_purpose_email",
        "email_verification_tokens",
        ["user_id", "purpose", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL AND superseded_at IS NULL"),
    )
    op.create_index(
        "ix_email_verification_tokens_user_purpose_state_expires",
        "email_verification_tokens",
        ["user_id", "purpose", "consumed_at", "superseded_at", "expires_at"],
    )
    op.create_index(
        "ix_email_verification_tokens_expires_at",
        "email_verification_tokens",
        ["expires_at"],
    )

    op.create_table(
        "trusted_devices",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("device_secret_hash", sa.String(64), nullable=False),
        sa.Column("security_stamp", sa.String(64), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ip_hash", sa.String(64), nullable=True),
        sa.Column("last_user_agent_hash", sa.String(64), nullable=True),
        sa.Column("created_ip_hash", sa.String(64), nullable=True),
        sa.Column("created_user_agent_hash", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_trusted_devices_active_device_secret_hash",
        "trusted_devices",
        ["device_secret_hash"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_trusted_devices_user_revoked_expires",
        "trusted_devices",
        ["user_id", "revoked_at", "expires_at"],
    )

    bind = op.get_bind()
    role_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'echoroo_app'")
    ).scalar()
    if role_exists:
        op.execute("GRANT SELECT, UPDATE ON api_keys TO echoroo_app")
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON trusted_devices TO echoroo_app")
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON "
            "email_verification_tokens TO echoroo_app"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_trusted_devices_user_revoked_expires",
        table_name="trusted_devices",
    )
    op.drop_index(
        "ix_trusted_devices_active_device_secret_hash",
        table_name="trusted_devices",
    )
    op.drop_table("trusted_devices")

    op.drop_index(
        "ix_email_verification_tokens_expires_at",
        table_name="email_verification_tokens",
    )
    op.drop_index(
        "ix_email_verification_tokens_user_purpose_state_expires",
        table_name="email_verification_tokens",
    )
    op.drop_index(
        "ix_email_verification_tokens_active_user_purpose_email",
        table_name="email_verification_tokens",
    )
    op.drop_index(
        "ix_email_verification_tokens_active_token_hash",
        table_name="email_verification_tokens",
    )
    op.drop_table("email_verification_tokens")

    op.drop_column("users", "email_verified_at")
