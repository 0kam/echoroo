"""Taxon identity journalling and concept-relation seeding (WS-A v2 slice 5).

Two cooperating pieces:

``record_identity_changes`` / ``record_identity_change``
    Write :class:`~echoroo.models.taxon_identity_history.TaxonIdentityHistory`
    rows for the identity fields a resolver just rewrote. Both write on the
    SAME session (and therefore the same transaction) as the ``taxa`` UPDATE,
    so a chunk commit banks the new value and its journal together — or
    neither. They are deliberately not chained into ``AuditLogService``: the
    platform audit log needs a fresh SERIALIZABLE session and a global advisory
    lock per row, which would serialize a 6,500-row batch.

``seed_concept_relations`` / ``relink_concept_relations``
    Derive the "where did this concept go" edges from a completed COL XR
    resolution. Both are idempotent: the seeder is an
    ``INSERT ... ON CONFLICT DO NOTHING`` on the edge's unique key, and the
    relinker only ever fills a ``to_taxon_id`` that is currently NULL.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_concept_relation import (
    CONCEPT_RELATION_SOURCE_COL_XR_AUTO,
    CONCEPT_RELATION_SYNONYM_OF,
    TaxonConceptRelation,
)
from echoroo.models.taxon_identity_history import (
    IDENTITY_HISTORY_FIELDS,
    TaxonIdentityHistory,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Actor kinds (mirrors ``IDENTITY_HISTORY_ACTOR_KINDS``; named constants keep
# the call sites from stringly-typing the CHECK constraint).
ACTOR_KIND_USER = "user"
ACTOR_KIND_TASK = "task"
ACTOR_KIND_SYSTEM = "system"

SOURCE_COL_XR = "col_xr"
SOURCE_GBIF = "gbif"


def resolve_actor_kind(
    *, actor_user_id: UUID | None, actor_task_id: str | None
) -> str:
    """Pick the ``actor_kind`` the actor-present CHECK will accept.

    A request user wins over a task id (a user-triggered synchronous call is
    attributable to the human, not to the process); with neither, the change is
    unattributed background work and is recorded as ``system``.
    """
    if actor_user_id is not None:
        return ACTOR_KIND_USER
    if actor_task_id is not None:
        return ACTOR_KIND_TASK
    return ACTOR_KIND_SYSTEM


def _as_text(value: object | None) -> str | None:
    """Render an identity value for the journal's ``TEXT`` columns."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def record_identity_change(
    db: AsyncSession,
    taxon: Taxon,
    *,
    field: str,
    old_value: object | None,
    new_value: object | None,
    source: str,
    resolver: str | None = None,
    release: str | None = None,
    actor_kind: str,
    actor_user_id: UUID | None = None,
    actor_task_id: str | None = None,
    detail: Mapping[str, object] | None = None,
    changed_at: datetime | None = None,
) -> TaxonIdentityHistory | None:
    """Journal ONE identity field change, or return ``None`` for a no-op.

    Used directly where SQLAlchemy attribute history is unavailable because the
    write already flushed (``TaxonService.create_from_gbif`` assigns its GBIF
    key inside a SAVEPOINT, so the post-savepoint value is compared against the
    captured pre-savepoint one instead).

    An identical rewrite is NOT history and is dropped here, mirroring the
    ``ck_taxon_identity_history_actual_change`` database CHECK.
    """
    old_text = _as_text(old_value)
    new_text = _as_text(new_value)
    if old_text == new_text:
        return None

    row = TaxonIdentityHistory(
        taxon_id=taxon.id,
        field=field,
        old_value=old_text,
        new_value=new_text,
        source=source,
        resolver=resolver,
        release=release,
        actor_kind=actor_kind,
        actor_user_id=actor_user_id,
        actor_task_id=actor_task_id,
        changed_at=changed_at or datetime.now(UTC),
        detail=dict(detail) if detail is not None else None,
    )
    db.add(row)
    return row


def record_identity_changes(
    db: AsyncSession,
    taxon: Taxon,
    *,
    source: str,
    resolver: str | None = None,
    release: str | None = None,
    actor_kind: str,
    actor_user_id: UUID | None = None,
    actor_task_id: str | None = None,
    detail: Mapping[str, object] | None = None,
    fields: Sequence[str] = IDENTITY_HISTORY_FIELDS,
) -> list[TaxonIdentityHistory]:
    """Journal every identity field the caller just rewrote on ``taxon``.

    Reads SQLAlchemy's per-attribute history, so it must be called AFTER the
    in-place assignments and BEFORE the flush that clears them
    (``TaxonRepository.update`` is a bare ``flush``). The returned rows are
    already ``add``ed to ``db`` and land in the caller's transaction — the COL
    XR batch therefore banks each chunk's identities and their journal in the
    same commit.

    Returns an empty list when nothing actually changed: a re-resolution that
    reproduces the same identity writes no history at all.
    """
    # ``raiseerr=False``: unit tests drive the resolvers with mock taxa, and a
    # non-mapped object simply has no attribute history to read.
    state = sa.inspect(taxon, raiseerr=False)
    if state is None:
        return []

    rows: list[TaxonIdentityHistory] = []
    changed_at = datetime.now(UTC)
    for field in fields:
        attribute = state.attrs.get(field)
        if attribute is None:  # pragma: no cover - defensive
            continue
        history = attribute.history
        if not history.has_changes():
            continue
        old_value = history.deleted[0] if history.deleted else None
        new_value = history.added[0] if history.added else None
        row = record_identity_change(
            db,
            taxon,
            field=field,
            old_value=old_value,
            new_value=new_value,
            source=source,
            resolver=resolver,
            release=release,
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            actor_task_id=actor_task_id,
            detail=detail,
            changed_at=changed_at,
        )
        if row is not None:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Concept relations
