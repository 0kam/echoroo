"""Add taxon identity history and taxon concept relations.

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-23

WS-A v2 slice 5. Slice 3 (revision 0035) gave every taxon a re-matchable
Catalogue of Life XR identity, but a re-resolution simply OVERWRITES it: a
status flip ``ACCEPTED`` -> ``SYNONYM``, a new accepted name, or a cleared
identity after a release bump all left no trace. This revision adds the two
tables that make those rewrites explainable.

1. ``taxon_identity_history`` — append-only journal, one row per changed
   identity field of one taxon (old value, new value, source, resolver, the
   COL release it was pinned to, and the actor). It is written in the SAME
   transaction as the ``taxa`` UPDATE that caused it, so the COL XR batch's
   chunk commits bank the new identity and its journal together. It is
   deliberately NOT the platform audit log: that needs a fresh SERIALIZABLE
   session plus a global advisory lock per row, which would serialize a
   6,500-row resolution pass.

   ``ck_taxon_identity_history_actual_change`` makes "an identical
   re-resolution writes no history" a database invariant rather than a
   convention, and ``ck_taxon_identity_history_actor_present`` makes
   attribution mandatory in whichever shape ``actor_kind`` promises.

2. ``taxon_concept_relations`` — directed edges recording where a concept
   WENT (``synonym_of`` today; ``lumped_into`` / ``split_into`` /
   ``renamed_to`` reserved). The target is keyed by the COL usage key
   (``to_col_xr_id``), NOT by a local FK: on the real dev catalogue all 302
   synonym targets are usages that do not exist as any local
   ``taxa.col_xr_id`` (e.g. ``Accipiter badius`` -> ``CVWCS Tachyspiza
   badia``). ``to_taxon_id`` is therefore nullable and filled in later,
   idempotently, by ``relink_concept_relations`` if the accepted concept is
   ever added locally.

The ``upgrade()`` also performs a ONE-TIME backfill of the ``synonym_of``
edges implied by the identities slice 3 already resolved. No history is
backfilled: the overwritten values no longer exist anywhere.

Fully reversible: ``downgrade()`` drops both tables (and, with them, the
backfilled edges).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

HISTORY_TABLE = "taxon_identity_history"
RELATIONS_TABLE = "taxon_concept_relations"

#: ``(name, type, nullable, fk_target, fk_ondelete)`` in creation order.
#: ``fk_target`` is ``None`` for plain columns. Mirrors 0035's module-level
#: tuple layout so the shape is reviewable in one place.
_ColumnSpec = tuple[str, "sa.types.TypeEngine[Any]", bool, str | None, str | None]

_HISTORY_COLUMNS: tuple[_ColumnSpec, ...] = (
    # RESTRICT: the journal is the reason a historical identity can be
    # explained, so deleting the taxon must deal with its history first.
    ("taxon_id", UUID(as_uuid=True), False, "taxa.id", "RESTRICT"),
    ("field", sa.String(length=64), False, None, None),
    ("old_value", sa.Text(), True, None, None),
    ("new_value", sa.Text(), True, None, None),
    ("source", sa.String(length=32), False, None, None),
    ("resolver", sa.String(length=128), True, None, None),
    ("release", sa.String(length=32), True, None, None),
    ("actor_kind", sa.String(length=16), False, None, None),
    # SET NULL: deleting a user must never delete or block the journal.
    ("actor_user_id", UUID(as_uuid=True), True, "users.id", "SET NULL"),
    ("actor_task_id", sa.String(length=64), True, None, None),
    ("changed_at", sa.DateTime(timezone=True), False, None, None),
    ("detail", postgresql.JSONB(astext_type=sa.Text()), True, None, None),
)

_RELATIONS_COLUMNS: tuple[_ColumnSpec, ...] = (
    ("from_taxon_id", UUID(as_uuid=True), False, "taxa.id", "RESTRICT"),
    ("to_taxon_id", UUID(as_uuid=True), True, "taxa.id", "RESTRICT"),
    ("to_col_xr_id", sa.String(length=16), True, None, None),
    ("to_scientific_name", sa.String(length=300), True, None, None),
    ("relation", sa.String(length=32), False, None, None),
    ("release", sa.String(length=32), True, None, None),
    ("authority", sa.String(length=64), True, None, None),
    ("evidence", sa.Text(), True, None, None),
    ("notes", sa.Text(), True, None, None),
    ("source", sa.String(length=32), False, None, None),
    ("created_by_id", UUID(as_uuid=True), True, "users.id", "SET NULL"),
)

#: ``(name, table, columns, unique, postgresql_where)``.
_IndexSpec = tuple[str, str, list[Any], bool, str | None]

_INDEXES: tuple[_IndexSpec, ...] = (
    # ``TimestampMixin`` declares ``created_at`` with ``index=True``; the ORM
    # therefore expects these to exist (P5 schema-parity introspection).
    (f"ix_{HISTORY_TABLE}_created_at", HISTORY_TABLE, ["created_at"], False, None),
    (
        f"ix_{RELATIONS_TABLE}_created_at",
        RELATIONS_TABLE,
        ["created_at"],
        False,
        None,
    ),
    # "What happened to this taxon, newest first" — the operator query.
    (
        "ix_taxon_identity_history_taxon_changed_at",
        HISTORY_TABLE,
        ["taxon_id", sa.text("changed_at DESC")],
        False,
        None,
    ),
    # "Every taxon whose status flipped in this release", newest first.
    (
        "ix_taxon_identity_history_field_changed_at",
        HISTORY_TABLE,
        ["field", sa.text("changed_at DESC")],
        False,
        None,
    ),
    # "What did this batch run change?" — sparse by construction.
    (
        "ix_taxon_identity_history_actor_task_id",
        HISTORY_TABLE,
        ["actor_task_id"],
        False,
        "actor_task_id IS NOT NULL",
    ),
    # Idempotency key of the auto-seeder: one edge per (source, relation,
    # external target).
    (
        "ux_taxon_concept_relations_edge",
        RELATIONS_TABLE,
        ["from_taxon_id", "relation", "to_col_xr_id"],
        True,
        None,
    ),
    # NULLs never collide in a UNIQUE index, so local-target edges (no COL
    # key) need their own partial uniqueness rule.
    (
        "ux_taxon_concept_relations_local_edge",
        RELATIONS_TABLE,
        ["from_taxon_id", "relation", "to_taxon_id"],
        True,
        "to_col_xr_id IS NULL",
    ),
    (
        "ix_taxon_concept_relations_from_taxon_id",
        RELATIONS_TABLE,
        ["from_taxon_id"],
        False,
        None,
    ),
    (
        "ix_taxon_concept_relations_to_taxon_id",
        RELATIONS_TABLE,
        ["to_taxon_id"],
        False,
        "to_taxon_id IS NOT NULL",
    ),
    (
        "ix_taxon_concept_relations_to_col_xr_id",
        RELATIONS_TABLE,
        ["to_col_xr_id"],
        False,
        None,
    ),
)

#: ``(name, table, condition)``.
_CHECKS: tuple[tuple[str, str, str], ...] = (
    # A no-op rewrite is not history.
    (
        "ck_taxon_identity_history_actual_change",
        HISTORY_TABLE,
        "old_value IS DISTINCT FROM new_value",
    ),
    (
        "ck_taxon_identity_history_actor_present",
        HISTORY_TABLE,
        "(actor_kind = 'user' AND actor_user_id IS NOT NULL"
        " AND actor_task_id IS NULL)"
        " OR (actor_kind = 'task' AND actor_task_id IS NOT NULL"
        " AND actor_user_id IS NULL)"
        " OR (actor_kind = 'system' AND actor_user_id IS NULL"
        " AND actor_task_id IS NULL)",
    ),
    # An edge with no target at all says nothing.
    (
        "ck_taxon_concept_relations_target_present",
        RELATIONS_TABLE,
        "to_taxon_id IS NOT NULL OR to_col_xr_id IS NOT NULL",
    ),
    # A concept is not a synonym of itself.
    (
        "ck_taxon_concept_relations_no_self_edge",
        RELATIONS_TABLE,
        "to_taxon_id IS NULL OR to_taxon_id <> from_taxon_id",
    ),
)

#: One-time backfill of the ``synonym_of`` edges implied by the identities
#: revision 0035 already resolved. ``to_taxon_id`` resolves via subquery and is
#: NULL when the accepted usage is not a local taxon — which, on the real
#: catalogue, is every one of them today. ``ON CONFLICT DO NOTHING`` keeps the
#: statement identical in effect to the runtime seeder.
_BACKFILL_SYNONYM_EDGES = f"""
INSERT INTO {RELATIONS_TABLE} (
    id, created_at, updated_at, from_taxon_id, to_taxon_id, to_col_xr_id,
    to_scientific_name, relation, release, authority, source
)
SELECT
    gen_random_uuid(),
    now(),
    now(),
    t.id,
    (
        SELECT a.id FROM taxa a
        WHERE a.col_xr_id = t.col_xr_accepted_id
        ORDER BY a.id
        LIMIT 1
    ),
    t.col_xr_accepted_id,
    t.accepted_scientific_name,
    'synonym_of',
    t.col_xr_release,
    t.col_xr_release,
    'col_xr_auto'
