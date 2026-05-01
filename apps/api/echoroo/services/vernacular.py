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

    Issues a single query filtered by ``taxon_id IN (...)`` and ``locale``.
    The returned mapping prefers ``is_primary = TRUE`` entries and falls
    back to any remaining entry for the locale when no primary exists.

    Args:
        db: Active SQLAlchemy async session used to execute the query.
        taxon_ids: Iterable of taxon UUIDs (``None`` values are ignored).
        locale: Language/locale code to match (e.g. ``"en"``, ``"ja"``).

    Returns:
        Mapping of ``taxon_id`` to the resolved vernacular name. Taxa
        without a matching row are simply omitted from the mapping so that
        callers can use ``mapping.get(taxon_id)`` to obtain ``None`` for
        unresolved entries.
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

    result = await db.execute(
        select(TaxonVernacularName)
        .where(TaxonVernacularName.taxon_id.in_(unique_ids))
        .where(TaxonVernacularName.locale == locale)
        .order_by(
            TaxonVernacularName.taxon_id,
            TaxonVernacularName.is_primary.desc(),
        )
    )

    mapping: dict[UUID, str] = {}
    for vn in result.scalars().all():
        # The ORDER BY keeps primary entries first, so the first hit per
        # taxon_id wins.
        if vn.taxon_id not in mapping:
            mapping[vn.taxon_id] = vn.name

    return mapping
