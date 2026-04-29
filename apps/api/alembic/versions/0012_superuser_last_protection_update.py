"""Phase 15 NO-GO C3: extend ``superuser_last_protection`` trigger to UPDATE.

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-28 00:00:00.000000

Background
==========
The original ``superuser_last_protection`` trigger
(:mod:`apps/api/alembic/versions/0001_baseline_permissions_redesign`,
``BEFORE DELETE`` only) blocked the ``echoroo_app`` connection from
issuing a hard ``DELETE FROM superusers`` against the last active row.

Phase 15 NO-GO Codex review found the gap: the application path never
issues ``DELETE`` — it soft-revokes by setting ``revoked_at = now()``.
The trigger therefore could not stop a runaway revoke from leaving zero
active superusers, breaking the FR-111a / FR-111 invariant ("≥ 3
active, never < 1 by application action").

This migration replaces the trigger function with a variant that also
fires on ``BEFORE UPDATE OF revoked_at``: when an UPDATE flips
``revoked_at`` from ``NULL`` to a timestamp AND the post-image active
count would be zero, the trigger raises. The DELETE branch is
preserved so legacy hard-delete paths (e.g. test fixtures) keep their
existing semantics.

The function still skips the rule for non-``echoroo_app`` connections
(``echoroo_migrator``, the postgres superuser) so baseline regen and
testcontainer teardown can drop superusers wholesale without touching
the override GUC.

Companion service-layer change
==============================
:mod:`echoroo.services.superuser_service.revoke_superuser_apply` now
takes a ``SELECT FOR UPDATE`` on the target row + raises
``LastSuperuserProtectionError`` when ``active_before <= 1``. The
two layers are intentional defence-in-depth: the trigger is the
authoritative block (it cannot be bypassed by future service callers
that forget the check), and the service exception keeps the API
response payload clean (avoids surfacing raw asyncpg ``RAISE``
strings).
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Replace the function so the BEFORE UPDATE trigger has the same
    # semantics as the BEFORE DELETE trigger. Using CREATE OR REPLACE
    # leaves the existing DELETE trigger pointing at the new body.
    op.execute(
        """
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
            -- from NULL → non-NULL (i.e. soft-revoke). Other UPDATEs on
            -- the row (key rotation, allowed_ip_cidrs edits, ...) are
            -- always permitted. ``OLD.revoked_at IS NULL`` is the
            -- discriminator: if the row is already revoked we never
            -- block (idempotent re-revoke).
            IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
                -- Compute the active count after this UPDATE applies.
                -- The current row hasn't committed yet, so subtract 1
                -- if OLD was active. NEW.revoked_at IS NOT NULL by
                -- construction.
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

    # Add the BEFORE UPDATE trigger pointing at the same function. The
    # original BEFORE DELETE trigger keeps its name + binding. asyncpg
    # rejects multi-command prepared statements, so split into two
    # ``op.execute`` calls.
    op.execute(
        "DROP TRIGGER IF EXISTS superuser_last_protection_update ON superusers"
    )
    op.execute(
        """
        CREATE TRIGGER superuser_last_protection_update
        BEFORE UPDATE OF revoked_at ON superusers
        FOR EACH ROW
        EXECUTE FUNCTION prevent_last_superuser_deletion()
        """
    )


def downgrade() -> None:
    # Drop the new trigger first, then restore the original DELETE-only
    # function body. The DELETE trigger keeps its existing binding.
    op.execute(
        "DROP TRIGGER IF EXISTS superuser_last_protection_update ON superusers"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_last_superuser_deletion()
        RETURNS trigger AS $$
        BEGIN
            IF current_user = 'echoroo_app' THEN
                IF (SELECT COUNT(*) FROM superusers WHERE revoked_at IS NULL) <= 1 THEN
                    IF current_setting('app.superuser_deletion_override', true)
                       IS DISTINCT FROM 'true' THEN
                        RAISE EXCEPTION
                          'Cannot delete last superuser without creator_founder override';
                    END IF;
                END IF;
            END IF;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