FROM taxa t
WHERE t.col_xr_status = 'SYNONYM'
  AND t.col_xr_accepted_id IS NOT NULL
  AND COALESCE(
        (
            SELECT a.id FROM taxa a
            WHERE a.col_xr_id = t.col_xr_accepted_id
            ORDER BY a.id
            LIMIT 1
        ) <> t.id,
        TRUE
      )
ON CONFLICT (from_taxon_id, relation, to_col_xr_id) DO NOTHING
"""


def _columns(specs: tuple[_ColumnSpec, ...]) -> list[sa.Column[Any]]:
    """Build fresh ``sa.Column`` objects for one table from its specs."""
    columns: list[sa.Column[Any]] = [
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    ]
    for name, type_, nullable, fk_target, fk_ondelete in specs:
        args: list[Any] = [name, type_]
        if fk_target is not None:
            args.append(sa.ForeignKey(fk_target, ondelete=fk_ondelete))
        columns.append(sa.Column(*args, nullable=nullable))
    return columns


def upgrade() -> None:
    op.create_table(HISTORY_TABLE, *_columns(_HISTORY_COLUMNS))
    op.create_table(RELATIONS_TABLE, *_columns(_RELATIONS_COLUMNS))

    for name, table, condition in _CHECKS:
        op.create_check_constraint(name, table, sa.text(condition))

    for index_name, table, columns, unique, where in _INDEXES:
        op.create_index(
            index_name,
            table,
            columns,
            unique=unique,
            postgresql_where=sa.text(where) if where else None,
        )

    # One-time backfill of the edges implied by the already-resolved
    # identities. Safe to re-run (ON CONFLICT DO NOTHING).
    op.execute(_BACKFILL_SYNONYM_EDGES)


def downgrade() -> None:
    # Dropping the tables takes their indexes, checks and the backfilled rows
    # with them, so no per-object drop is needed.
    op.drop_table(RELATIONS_TABLE)
    op.drop_table(HISTORY_TABLE)
