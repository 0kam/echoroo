"""Phase 17 backlog A-11 Round-2 Fix-2: stale ``dispatching`` reclaim column.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-04 12:00:00.000000

Background
==========
Round-1 review (Codex) flagged a permanent-stuck-state bug in the
2FA reset dispatch poller:

* ``run_dispatch_due_requests`` flips a row to ``dispatching`` and
  commits BEFORE calling :meth:`TwoFactorService.reset_user_two_factor`.
* If the worker process crashes mid-reset, the row stays in
  ``dispatching`` forever — the partial unique index
  ``ux_two_factor_reset_requests_active_user`` includes
  ``dispatching`` in its ``WHERE`` clause, so the user can never have
  a fresh reset request opened either.

Fix design (case A — minimal):
We add a new nullable ``dispatching_started_at`` column. The poller
sets it whenever it transitions a row to ``dispatching``. A sweep
step at the start of each beat tick reverts any
``dispatching`` row whose ``dispatching_started_at`` is older than
``DISPATCH_RECLAIM_TIMEOUT`` (5 minutes) back to ``pending_delay`` so
it can be re-claimed on the next tick.

The partial unique index keeps ``dispatching`` in its ``WHERE`` set
(unchanged) — the sweep ensures the row does not stay in that
status long enough for the index to lock out future requests
unnecessarily.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "two_factor_reset_requests",
        sa.Column(
            "dispatching_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Helper index for the sweep query — narrow partial index keyed on
    # the only status the sweep cares about.
    op.create_index(
        "ix_two_factor_reset_requests_dispatching_started",
        "two_factor_reset_requests",
        ["dispatching_started_at"],
        postgresql_where=sa.text("status = 'dispatching'"),
    )
    # Round-7 Fix (Codex Major→close follow-up): no additional GRANT is
    # required here. ``ADD COLUMN`` inherits the table's existing
    # privileges (PostgreSQL applies INSERT/UPDATE/DELETE at the table
    # level — column-level GRANTs are an additional restriction layer,
    # not a relaxation), and the new index does not require a separate
    # GRANT (indexes are not first-class privilege objects in
    # PostgreSQL). The table-level GRANTs added in
    # ``0014_two_factor_reset_requests.upgrade()`` already cover
    # reads/writes to ``dispatching_started_at`` from the
    # ``echoroo_app`` runtime role.


def downgrade() -> None:
    op.drop_index(
        "ix_two_factor_reset_requests_dispatching_started",
        table_name="two_factor_reset_requests",
    )
    op.drop_column("two_factor_reset_requests", "dispatching_started_at")
