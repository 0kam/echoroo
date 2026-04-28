"""Taxon sensitivity service (Phase 11 / T610, FR-032 / FR-036 / NFR-001a).

This module owns the *bulk preload* and *request-scope cache* for the auto-
obscure pipeline. The pure decision function
:func:`echoroo.core.permissions.compute_effective_resolution` consumes the
two dicts returned here:

* ``sensitivity_map`` — ``{taxon_id: effective sensitivity_h3_res}`` derived
  from the global :class:`TaxonSensitivity` rows. When more than one source
  (``manual`` / ``moe_rdb`` / ``iucn``) emits an opinion for the same taxon
  we collapse to a single integer per spec L313-365 by taking the
  **strictest** (numerically lowest) recommendation. The source-priority
  rule (manual > moe_rdb > iucn) is recorded in spec FR-032 as a tie-break
  for *category* metadata, not for the H3 resolution itself — masking is
  always conservative, so "min h3_res" is the safe default.

* ``override_map`` — ``{(project_id, taxon_id): override_row}`` filtered to
  rows whose ``approval_status = 'applied'`` (FR-034). The decision
  function inspects ``direction`` to decide whether the override REPLACES
  the global (``looser``, post-approval) or is ANDed with the global
  (``stricter``, immediate).

NFR-001a requires the masking pipeline to issue **at most one** sensitivity
SELECT and **at most one** override SELECT per HTTP request, regardless of
how many detections / recordings are being projected. We satisfy this with a
:class:`contextvars.ContextVar` cache that the FastAPI dependency tree can
reset on every request boundary.

This module also exposes helpers used by the IUCN / MoE workers and CLI:

* :func:`upsert_taxon_sensitivity` — single-row UPSERT for the
  ``(taxon_id, source)`` pair, used by :mod:`echoroo.workers.iucn_sync`
  and :mod:`echoroo.scripts.seed_moe_rdb`.
* :func:`is_iucn_fail_safe_active` — Redis-backed flag set by the IUCN
  worker when 2 weeks of consecutive sync failures elapse (FR-036). When
  active, *unknown* taxa default to ``H3_RES_7`` instead of the standard
  ``H3_RES_9``; *known* taxa keep whatever the most recent successful
  sync recorded.

The pure decision function lives in
:mod:`echoroo.core.permissions`; this service is purely about *fetching*
the inputs efficiently.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.permissions import H3_RES_7, H3_RES_9
from echoroo.core.permissions import (
    compute_effective_resolution as _compute_effective_resolution,
)
from echoroo.core.redis import get_redis_connection
from echoroo.models.enums import TaxonOverrideApprovalStatus, TaxonSensitivitySource
from echoroo.models.project_taxon_override import ProjectTaxonSensitivityOverride
from echoroo.models.taxon_sensitivity import TaxonSensitivity

logger = logging.getLogger(__name__)


#: Redis key set by the IUCN sync worker after 14 days of consecutive
#: sync failures (FR-036). Presence (any non-null value) means "fail-safe
#: mode is active" — unknown species default to ``H3_RES_7`` until the
#: next successful sync clears the key.
IUCN_FAIL_SAFE_REDIS_KEY: str = "iucn:fail_safe_active"

#: TTL for the fail-safe flag. Slightly longer than the sync cadence
#: (weekly) so a transient Redis outage cannot accidentally lift the
#: fail-safe between two scheduled runs. 30 days is comfortably above
#: the spec's "2 weeks consecutive failure" trigger.
IUCN_FAIL_SAFE_TTL_SECONDS: int = 30 * 24 * 60 * 60

#: Source priority for tie-breaking *metadata* (category, notes). The
#: actual ``sensitivity_h3_res`` is collapsed via min() per the spec
#: (most-conservative wins). Spec L313-365 + FR-032.
_SOURCE_PRIORITY: dict[TaxonSensitivitySource, int] = {
    TaxonSensitivitySource.MANUAL: 0,
    TaxonSensitivitySource.MOE_RDB: 1,
    TaxonSensitivitySource.IUCN: 2,
}


# =============================================================================
# Request-scope cache (NFR-001a)
# =============================================================================


class _RequestCache:
    """Mutable per-request cache holding sensitivity + override dicts.

    Stored in a :class:`contextvars.ContextVar` so it is automatically
    isolated per asyncio task and the FastAPI worker pool. Callers should
    treat the dicts as *additive*: looking up a missing key yields a
    follow-up DB query that POPULATES the cache, never a stale read.
    """

    __slots__ = ("sensitivity", "overrides")

    def __init__(self) -> None:
        # taxon_id -> effective h3 resolution
        self.sensitivity: dict[str, int] = {}
        # (project_id, taxon_id) -> applied ProjectTaxonSensitivityOverride
        self.overrides: dict[tuple[UUID, str], ProjectTaxonSensitivityOverride] = {}


_REQUEST_CACHE: contextvars.ContextVar[_RequestCache | None] = contextvars.ContextVar(
    "echoroo_taxon_sensitivity_request_cache",
    default=None,
)


def reset_request_cache() -> contextvars.Token[_RequestCache | None]:
    """Initialise a fresh request-scope cache and return a reset Token.

    Intended use::

        token = reset_request_cache()
        try:
            ...  # handle request
        finally:
            _REQUEST_CACHE.reset(token)

    A FastAPI dependency or middleware should drive this; failing to reset
    leaks cache entries between requests within the same worker process,
    which would defeat NFR-001a's freshness guarantees after an IUCN sync.
    """
    return _REQUEST_CACHE.set(_RequestCache())


def _ensure_request_cache() -> _RequestCache:
    """Return the active cache, lazily creating one if absent.

    Lazy creation lets call sites that did not run the dependency (e.g.
    Celery tasks, scripts) still benefit from local memoisation within a
    single function call without forcing every entry point to wire up the
    middleware.
    """
    cache = _REQUEST_CACHE.get()
    if cache is None:
        cache = _RequestCache()
        _REQUEST_CACHE.set(cache)
    return cache


# =============================================================================
# Bulk preload — sensitivity map
# =============================================================================


async def bulk_load_sensitivity_map(
    session: AsyncSession,
    taxon_ids: set[str],
    *,
    iucn_fail_safe_active: bool = False,
) -> dict[str, int]:
    """Return ``{taxon_id: effective sensitivity_h3_res}`` for the given IDs.

    Behaviour:

    * Issues at most ONE ``SELECT ... WHERE taxon_id IN (:ids)`` query
      against ``taxon_sensitivities`` (NFR-001a).
    * Collapses multiple source rows for the same taxon by taking the
      **strictest** ``sensitivity_h3_res`` (lowest integer, conservative
      masking). This matches spec L313-365 — the masking pipeline never
      relaxes protection silently because more than one authority weighs
      in.
    * When ``iucn_fail_safe_active`` is True, taxa absent from the result
      are pre-populated in the returned dict with :data:`H3_RES_7` per
      FR-036 ("unknown species default to H3_RES_7 during 2-week IUCN
      outage"). Known taxa always retain whatever the last successful
      sync recorded.
    * Re-uses the request-scope cache so a second list endpoint in the
      same request does not re-query for taxa already loaded.

    Args:
        session: Active SQLAlchemy AsyncSession.
        taxon_ids: De-duplicated set of GBIF species keys.
        iucn_fail_safe_active: Result of :func:`is_iucn_fail_safe_active`.
            Pass-through so callers can inspect it once per request.

    Returns:
        Dict containing every requested taxon_id. Unknown taxa map to
        :data:`H3_RES_9` (open) under normal conditions, or :data:`H3_RES_7`
        (coarse) when the IUCN fail-safe is active.
    """
    if not taxon_ids:
        return {}

    cache = _ensure_request_cache()

    # Determine which IDs still need a database lookup. We do not assume
    # a None / sentinel value — explicit membership keeps the cache
    # composable with future call sites that wish to pre-warm it.
    missing = {tid for tid in taxon_ids if tid not in cache.sensitivity}

    if missing:
        stmt = sa.select(
            TaxonSensitivity.taxon_id,
            TaxonSensitivity.source,
            TaxonSensitivity.sensitivity_h3_res,
        ).where(TaxonSensitivity.taxon_id.in_(missing))
        result = await session.execute(stmt)

        # Collapse multi-source rows to the strictest h3 resolution.
        per_taxon: dict[str, int] = {}
        for tid, _source, h3_res in result.all():
            current = per_taxon.get(tid)
            if current is None or h3_res < current:
                per_taxon[tid] = h3_res

        for tid in missing:
            if tid in per_taxon:
                cache.sensitivity[tid] = per_taxon[tid]
            else:
                # Unknown taxon — apply fail-safe default if active.
                cache.sensitivity[tid] = (
                    H3_RES_7 if iucn_fail_safe_active else H3_RES_9
                )

    return {tid: cache.sensitivity[tid] for tid in taxon_ids}


# =============================================================================
# Bulk preload — override map (FR-033)
# =============================================================================


async def bulk_load_override_map(
    session: AsyncSession,
    project_id: UUID,
    taxon_ids: set[str],
) -> dict[tuple[UUID, str], ProjectTaxonSensitivityOverride]:
    """Return ``{(project_id, taxon_id): override}`` for applied overrides.

    Issues at most ONE SELECT against ``project_taxon_sensitivity_overrides``
    (NFR-001a). Filters to ``approval_status = 'applied'`` so neither
    pending looser overrides (still awaiting superuser approval) nor
    rejected ones leak into the masking decision (FR-034).

    Args:
        session: Active SQLAlchemy AsyncSession.
        project_id: The project whose overrides are being looked up.
        taxon_ids: De-duplicated set of GBIF species keys.

    Returns:
        Dict keyed by ``(project_id, taxon_id)``. Pairs without an applied
        override are simply absent from the returned dict — the consumer
        is :func:`compute_effective_resolution` which already treats a
        missing key as "no override".
    """
    if not taxon_ids:
        return {}

    cache = _ensure_request_cache()

    # All requested keys for this project. The cache uses the same tuple
    # key so a second list-endpoint in the same request reuses the rows.
    keys_needed = {(project_id, tid) for tid in taxon_ids}
    missing_keys = {k for k in keys_needed if k not in cache.overrides}
    missing_taxons = {tid for (_pid, tid) in missing_keys}

    if missing_taxons:
        stmt = sa.select(ProjectTaxonSensitivityOverride).where(
            ProjectTaxonSensitivityOverride.project_id == project_id,
            ProjectTaxonSensitivityOverride.taxon_id.in_(missing_taxons),
            ProjectTaxonSensitivityOverride.approval_status
            == TaxonOverrideApprovalStatus.APPLIED,
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

        for row in rows:
            cache.overrides[(row.project_id, row.taxon_id)] = row

        # The unique partial index ``ux_taxon_overrides_applied_unique``
        # guarantees that the SELECT above returns at most ONE row per
        # ``(project_id, taxon_id)`` pair (FR-033 / project_taxon_override
        # docstring), so we do not need a per-key dedup pass here.

    return {
        key: cache.overrides[key]
        for key in keys_needed
        if key in cache.overrides
    }


# =============================================================================
# Pure decision wrapper (re-export)
# =============================================================================


def compute_effective_resolution(
    *,
    user: Any,  # noqa: ARG001 — kept for API symmetry with the spec
    project: Any,
    resource: Any,
    role: str,
    effective_permissions: Any = frozenset(),
    taxon_sensitivity_map: dict[str, int] | None = None,
    override_map: dict[tuple[UUID, str], ProjectTaxonSensitivityOverride] | None = None,
) -> int:
    """Service-layer wrapper around :func:`echoroo.core.permissions.compute_effective_resolution`.

    The core/permissions function is the canonical implementation of
    spec L313-365 (Step A-E) and lives outside the service layer because
    it is a *pure* decision (no DB access, no I/O). This wrapper exists
    so the rest of the codebase can import the auto-obscure entry point
    from a single, service-layer location alongside the bulk loaders.

    The ``user`` parameter is accepted but unused — the underlying
    decision keys solely off ``role`` + ``project.visibility`` +
    ``effective_permissions``. Keeping the argument here preserves the
    spec's published signature so callers do not have to remember which
    layer drops it.
    """
    return _compute_effective_resolution(
        resource=resource,
        role=role,
        project=project,
        effective_permissions=effective_permissions,
        taxon_sensitivity_map=taxon_sensitivity_map,
        override_map=override_map,
    )


# =============================================================================
# Single-row UPSERT — used by IUCN worker + MoE seeder + manual overrides
# =============================================================================


async def upsert_taxon_sensitivity(
    session: AsyncSession,
    *,
    taxon_id: str,
    source: TaxonSensitivitySource,
    sensitivity_h3_res: int,
    category: str | None = None,
    notes: str | None = None,
) -> tuple[bool, int | None]:
    """Insert-or-update a single ``(taxon_id, source)`` row.

    Returns ``(loosened, previous_h3_res)`` so the caller can implement
    the FR-036 sanity check ("abort sync if more than 10 % of rows would
    *loosen* masking in one batch"). ``loosened`` is True iff a previous
    row existed AND the new ``sensitivity_h3_res`` is *higher* (less
    masking) than the prior value.

    The conflict target ``(taxon_id, source)`` matches the unique
    constraint ``ux_taxon_sensitivities_taxon_source`` and lets the
    UPSERT execute as a single statement under PostgreSQL's
    ``ON CONFLICT DO UPDATE``.
    """
    # First read the previous value so we can detect "loosening" — the
    # sanity check needs the diff before the row is overwritten.
    previous_stmt = sa.select(TaxonSensitivity.sensitivity_h3_res).where(
        TaxonSensitivity.taxon_id == taxon_id,
        TaxonSensitivity.source == source,
    )
    previous_result = await session.execute(previous_stmt)
    previous_h3_res = previous_result.scalar_one_or_none()

    insert_stmt = pg_insert(TaxonSensitivity).values(
        taxon_id=taxon_id,
        source=source,
        sensitivity_h3_res=sensitivity_h3_res,
        category=category,
        notes=notes,
    )
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["taxon_id", "source"],
        set_={
            "sensitivity_h3_res": insert_stmt.excluded.sensitivity_h3_res,
            "category": insert_stmt.excluded.category,
            "notes": insert_stmt.excluded.notes,
        },
    )
    await session.execute(upsert_stmt)

    loosened = previous_h3_res is not None and sensitivity_h3_res > previous_h3_res
    return loosened, previous_h3_res


# =============================================================================
# IUCN fail-safe (Redis-backed flag, FR-036)
# =============================================================================


async def is_iucn_fail_safe_active() -> bool:
    """Return True iff the IUCN 2-week fail-safe is currently active.

    Reads :data:`IUCN_FAIL_SAFE_REDIS_KEY` from Redis; any truthy value
    (the worker writes ``"1"``) means unknown species should default to
    :data:`H3_RES_7` instead of :data:`H3_RES_9`. A Redis outage fails
    *open* (returns False) so a complete cache failure does not silently
    coarsen every unknown taxon — the masking pipeline is still
    conservative because the global ``TaxonSensitivity`` rows for known
    sensitive taxa remain intact.
    """
    try:
        client = await get_redis_connection()
        value = await client.get(IUCN_FAIL_SAFE_REDIS_KEY)
    except Exception as exc:  # noqa: BLE001 — fail-open per docstring
        logger.warning(
            "iucn fail-safe lookup failed; defaulting to inactive: %r", exc
        )
        return False
    return bool(value)


async def set_iucn_fail_safe(active: bool) -> None:
    """Toggle the IUCN fail-safe flag in Redis.

    ``active=True`` writes ``"1"`` with TTL :data:`IUCN_FAIL_SAFE_TTL_SECONDS`.
    ``active=False`` deletes the key. The IUCN worker calls this from
    its terminal status branch on each run.
    """
    try:
        client = await get_redis_connection()
        if active:
            await client.set(
                IUCN_FAIL_SAFE_REDIS_KEY,
                "1",
                ex=IUCN_FAIL_SAFE_TTL_SECONDS,
            )
        else:
            await client.delete(IUCN_FAIL_SAFE_REDIS_KEY)
    except Exception as exc:  # noqa: BLE001 — best effort; soft alert
        logger.warning(
            "iucn fail-safe flag toggle failed: active=%s error=%r",
            active,
            exc,
        )


__all__ = [
    "IUCN_FAIL_SAFE_REDIS_KEY",
    "IUCN_FAIL_SAFE_TTL_SECONDS",
    "bulk_load_override_map",
    "bulk_load_sensitivity_map",
    "compute_effective_resolution",
    "is_iucn_fail_safe_active",
    "reset_request_cache",
    "set_iucn_fail_safe",
    "upsert_taxon_sensitivity",
]
