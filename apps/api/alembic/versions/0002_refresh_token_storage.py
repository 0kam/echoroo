"""Refresh-token storage tables for SqlTokenStore (Phase 2.11 P0-d).

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25 00:00:00.000000

Adds two tables that back :class:`echoroo.core.auth.SqlTokenStore`:

* ``token_families``  — one row per refresh-token family. ``revoked_at``
  flips when the family is killed (logout-all, replay detection, etc.).
* ``refresh_tokens``  — one row per individual refresh token (jti).
  ``consumed_at`` flips when the token is rotated. The atomic-rotate
  primitive (``UPDATE ... WHERE consumed_at IS NULL RETURNING jti``)
  uses PostgreSQL's row-level lock to guarantee only one rotation
  succeeds per token, even under concurrent attempts.

Schema choices (data-model §3.1, research §auth):

* ``family_id`` is a UUID rather than a FK NULL fallback so the
  Phase-3 wiring can plant a family without first having to write the
  user's row. The (family_id, jti) UNIQUE constraint is the index used
  by atomic_consume_and_issue to short-circuit duplicate inserts.
* (user_id, family_id) compound index supports the "list all my
  outstanding sessions" admin UI and fast family-revoke updates.
* expires_at is indexed because the cleanup job (Phase 3) walks the
  expired half of the table.

The migration is intentionally additive: the ``0001`` baseline is NOT
modified. Downgrade drops both tables and is safe because ``0001`` has
no FKs into them.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = "0001"


def upgrade() -> None:
    # token_families: revocation marker for a chain of rotated refresh tokens.
    op.create_table(
        "token_families",
        sa.Column(
            "family_id",
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_token_families_user_id", "token_families", ["user_id"])
    op.create_index(
        "ix_token_families_revoked_at", "token_families", ["revoked_at"]
    )

    # refresh_tokens: one row per individual refresh JWT (identified by jti).
    op.create_table(
        "refresh_tokens",
        sa.Column("jti", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "family_id",
            UUID(as_uuid=True),
            sa.ForeignKey("token_families.family_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_refresh_tokens_user_family",
        "refresh_tokens",
        ["user_id", "family_id"],
    )
    op.create_index(
        "ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"]
    )
    op.create_index(
        "ix_refresh_tokens_consumed_at",
        "refresh_tokens",
        ["consumed_at"],
        postgresql_where=sa.text("consumed_at IS NULL"),
    )
    # The atomic rotate primitive uses (family_id, jti) for fast lookup;
    # PRIMARY KEY on (jti) covers single-row reads but family-scoped
    # queries (revoke all in family) need the compound index.
    op.create_index(
        "ix_refresh_tokens_family_jti",
        "refresh_tokens",
        ["family_id", "jti"],
        unique=True,
    )


def downgrade() -> None:
    # Reverse FK dependency order: refresh_tokens references token_families.
    op.drop_index("ix_refresh_tokens_family_jti", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_consumed_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_family", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_token_families_revoked_at", table_name="token_families")
    op.drop_index("ix_token_families_user_id", table_name="token_families")
    op.drop_table("token_families")
