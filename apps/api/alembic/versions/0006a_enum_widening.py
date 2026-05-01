"""Phase 13 P0b: widen ``detectionsource`` with the four new ML/sampling values.

Revision ID: 0006a
Revises: 0006
Create Date: 2026-04-28 00:00:01.000000

PostgreSQL ``ALTER TYPE ... ADD VALUE`` cannot run inside a transaction
block (since PG 12 it is allowed in a transaction *only* if the value is not
referenced in the same transaction). Alembic exposes
``op.get_context().autocommit_block()`` for exactly this case — we use it to
add the four new ``detectionsource`` enum members:

- ``perch``               (Perch ML detector)
- ``similarity_search``   (vector similarity search)
- ``custom_svm``          (per-project SVM custom classifier)
- ``sampling_round``      (active learning / seed sampling pipeline)

Each ``ADD VALUE`` is guarded with ``IF NOT EXISTS`` so the migration is
idempotent across replays. There is **no downgrade**: PostgreSQL has no
``DROP VALUE`` operation, so the ``downgrade()`` step is a deliberate no-op.

The widening is split into its own revision (separate from 0006) because:

* enum value addition cannot share a transaction with the rest of 0006;
* a future migration (Phase 13 P3+) may want to depend on the new values
  for a CHECK constraint or DML, which is forbidden in the same transaction
  that added them.

See ``/tmp/plan-merged-v5-final.md`` §0.3 for the rationale.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0006a"
down_revision: str | None = "0006"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


_NEW_DETECTIONSOURCE_VALUES: tuple[str, ...] = (
    "perch",
    "similarity_search",
    "custom_svm",
    "sampling_round",
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in _NEW_DETECTIONSOURCE_VALUES:
            op.execute(
                f"ALTER TYPE detectionsource ADD VALUE IF NOT EXISTS '{value}'"
            )


def downgrade() -> None:
    """No-op: PostgreSQL does not support ``ALTER TYPE ... DROP VALUE``."""

    return None
