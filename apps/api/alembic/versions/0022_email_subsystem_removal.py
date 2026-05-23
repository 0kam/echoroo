"""Email subsystem removal — destructive (spec/011 step 11).

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-23

Final destructive half of the spec/011 zero-email-deployment two-phase
migration plan. Step 1 (``0021_zero_email_additive``) introduced the
additive surface (``users.must_change_password`` /
``users.temp_password_expires_at`` / ``users.email_change_cooldown_until`` /
``project_invitations.ownership_transfer_on_accept`` /
``user_banner_dismissals``). Step 10 (PR #103 — see HANDOFF.md line 73)
removed every Python reader and writer of the email-subsystem objects
this migration now drops. The grep-based CI guard
``apps/api/tests/contract/test_no_email_subsystem_traces.py`` enforces
zero remaining references at HEAD (NFR-011-001).

Drops:

* ``email_verification_tokens`` table (FR-011-002 / FR-011-003) — the
  pending-verification token store seeded by ``0019_email_verification_
  trusted_devices``. All four supporting indexes
  (``ix_email_verification_tokens_active_token_hash``,
  ``ix_email_verification_tokens_active_user_purpose_email``,
  ``ix_email_verification_tokens_user_purpose_state_expires``,
  ``ix_email_verification_tokens_expires_at``) are dropped as part of
  the table drop — PostgreSQL ``DROP TABLE`` removes dependent indexes
  in one statement, so no explicit ``op.drop_index`` is required.
* ``password_reset_tokens`` table (FR-011-003) — the magic-link token
  store seeded by ``0003_password_reset_tokens``. Its two indexes
  (``ix_password_reset_tokens_token_hash``,
  ``ix_password_reset_tokens_user_expires``) are likewise dropped by
  cascade.
* ``users.email_verified_at`` column (FR-011-002) — added by
  ``0019_email_verification_trusted_devices``. Drop is unconditional;
  Step 10 removed the model field and every reader.

Out of scope for this migration (per HANDOFF.md line 73): the
``trusted_devices`` table introduced alongside ``email_verified_at`` in
``0019_*`` is NOT dropped here. Trusted devices remain operational
post-zero-email and have their own lifecycle.

Operator notes:

* Single-host docker compose deploys MAY apply this migration in the
  same ``stop → migrate → start`` window as ``0021`` once Step 10's
  reader removal is in production. Pre-verification: the
  NFR-011-001 grep guard (``test_no_email_subsystem_traces.py``) MUST
  be passing at HEAD before this migration is applied — that test
  enforces zero matches outside historical migrations.
* If a backup is required before the ``DROP``, take a logical DB dump
  (``pg_dump -t email_verification_tokens -t password_reset_tokens
  -t users``) before running ``alembic upgrade head``.
* ``downgrade()`` raises ``NotImplementedError`` per spec/011
  NFR-011-002 (forward-only). Restore from backup if rollback is
  required.
"""

from __future__ import annotations

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Drop email subsystem tables + column (FR-011-002..003)."""
    # 1. Drop ``email_verification_tokens`` table. PostgreSQL drops
    #    dependent indexes as part of the same statement.
    op.drop_table("email_verification_tokens")
    # 2. Drop ``password_reset_tokens`` table (same cascade rule).
    op.drop_table("password_reset_tokens")
    # 3. Drop ``users.email_verified_at`` column.
    op.drop_column("users", "email_verified_at")


def downgrade() -> None:
    """Forward-only per spec/011 NFR-011-002."""
    raise NotImplementedError(
        "Migration 0022 is forward-only per spec/011 NFR-011-002. "
        "Email subsystem removal is irreversible — restore from backup "
        "if rollback is required."
    )
