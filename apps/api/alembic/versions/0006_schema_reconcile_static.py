"""Phase 13 P0a / P1: schema reconcile (ORM-only tables + 16 new enums + detections).

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-28 00:00:00.000000

This migration is the **static** product of Phase 13's three-way diff between
``Base.metadata.tables`` and the live ``information_schema``. It performs the
following idempotent operations to bring the live database in line with the
ORM canonical schema **without** disturbing the existing rows in the 19
already-common tables (which Phase 13 P1.5 reconciles separately):

1. Create the 16 ORM-only PostgreSQL ``ENUM`` types that the ORM-only tables
   need to reference (per the v5-final plan §0.2 & §2.1, names match the
   ``Enum(name=...)`` parameter on each ``mapped_column`` exactly). The
   ``setting_type`` enum was retired in Phase 13 P1 (T803a) when
   ``system_settings.value`` switched to JSONB, so the count dropped from
   17 → 16.
2. Create the 32 ORM-only tables emitted directly by the ORM via
   ``Base.metadata`` (rendered once by ``scripts/gen_phase13_migration.py``;
   future ORM evolution must go into a new migration revision).
3. Re-emit ``detections`` (the only DB-only table that the ORM adopts as
   canonical in Phase 13) using ``CREATE TABLE IF NOT EXISTS`` so the live
   rows survive intact. Phase 14+ will rebind ``detections.taxon_id`` to a
   UUID FK to ``taxa.id``; the legacy stringified GBIF key column is
   preserved in this migration.

All ``CREATE TABLE`` and ``CREATE INDEX`` statements are guarded with
``IF NOT EXISTS`` so a fresh database that completes ``0001`` and replays
``0002..0009`` ends up in the same final shape as a long-lived dev database
that arrives at this revision starting from ``0005``.

The companion revision ``0006a`` (separate file, autocommit-required) widens
``detectionsource`` with the four new values.

Downgrade is a *partial* drop: only the ORM-only tables and the 16 ORM-only
enums are removed (the ``setting_type`` enum was retired in Phase 13 P1
T803a along with ``system_settings.value_type``, dropping the count from
17 to 16). ``detections`` is preserved on downgrade because its rows
predate this migration. A full schema teardown lives in ``scripts/wipe_database``.

Phase 13 inventory artifact: ``/tmp/phase13-inventory.md`` (T800).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from echoroo._alembic_phase13_supporting_ddl import (
    SUPPORTING_TABLES_REVERSE_DROP_ORDER,
    apply_phase13_supporting_tables,
)

# Revision identifiers used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# --------------------------------------------------------------------------- #
# Enum type definitions (Phase 13 P0a — 16 ORM-only enums after T803a)
# --------------------------------------------------------------------------- #
# Names MUST match the ``Enum(name=...)`` parameter on each ORM mapped column;
# see ``apps/api/echoroo/models/*.py``. The v5-final plan §0.2 captures the
# canonical snake_case names verified via the Phase 13 inventory (T800).
_PHASE13_ENUMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("datetimeparsestatus", ("pending", "success", "failed")),
    ("annotation_set_status", ("sampling", "ready", "in_progress", "completed")),
    ("annotation_segment_status", ("unannotated", "annotated", "skipped")),
    (
        "annotationtaskstatus",
        ("pending", "in_progress", "completed", "review_pending"),
    ),
    ("annotationprojectvisibility", ("private", "public")),
    ("reviewstatus", ("unreviewed", "approved", "rejected")),
    ("geometrytype", ("BoundingBox", "TimeInterval")),
    ("signalquality", ("solo", "dominant", "mixed")),
    (
        "consensusstatus",
        ("needs_votes", "agreed", "rejected", "disputed"),
    ),
    ("detectionrunstatus", ("pending", "running", "completed", "failed")),
    (
        "uploadsessionstatus",
        (
            "issued",
            "uploaded",
            "validating",
            "validated",
            "importing",
            "imported",
            "failed",
        ),
    ),
    (
        "uploadfilestatus",
        ("pending", "uploaded", "valid", "invalid", "imported"),
    ),
    ("searchsessionstatus", ("pending", "running", "completed", "failed")),
    # Phase 13 P1 (T803a): ``setting_type`` retired with ``system_settings.value_type``.
    ("votetype", ("agree", "disagree", "unsure")),
    (
        "custommodelstatus",
        ("draft", "training", "trained", "deployed", "failed", "archived"),
    ),
    (
        "evaluation_run_status",
        ("pending", "running", "completed", "failed"),
    ),
)


def _create_enums(enums: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    bind = op.get_bind()
    for name, values in enums:
        sa.Enum(*values, name=name, create_type=True).create(bind, checkfirst=True)


def _drop_enums(enums: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    bind = op.get_bind()
    for name, _ in enums:
        sa.Enum(name=name).drop(bind, checkfirst=True)


# --------------------------------------------------------------------------- #
# Upgrade
# --------------------------------------------------------------------------- #


def upgrade() -> None:  # noqa: PLR0915 — generated DDL block, long by nature
    # Ensure the legacy crypto extension exists for ``gen_random_uuid()``
    # (also called from baseline 0001; harmless if already present).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Phase 13 P0a: ensure pgvector is available for ``embeddings`` and
    # ``search_query_embeddings`` (VECTOR(1536) columns below). Without
    # this extension the CREATE TABLE statements fail on a fresh DB.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Step 1 — create the 16 ORM-only enum types
    # (Phase 13 P1 / T803a dropped ``setting_type``; see _PHASE13_ENUMS).
    _create_enums(_PHASE13_ENUMS)

    # Step 2 — emit the 32 ORM-only supporting tables + the canonical
    # ``detections`` table via the shared helper. The same helper is
    # invoked by 0001 so a fresh DB built from baseline alone reaches the
    # identical final shape without duplicating ~870 lines of DDL between
    # both revisions. All statements use ``CREATE TABLE/INDEX IF NOT EXISTS``
    # so existing dev DBs that arrive here at HEAD=0005 with the legacy
    # ``detections`` row data also converge on the same final shape.
    apply_phase13_supporting_tables()


# --------------------------------------------------------------------------- #
# Downgrade — drop ORM-only tables only; keep ``detections`` and the 16
# Phase 13 enums untouched if anything else still depends on them.
# --------------------------------------------------------------------------- #


def downgrade() -> None:
    for tname in SUPPORTING_TABLES_REVERSE_DROP_ORDER:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{tname}" CASCADE'))
    _drop_enums(_PHASE13_ENUMS)
