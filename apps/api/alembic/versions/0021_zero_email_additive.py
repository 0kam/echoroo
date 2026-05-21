"""Zero-email Phase 1 additive schema changes (spec/011 step 1).

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-21

Adds the additive schema surface required by spec/011 zero-email
deployment, Phase A (Implementation Phasing Step 1). This migration is
intentionally **additive only** — no existing column / table is dropped
or altered in place. The corresponding destructive removals
(``email_verification_tokens`` table, ``password_reset_tokens`` table,
``users.email_verified_at`` column) ship in a later forward-only
migration ``0022_email_subsystem_removal`` once every reader has been
rewritten.

Changes:

* ``users.must_change_password`` (BOOL NOT NULL DEFAULT false) —
  forced-password-change gate flipped on by
  ``services/admin_password_reset.reset_password`` (FR-011-203).
* ``users.temp_password_expires_at`` (TIMESTAMPTZ NULL) — wall-clock
  expiry of the temporary password issued by the admin reset flow
  (FR-011-203). Always paired with ``must_change_password``.
* ``users.email_change_cooldown_until`` (TIMESTAMPTZ NULL) — 24h
  cool-off after a successful ``change_email`` (FR-011-305).
* ``project_invitations.ownership_transfer_on_accept`` (BOOL NOT NULL
  DEFAULT false) — superuser-bootstrapped invitations that perform
  ownership transfer on acceptance (FR-011-121 / FR-011-122).
* CHECK ``ck_project_invitations_ownership_transfer_kind_member``:
  ownership transfer is only ever paired with ``kind = 'member'``
  invitations (defence-in-depth against bad service-layer callers).
* New table ``user_banner_dismissals`` for in-app banner dismissal
  state, polymorphic over ``project_audit_log`` and
  ``platform_audit_log`` (FR-011-301). No FK on ``audit_log_id`` —
  PostgreSQL does not support polymorphic foreign keys, so the integrity
  invariant lives in ``services/user_banner.py``. No secondary index
  on ``user_id`` is created: the composite primary key
  ``(user_id, audit_table, audit_log_id)`` is already a leading-column
  prefix on ``user_id``, so PostgreSQL can serve "list dismissals for
  this user" via the PK btree (see data-model.md §
  ``user_banner_dismissals`` "composite PK is sufficient").

The ``downgrade`` is intentionally not implemented: spec/011 NFR-011-002
mandates forward-only migrations.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # --- users: forced-password-change + email-change cooldown ---------
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "temp_password_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_change_cooldown_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # --- project_invitations: ownership transfer on accept -------------
    op.add_column(
        "project_invitations",
        sa.Column(
            "ownership_transfer_on_accept",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_check_constraint(
        "ck_project_invitations_ownership_transfer_kind_member",
        "project_invitations",
        "ownership_transfer_on_accept = false OR kind = 'member'",
    )

    # --- user_banner_dismissals (new table) ----------------------------
    op.create_table(
        "user_banner_dismissals",
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_table", sa.Text(), nullable=False),
        sa.Column("audit_log_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "audit_table",
            "audit_log_id",
            name="pk_user_banner_dismissals",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
            name="fk_user_banner_dismissals_user_id",
        ),
        sa.CheckConstraint(
            "audit_table IN ('project_audit_log', 'platform_audit_log')",
            name="ck_user_banner_dismissals_audit_table",
        ),
    )
    # No secondary ``user_id`` index — the composite PK already covers
    # both the exact-match path AND the leading-column prefix scan for
    # "list dismissals for this user" (data-model.md is explicit:
    # "the composite PK is sufficient").


def downgrade() -> None:
    raise NotImplementedError(
        "Forward-only migration per spec/011 NFR-011-002."
    )