# ---------------------------------------------------------------------------


async def seed_concept_relations(
    db: AsyncSession, taxon_ids: Sequence[UUID] | None = None
) -> int:
    """Seed ``synonym_of`` edges from the current COL XR resolution.

    Rule: a taxon whose ``col_xr_status`` is ``SYNONYM`` and which carries a
    ``col_xr_accepted_id`` points at a DIFFERENT concept. The edge is keyed by
    that accepted COL usage key (``to_col_xr_id``), because on the real
    catalogue the accepted usage is essentially never a local taxon —
    ``to_taxon_id`` is resolved opportunistically and stays NULL otherwise
    (:func:`relink_concept_relations` fills it in later).

    Idempotent: ``ON CONFLICT DO NOTHING`` on
    ``ux_taxon_concept_relations_edge``. Re-running a forced pass therefore
    leaves the relation count unchanged.

    Args:
        db: Session to write on. NOT committed here — the caller decides (the
            COL XR batch seeds just before each chunk commit so the edges are
            banked with the identities that produced them).
        taxon_ids: Restrict the seed to these taxa. ``None`` scans the whole
            catalogue (used for a one-off backfill).

    Returns:
        Number of edges actually inserted.
    """
    if taxon_ids is not None and not taxon_ids:
        return 0

    target = aliased(Taxon, name="target")

    # Deterministic pick: several taxa may legitimately share a COL usage key
    # (taxonomic lumps), so ORDER BY id makes the choice reproducible.
    target_id = (
        sa.select(target.id)
        .where(target.col_xr_id == Taxon.col_xr_accepted_id)
        .order_by(target.id)
        .limit(1)
        .scalar_subquery()
    )

    conditions = [
        Taxon.col_xr_status == "SYNONYM",
        Taxon.col_xr_accepted_id.isnot(None),
        # ck_taxon_concept_relations_no_self_edge: never point a concept at
        # itself (a name that is its own accepted usage is not a synonym).
        sa.or_(target_id.is_(None), target_id != Taxon.id),
    ]
    if taxon_ids is not None:
        conditions.append(Taxon.id.in_(list(taxon_ids)))

    source_select = sa.select(
        sa.func.gen_random_uuid(),
        sa.func.now(),
        sa.func.now(),
        Taxon.id,
        target_id,
        Taxon.col_xr_accepted_id,
        Taxon.accepted_scientific_name,
        sa.literal(CONCEPT_RELATION_SYNONYM_OF, sa.String(32)),
        Taxon.col_xr_release,
        Taxon.col_xr_release,
        sa.literal(CONCEPT_RELATION_SOURCE_COL_XR_AUTO, sa.String(32)),
    ).where(sa.and_(*conditions))

    stmt = (
        pg_insert(TaxonConceptRelation)
        .from_select(
            [
                "id",
                "created_at",
                "updated_at",
                "from_taxon_id",
                "to_taxon_id",
                "to_col_xr_id",
                "to_scientific_name",
                "relation",
                "release",
                "authority",
                "source",
            ],
            source_select,
        )
        .on_conflict_do_nothing(
            index_elements=["from_taxon_id", "relation", "to_col_xr_id"]
        )
    )
    result = cast("CursorResult[Any]", await db.execute(stmt))
    inserted = result.rowcount or 0
    if inserted:
        logger.info("Seeded %d taxon concept relation(s)", inserted)
    return inserted


async def relink_concept_relations(db: AsyncSession) -> int:
    """Fill ``to_taxon_id`` on edges whose target became a local taxon.

    Idempotent and additive: only rows with a NULL ``to_taxon_id`` and a
    non-NULL ``to_col_xr_id`` are considered, and only when exactly that COL
    usage key now exists on a local ``taxa`` row other than the edge's own
    source. Running it twice is a no-op.

    Returns:
        Number of edges relinked.
    """
    target = aliased(Taxon, name="target")

    target_id = (
        sa.select(target.id)
        .where(
            target.col_xr_id == TaxonConceptRelation.to_col_xr_id,
            # Never create a self-edge the CHECK would reject.
            target.id != TaxonConceptRelation.from_taxon_id,
        )
        .order_by(target.id)
        .limit(1)
        .scalar_subquery()
    )

    stmt = (
        sa.update(TaxonConceptRelation)
        .where(
            TaxonConceptRelation.to_taxon_id.is_(None),
            TaxonConceptRelation.to_col_xr_id.isnot(None),
            target_id.isnot(None),
        )
        .values(to_taxon_id=target_id, updated_at=sa.func.now())
        # The new value comes from a correlated subquery, so the ORM cannot
        # evaluate it in Python; ``fetch`` uses RETURNING to expire exactly the
        # rows that changed, keeping a caller that reuses this session from
        # reading a stale ``to_taxon_id``.
        .execution_options(synchronize_session="fetch")
    )
    result = cast("CursorResult[Any]", await db.execute(stmt))
    relinked = result.rowcount or 0
    if relinked:
        logger.info("Relinked %d taxon concept relation target(s)", relinked)
    return relinked


__all__ = [
    "ACTOR_KIND_SYSTEM",
    "ACTOR_KIND_TASK",
    "ACTOR_KIND_USER",
    "SOURCE_COL_XR",
    "SOURCE_GBIF",
    "record_identity_change",
    "record_identity_changes",
    "relink_concept_relations",
    "resolve_actor_kind",
    "seed_concept_relations",
]
