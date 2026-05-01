"""Phase 15 R3 NO-GO C3: serialise concurrent revoke applies via advisory lock.

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-28 00:00:00.000000

Background
==========
Migration ``0012`` added the BEFORE UPDATE branch of
:func:`prevent_last_superuser_deletion` to block soft-revokes that would
leave zero active superusers. The Codex re-review of commit
``f4b2c85c`` found that the BEFORE UPDATE row trigger only locks the
*target* row: two concurrent transactions revoking *different* targets
both observe ``COUNT(*) - 1 = 1`` (the surviving sibling) and pass the
guard, then commit and leave zero active rows.

This migration replaces the function body with a variant that takes a
deterministic ``pg_advisory_xact_lock(<constant 64-bit key>)`` BEFORE
the active-count probe. Any concurrent UPDATE that flips
``revoked_at NULL → non-NULL`` will queue behind the lock; the second
transaction therefore sees the post-image of the first commit and the
``active_after < 1`` branch fires. The lock is released automatically
when the transaction commits or rolls back (``_xact_`` variant).

The constant key derives from ``SHA-256("superuser_last_protection")``
folded into a 63-bit positive integer to avoid sign-extension surprises
across drivers (mirrors the convention in
:mod:`echoroo.services.audit_service` and
:mod:`echoroo.services.ownership_service`).

Phase 13 P5 9-axis parity
=========================
Axis 8 (``pg_trigger``) compares ``pg_get_triggerdef`` output, which
contains only the ``CREATE TRIGGER ...`` statement, not the function
body. Trigger DDL is unchanged here, so fresh + upgraded paths still
agree on every axis. The function body itself is replaced by both
paths during the alembic chain, so the runtime behaviour matches.
"""

from __future__ import annotations

import hashlib

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# Deterministic advisory-lock key. Folded into the 63-bit positive
# range so PostgreSQL clients that surface bigint as signed Python int
# never accidentally negate it.
_LOCK_KEY: int = (
    int.from_bytes(
        hashlib.sha256(b"superuser_last_protection").digest()[:8], "big"
    )
    & 0x7FFFFFFFFFFFFFFF
)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION prevent_last_superuser_deletion()
        RETURNS trigger AS $$
        DECLARE
            active_after INTEGER;
        BEGIN
            -- Only the application connection is gated; baseline /
            -- migration roles fall through unchanged.
            IF current_user <> 'echoroo_app' THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;

            IF TG_OP = 'DELETE' THEN
                -- Phase 15 R3 NO-GO C3: serialise the active-count probe.
                -- Concurrent DELETEs against distinct rows would otherwise
                -- both observe ``COUNT(*) <= 1`` for the surviving siblings.
                PERFORM pg_advisory_xact_lock({_LOCK_KEY});
                IF (SELECT COUNT(*) FROM superusers WHERE revoked_at IS NULL) <= 1 THEN
                    IF current_setting('app.superuser_deletion_override', true)
                       IS DISTINCT FROM 'true' THEN
                        RAISE EXCEPTION
                          'Cannot delete last superuser without creator_founder override';
                    END IF;
                END IF;
                RETURN OLD;
            END IF;

            -- BEFORE UPDATE OF revoked_at branch (Phase 15 NO-GO C3).
            -- Only fire when the UPDATE actually transitions revoked_at
            -- from NULL → non-NULL (i.e. soft-revoke).
            IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
                -- Phase 15 R3 NO-GO C3: take the global advisory lock so
                -- two concurrent revoke transactions targeting *different*
                -- rows still serialise on the active-count probe. Without
                -- this, BOTH would compute ``COUNT(*) - 1 = 1`` from the
                -- pre-image of their sibling and pass the guard, leaving
                -- zero active superusers after both commits.
                PERFORM pg_advisory_xact_lock({_LOCK_KEY});

                SELECT COUNT(*) - 1 INTO active_after
                FROM superusers
                WHERE revoked_at IS NULL;

                IF active_after < 1 THEN
                    IF current_setting('app.superuser_deletion_override', true)
                       IS DISTINCT FROM 'true' THEN
                        RAISE EXCEPTION
                          'Cannot revoke last superuser without creator_founder override';
                    END IF;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    # Restore the 0012 function body (no advisory lock).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_last_superuser_deletion()
        RETURNS trigger AS $$
        DECLARE
            active_after INTEGER;
        BEGIN
            IF current_user <> 'echoroo_app' THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;

            IF TG_OP = 'DELETE' THEN
                IF (SELECT COUNT(*) FROM superusers WHERE revoked_at IS NULL) <= 1 THEN
                    IF current_setting('app.superuser_deletion_override', true)
                       IS DISTINCT FROM 'true' THEN
                        RAISE EXCEPTION
                          'Cannot delete last superuser without creator_founder override';
                    END IF;
                END IF;
                RETURN OLD;
            END IF;

            IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
                SELECT COUNT(*) - 1 INTO active_after
                FROM superusers
                WHERE revoked_at IS NULL;

                IF active_after < 1 THEN
                    IF current_setting('app.superuser_deletion_override', true)
                       IS DISTINCT FROM 'true' THEN
                        RAISE EXCEPTION
                          'Cannot revoke last superuser without creator_founder override';
                    END IF;
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
