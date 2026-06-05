"""Shared helpers for resolving locale-specific vernacular names.

Resolving a vernacular name per tag naively causes N+1 queries. The helper
here issues a single ``SELECT ... WHERE taxon_id IN (...)`` query and builds
a ``{taxon_id: name}`` mapping that callers can use to fill
``TagResponse.vernacular_name`` (or similar fields) without additional round
trips to the database.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.taxon_vernacular_name import TaxonVernacularName


async def resolve_vernacular_names(
    db: AsyncSession,
    taxon_ids: Iterable[UUID | None],
    locale: str,
) -> dict[UUID, str]:
    """Batch-resolve vernacular names for a collection of taxon IDs.

    Issues a single query filtered by ``taxon_id IN (...)`` and
    ``locale IN (<requested>, 'en')`` and resolves each taxon's name using a
    requested-locale → English fallback chain. For each taxon the priority is:

    1. requested-locale row with ``is_primary = TRUE``
    2. requested-locale row (any)
    3. English (``en``) row with ``is_primary = TRUE``
    4. English (``en``) row (any)

    When ``locale == "en"`` the chain collapses to the English candidates only.
    Taxa that have neither a requested-locale nor an English row are omitted
    from the mapping (the final scientific-name floor is a display concern
    handled by the caller, not here), so callers can use
    ``mapping.get(taxon_id)`` to obtain ``None`` for unresolved entries.

    Args:
        db: Active SQLAlchemy async session used to execute the query.
        taxon_ids: Iterable of taxon UUIDs (``None`` values are ignored).
        locale: Language/locale code to match (e.g. ``"en"``, ``"ja"``).

    Returns:
        Mapping of ``taxon_id`` to the resolved vernacular name.
    """
    unique_ids: list[UUID] = []
    seen: set[UUID] = set()
    for taxon_id in taxon_ids:
        if taxon_id is None or taxon_id in seen:
            continue
        seen.add(taxon_id)
        unique_ids.append(taxon_id)

    if not unique_ids:
        return {}

    # Fetch both the requested locale and English (the fallback) in a single
    # query. Collapse to just English when the requested locale already is en.
    candidate_locales = [locale] if locale == "en" else [locale, "en"]

    result = await db.execute(
        select(TaxonVernacularName)
        .where(TaxonVernacularName.taxon_id.in_(unique_ids))
        .where(TaxonVernacularName.locale.in_(candidate_locales))
        .order_by(
            TaxonVernacularName.taxon_id,
            TaxonVernacularName.is_primary.desc(),
        )
    )

    # Bucket candidate names per taxon by priority tier so we can apply the
    # requested-locale → English fallback chain deterministically.
    # Tiers (lower index = higher priority):
    #   0: requested-locale primary
    #   1: requested-locale any
    #   2: english primary
    #   3: english any
    best: dict[UUID, tuple[int, str]] = {}
    for vn in result.scalars().all():
        # Base offset 0 for the requested locale, 2 for the English fallback;
        # +1 within each pair when the row is not primary.
        locale_offset = 0 if vn.locale == locale else 2
        tier = locale_offset + (0 if vn.is_primary else 1)
        current = best.get(vn.taxon_id)
        if current is None or tier < current[0]:
            best[vn.taxon_id] = (tier, vn.name)

    return {taxon_id: name for taxon_id, (_, name) in best.items()}
