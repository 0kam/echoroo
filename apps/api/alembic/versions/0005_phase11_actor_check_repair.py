"""Repair superuser_approval_requests actor columns / CHECK on legacy dev DBs.

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-28 00:00:00.000000

Round 2 review M3 + migration delta finding (2026-04-28)
========================================================

Background
----------
Phase 11 baseline migration (0001) was edited in-place during Round 1 to:

* add a second actor column ``requesting_user_id`` (UUID, FK ``users.id``
  ON DELETE SET NULL) so a regular project admin can be the actor
  recorded against a ``looser`` taxon override request — superusers
  approve, but the *requester* is the project admin;
* relax ``requested_by_id`` to nullable, since one or the other is set
  per row, never both;
* tighten the actor CHECK constraint
  ``ck_superuser_approval_requests_actor_present`` from "at least one"
  to **XOR** so both columns can never be filled simultaneously.

The 0001 edits work for *fresh* DBs that run ``alembic upgrade head``
from scratch, but existing dev databases that already applied 0001
through 0004 do not pick up the in-place 0001 changes — Alembic only
sees the head pointer move forward. This migration is the explicit
delta that brings any DB at HEAD=0004 into the same final shape as a
fresh DB at HEAD=0005.

Idempotency
-----------
Each step is guarded so a fresh DB (where 0001 already produced the
final shape) does not double-apply. We use:

* ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` for the new column — and
  add the FK + ON DELETE separately so we can ``IF NOT EXISTS`` the
  constraint name safely.
* ``ALTER COLUMN ... DROP NOT NULL`` is naturally idempotent (Postgres
  treats it as a no-op when the column is already nullable).
* The CHECK is dropped by name (``IF EXISTS``) and re-added with the
  XOR predicate.

Downgrade
---------
Reverts to the legacy 0004 shape: drop the FK, drop the column, restore
the original "at least one" CHECK predicate, and put ``requested_by_id``
back to NOT NULL. The downgrade is best-effort — if any rows have been
inserted with ``requesting_user_id`` populated and ``requested_by_id``
NULL, the NOT NULL restore will fail; operators must reconcile manually
before downgrading.
"""

from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = "0004"


def upgrade() -> None:
    # 1. Add requesting_user_id column (idempotent for fresh DBs).
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        ADD COLUMN IF NOT EXISTS requesting_user_id UUID NULL
        """
    )

    # 2. Add the FK separately so we can name it and IF-NOT-EXISTS
    #    cleanly. Postgres has no ``ADD CONSTRAINT IF NOT EXISTS`` for
    #    FKs, so we wrap in a DO block that checks pg_constraint first.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_superuser_approval_requests_requesting_user_id'
            ) THEN
                ALTER TABLE superuser_approval_requests
                ADD CONSTRAINT fk_superuser_approval_requests_requesting_user_id
                FOREIGN KEY (requesting_user_id)
                REFERENCES users(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """
    )

    # 3. Relax requested_by_id to nullable — Postgres no-ops when the
    #    column is already nullable on a fresh-DB install.
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        ALTER COLUMN requested_by_id DROP NOT NULL
        """
    )

    # 4. Replace the actor CHECK with the XOR predicate. Drop by name
    #    (idempotent via IF EXISTS) and re-add. We keep the same
    #    constraint name so application code referring to the constraint
    #    by name (e.g. error matchers) continues to work.
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        DROP CONSTRAINT IF EXISTS ck_superuser_approval_requests_actor_present
        """
    )
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        ADD CONSTRAINT ck_superuser_approval_requests_actor_present
        CHECK (
            (requested_by_id IS NOT NULL) <> (requesting_user_id IS NOT NULL)
        )
        """
    )


def downgrade() -> None:
    # Reverse order: re-impose the NOT NULL on requested_by_id, restore
    # the looser CHECK, drop the FK + column.
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        DROP CONSTRAINT IF EXISTS ck_superuser_approval_requests_actor_present
        """
    )
    # Best-effort restore: if any rows have requested_by_id NULL the
    # ALTER will fail. Operators must reconcile before downgrading.
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        ALTER COLUMN requested_by_id SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        ADD CONSTRAINT ck_superuser_approval_requests_actor_present
        CHECK (requested_by_id IS NOT NULL OR requesting_user_id IS NOT NULL)
        """
    )
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        DROP CONSTRAINT IF EXISTS fk_superuser_approval_requests_requesting_user_id
        """
    )
    op.execute(
        """
        ALTER TABLE superuser_approval_requests
        DROP COLUMN IF EXISTS requesting_user_id
        """
    )
