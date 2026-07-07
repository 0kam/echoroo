"""First-class ``run_type`` discriminator on ``detection_runs``.

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-07

W1-4: replace the fragile client-side heuristic (``parameters->embedding_only``
plus ``model_name`` allowlists) with a NOT NULL ``run_type`` enum on
``detection_runs``. The three run kinds are:

- ``detection``: species-detection runs that write annotations (BirdNET, and
  any future non-embedding detector).
- ``embedding``: embedding-generation runs (Perch) for similarity search.
- ``custom``: custom-model (``custom_svm``) inference runs.

Backfill classifies existing rows in priority order (first match wins):

  1. ``parameters->>'embedding_only' = 'true'``           -> ``embedding``
  2. ``model_name = 'custom_svm'``                         -> ``custom``
  3. ``model_name = 'perch' AND annotation_count = 0``     -> ``embedding``
     (legacy Perch embedding rows predating the ``embedding_only`` flag;
     documented in ``MLAnalysisStatus.svelte``)
  4. everything else                                       -> ``detection``

The column is added nullable, backfilled, then set NOT NULL with a
``server_default`` of ``'detection'`` so any concurrently-created row (and any
future INSERT that omits the column) lands on a safe default.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_ENUM_NAME = "detectionruntype"
_ENUM_VALUES = ("detection", "embedding", "custom")


def upgrade() -> None:
    bind = op.get_bind()

    # Create the enum type (idempotent on a DB that somehow already has it).
    sa.Enum(*_ENUM_VALUES, name=_ENUM_NAME, create_type=True).create(
        bind, checkfirst=True
    )

    enum_type = sa.Enum(*_ENUM_VALUES, name=_ENUM_NAME, create_type=False)

    # Add nullable first so the backfill can populate every row before the
    # NOT NULL constraint is enforced.
    op.add_column(
        "detection_runs",
        sa.Column("run_type", enum_type, nullable=True),
    )

    # Backfill in priority order (first matching branch wins).
    op.execute(
        sa.text(
            """
            UPDATE detection_runs
            SET run_type = CASE
                WHEN parameters->>'embedding_only' = 'true' THEN 'embedding'
                WHEN model_name = 'custom_svm' THEN 'custom'
                WHEN model_name = 'perch' AND annotation_count = 0 THEN 'embedding'
                ELSE 'detection'
            END::detectionruntype
            WHERE run_type IS NULL
            """
        )
    )

    # Enforce NOT NULL with a server-side default for future safety.
    op.alter_column(
        "detection_runs",
        "run_type",
        existing_type=enum_type,
        nullable=False,
        server_default="detection",
    )

    op.create_index(
        "ix_detection_runs_project_id_run_type",
        "detection_runs",
        ["project_id", "run_type"],
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index(
        "ix_detection_runs_project_id_run_type",
        table_name="detection_runs",
    )
    op.drop_column("detection_runs", "run_type")

    sa.Enum(name=_ENUM_NAME).drop(bind, checkfirst=True)
