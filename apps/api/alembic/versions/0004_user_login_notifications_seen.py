"""Track recent (IP, UA) tuples per user for new-device login notifications.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-25 00:00:00.000000

Backs :class:`echoroo.models.UserLoginNotificationSeen`. The
:class:`echoroo.services.login_notification_service.LoginNotificationService`
upserts one row per unique (user_id, ip_hash, ua_hash) seen in the last
30 days. The hashes are HMAC-SHA256 outputs from
:func:`echoroo.core.kms.compute_pii_hash`, so a database leak cannot be
mined for real IP / UA strings — the HMAC key lives only inside KMS
(FR-091, FR-091b).

A periodic janitor (Phase 3 follow-up) drops rows whose ``last_seen_at``
is older than 30 days so the table does not grow without bound. The
unique constraint keeps the upsert path correct even if two parallel
logins for the same tuple race — the second one becomes a fast NOOP.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = "0003"


def upgrade() -> None:
    op.create_table(
        "user_login_notifications_seen",
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
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("ua_hash", sa.String(64), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "ip_hash",
            "ua_hash",
            name="uq_user_login_notifications_seen_tuple",
        ),
    )
    # Composite index on (user_id, last_seen_at) — the canonical query
    # pattern is ``WHERE user_id = ? AND last_seen_at > retention_cutoff``
    # (see :class:`LoginNotificationService._fetch_recent_seen`). A
    # composite left-anchored index serves both the ``user_id`` equality
    # filter (left prefix) AND the ``last_seen_at`` range filter as a
    # single index scan, removing the need for a separate single-column
    # index on ``user_id`` (which would be redundant for any query
    # touching the prefix). The single ``last_seen_at`` index is also
    # dropped because the service never queries on ``last_seen_at``
    # without also constraining ``user_id``.
    op.create_index(
        "ix_user_login_notifications_seen_user_id_last_seen_at",
        "user_login_notifications_seen",
        ["user_id", "last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_login_notifications_seen_user_id_last_seen_at",
        table_name="user_login_notifications_seen",
    )
    op.drop_table("user_login_notifications_seen")
