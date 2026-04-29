"""Phase 13 P1 R2 致命 #1: enforce ``system_settings.updated_by_id IS NOT NULL``.

Revision ID: 0006b
Revises: 0006a
Create Date: 2026-04-28 00:00:02.000000

The canonical schema in ``specs/006-permissions-redesign/data-model.md`` §3.19
declares ``updated_by_id`` as ``Mapped[UUID]`` with ``nullable=False``. The
Phase 13 P1 baseline (``0001``) historically left the column nullable so the
migration could seed boot-time defaults before any superuser existed; the seed
rows were inserted with ``updated_by_id = NULL`` and were intended to be
back-filled by the bootstrap superuser-creation script.

Codex Phase 13 P1 R1 review (commit ``23762f78``) called out the resulting
three-way drift:

* spec / inventory:  NOT NULL
* baseline DDL:      nullable
* seed rows:         NULL

This migration reconciles the live DB to the canonical NOT NULL contract:

1. The orphan boot-time defaults (rows with ``updated_by_id IS NULL``) are
   removed wholesale. None of these settings are read by any code path —
   future writers will recreate them with a valid ``superusers.id`` on first
   write — and unique-key collisions are avoided because the keys are
   compound (``key`` PK).
2. Any rows that **do** carry a non-null FK survive untouched (they came
   from a fully-bootstrapped install).
3. The column is altered to ``SET NOT NULL``.

Rationale for *deleting* rather than back-filling: the rows seeded by the
baseline have never been read in production (FR-094 / NFR-006 readers
default to spec-canonical values via ``get_value(default=…)``), and there is
no surrogate ``superusers.id`` value safe to invent — superusers must be
real users. A first write from the admin UI will recreate the rows with a
valid FK at runtime.

Companion code changes in this commit:

* ``echoroo/models/system.py``    — ``Mapped[UUID]`` + ``nullable=False``.
* ``alembic/versions/0001_baseline_permissions_redesign.py`` — DDL
  ``nullable=False`` + seed block removed.
* ``echoroo/middleware/auth.py``   — ``_stamp_superuser_status`` also stamps
  ``user._superuser_id``.
* ``echoroo/api/v1/admin.py``      — settings PATCH passes
  ``current_user._superuser_id`` to the service.
* ``echoroo/repositories/system.py`` — ``updated_by_id`` is required.
* ``apps/api/tests/conftest.py``   — cleanup deletes rows instead of nulling.

There is no downgrade for the data-loss step (we cannot reconstruct which
rows were originally NULL). The downgrade therefore only relaxes the
constraint back to ``DROP NOT NULL`` so a roll-back leaves the schema in the
nullable state baseline ``0001`` historically produced.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0006b"
down_revision: str | None = "0006a"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Drop NULL rows then enforce NOT NULL on ``updated_by_id``."""

    # Step 1: delete any orphan boot-time defaults that still carry
    # ``updated_by_id = NULL``. These exist only on dev databases that were
    # bootstrapped under the historical (nullable) baseline.
    op.execute(
        sa.text(
            "DELETE FROM system_settings WHERE updated_by_id IS NULL"
        )
    )

    # Step 2: enforce the NOT NULL contract canonically.
    op.alter_column(
        "system_settings",
        "updated_by_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )


def downgrade() -> None:
    """Relax the NOT NULL constraint (data is *not* restored)."""

    op.alter_column(
        "system_settings",
        "updated_by_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )
