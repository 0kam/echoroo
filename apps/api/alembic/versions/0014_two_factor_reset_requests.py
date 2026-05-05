"""Phase 17 backlog A-11: 2FA reset state machine + magic-link nonce table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-04 00:00:00.000000

Background
==========
``PHASE17_BACKLOG.md`` item A-11 promises a documented, audited support
workflow for clearing a user's 2FA enrolment when they cannot supply
their TOTP / backup codes (FR-072). The workflow has four moving parts:

1. **4-factor identity verification** — implemented via a magic-link
   email confirmation handed to the support agent who is operating on
   behalf of the user.
2. **24h delayed dispatch** — a Celery beat poller picks up rows where
   ``dispatch_at <= now()`` and the user has not unlocked themselves in
   the meantime.
3. **72h cooldown state machine** — a partial unique index on
   ``two_factor_reset_requests`` prevents a second pending request for
   the same user; once the dispatch lands, the existing
   ``users.two_factor_reset_cooldown_until`` column gates further
   logins / password resets for 72h.
4. **``skip_delay`` quorum** — opens a ``superuser_approval_requests``
   row with action ``two_factor_reset.skip_delay`` and only flips the
   ``two_factor_reset_requests`` row to ``approved`` (with
   ``dispatch_at = now()``) when two co-signing superusers approve.

Tables created
==============
* ``two_factor_reset_requests`` — the canonical state-machine row. One
  row per support ticket. The unique partial index guarantees there is
  at most one *in-flight* row per user; after the request reaches a
  terminal state (``applied`` / ``expired`` / ``cancelled`` / ``failed``)
  the row stays in place for forensics but no longer blocks new
  requests.
* ``two_factor_confirmation_tokens`` — the nonce store for the
  magic-link → confirmation-token handshake. Each row carries the
  token's HMAC nonce and a single-use ``used_at`` column updated under
  ``UPDATE ... WHERE used_at IS NULL RETURNING`` so concurrent reuse of
  the same nonce is impossible.
* ``two_factor_reset_magic_links`` — short-lived magic-link tokens
  emailed to the user. Each row holds a ``token_hash`` (SHA-256 of the
  raw token) and a ``redeemed_at`` column. The handshake row is
  consumed atomically when the user clicks the link.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # two_factor_reset_magic_links
    # ------------------------------------------------------------------
    # Mirror of ``password_reset_tokens`` so the operational shape is
    # familiar: (token_hash, expires_at, redeemed_at). The hash column is
    # SHA-256 hex of the raw token (64 chars) so an attacker with read
    # access to the table cannot recover the token.
    op.create_table(
        "two_factor_reset_magic_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", sa.String(length=45), nullable=True),
        sa.Column("requested_user_agent", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_two_factor_reset_magic_links_user_expires",
        "two_factor_reset_magic_links",
        ["user_id", "expires_at"],
    )

    # ------------------------------------------------------------------
    # two_factor_confirmation_tokens
    # ------------------------------------------------------------------
    # Nonce store for the short-lived (5min) confirmation token issued
    # after a successful magic-link redeem. The token itself is an HMAC
    # over the (user_id, purpose, expires_at, nonce) tuple — the nonce
    # column here is the one-time-use guard. ``used_at`` is updated
    # under an atomic ``UPDATE ... WHERE used_at IS NULL RETURNING``
    # statement so the second redeem fails closed.
    op.create_table(
        "two_factor_confirmation_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nonce", sa.String(length=64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_two_factor_confirmation_tokens_user_purpose_expires",
        "two_factor_confirmation_tokens",
        ["user_id", "purpose", "expires_at"],
    )

    # ------------------------------------------------------------------
    # two_factor_reset_requests
    # ------------------------------------------------------------------
    # Canonical state machine row for the 2FA reset workflow. ``status``
    # is intentionally a free-form ``VARCHAR`` (instead of an enum) so
    # we can extend the state machine in subsequent phases without
    # paying the ``ALTER TYPE ... ADD VALUE`` migration cost. The CHECK
    # constraint pins the current state names so a bug that writes a
    # bogus literal cannot land silently.
    op.create_table(
        "two_factor_reset_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_superuser_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("superusers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("support_ticket_id", sa.String(length=200), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "skip_delay",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("dispatch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_token_nonce", sa.String(length=64), nullable=False),
        sa.Column(
            "approval_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("superuser_approval_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('pending_delay','pending_approval','approved',"
            "'dispatching','applied','expired','cancelled','failed')",
            name="ck_two_factor_reset_requests_status",
        ),
    )

    # In-flight pending exclusion. Any of {pending_delay, pending_approval,
    # approved, dispatching} blocks a second request for the same user.
    op.create_index(
        "ux_two_factor_reset_requests_active_user",
        "two_factor_reset_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending_delay','pending_approval','approved','dispatching')"
        ),
    )
    # Beat poller scan helper — surfaces dispatchable rows in order.
    op.create_index(
        "ix_two_factor_reset_requests_dispatch_at",
        "two_factor_reset_requests",
        ["status", "dispatch_at"],
    )

    # ------------------------------------------------------------------ #
    # Round-7 Fix (Codex Major→close follow-up): explicit GRANT to the
    # ``echoroo_app`` runtime role.
    #
    # Rationale
    # ---------
    # Migrations run as the table owner (typically ``postgres`` /
    # ``echoroo`` superuser), but the FastAPI / Celery workers connect
    # as ``echoroo_app`` in environments that follow the
    # 0001-baseline-permissions-redesign convention (CI, staging,
    # prod). Without an explicit GRANT, the app role cannot SELECT /
    # INSERT / UPDATE / DELETE on the three new 2FA-reset tables and
    # the entire support workflow fails at runtime with a
    # ``permission denied for table ...`` error.
    #
    # We follow the established conditional GRANT pattern from
    # ``0001_baseline_permissions_redesign`` (T020f, line 1294-1320):
    # only emit the GRANTs when the role actually exists, so local
    # dev / testcontainers runs that connect as the table owner do
    # not fail with ``role does not exist``. The ``id`` PK uses
    # ``gen_random_uuid()`` (no sequence) so no ``GRANT USAGE ON
    # SEQUENCE`` is required for these tables.
    bind = op.get_bind()
    role_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = 'echoroo_app'")
    ).scalar()
    if role_exists:
        # asyncpg cannot execute multiple statements in a single
        # prepared statement — split into individual op.execute() calls
        # so the migration runs under both psycopg2 and asyncpg drivers
        # (same constraint as 0001 / 0012 / 0013).
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON "
            "two_factor_reset_magic_links TO echoroo_app"
        )
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON "
            "two_factor_confirmation_tokens TO echoroo_app"
        )
        op.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON "
            "two_factor_reset_requests TO echoroo_app"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_two_factor_reset_requests_dispatch_at",
        table_name="two_factor_reset_requests",
    )
    op.drop_index(
        "ux_two_factor_reset_requests_active_user",
        table_name="two_factor_reset_requests",
    )
    op.drop_table("two_factor_reset_requests")

    op.drop_index(
        "ix_two_factor_confirmation_tokens_user_purpose_expires",
        table_name="two_factor_confirmation_tokens",
    )
    op.drop_table("two_factor_confirmation_tokens")

    op.drop_index(
        "ix_two_factor_reset_magic_links_user_expires",
        table_name="two_factor_reset_magic_links",
    )
    op.drop_table("two_factor_reset_magic_links")
