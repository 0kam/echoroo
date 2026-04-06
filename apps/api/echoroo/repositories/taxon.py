"""Taxon repository for database operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.repositories.base import BaseRepository


class TaxonRepository(BaseRepository[Taxon]):
    """Repository for Taxon entity operations."""

    model = Taxon

    async def get_by_id(self, taxon_id: UUID) -> Taxon | None:
        result = await self.db.execute(
            select(Taxon)
            .where(Taxon.id == taxon_id)
            .options(selectinload(Taxon.vernacular_names))
        )
        return result.scalar_one_or_none()

    async def get_by_scientific_name(self, scientific_name: str) -> Taxon | None:
        result = await self.db.execute(
            select(Taxon).where(Taxon.scientific_name == scientific_name)
        )
        return result.scalar_one_or_none()

    async def get_or_create_by_scientific_name(
        self,
        scientific_name: str,
        common_name: str | None = None,
        is_non_biological: bool = False,
    ) -> Taxon:
        """Get existing taxon by scientific name or create a new one.

        If common_name is provided and the taxon is newly created,
        a vernacular name (en, source=birdnet) is also created.
        """
        existing = await self.get_by_scientific_name(scientific_name)
        if existing is not None:
            return existing

        taxon = Taxon(
            scientific_name=scientific_name,
            is_non_biological=is_non_biological,
        )
        self.db.add(taxon)
        await self.db.flush()

        if common_name:
            vn = TaxonVernacularName(
                taxon_id=taxon.id,
                locale="en",
                name=common_name,
                source="birdnet",
                is_primary=True,
            )
            self.db.add(vn)
            await self.db.flush()

        return taxon

    async def bulk_create(self, taxa_list: list[dict[str, object]]) -> int:
        """Bulk insert taxa, skipping duplicates.

        Each dict should have: scientific_name, common_name (optional),
        is_non_biological (optional, default False).

        Returns number of newly created taxa.
        """
        created = 0
        for item in taxa_list:
            sci_name = str(item["scientific_name"])
            existing = await self.get_by_scientific_name(sci_name)
            if existing is not None:
                continue

            taxon = Taxon(
                scientific_name=sci_name,
                is_non_biological=bool(item.get("is_non_biological", False)),
            )
            self.db.add(taxon)
            await self.db.flush()

            common_name = item.get("common_name")
            if common_name:
                vn = TaxonVernacularName(
                    taxon_id=taxon.id,
                    locale="en",
                    name=str(common_name),
                    source="birdnet",
                    is_primary=True,
                )
                self.db.add(vn)

            created += 1

        await self.db.flush()
        return created

    async def get_unresolved(self, limit: int = 100) -> list[Taxon]:
        """Get taxa without GBIF resolution."""
        result = await self.db.execute(
            select(Taxon)
            .where(Taxon.gbif_resolved_at.is_(None))
            .where(Taxon.is_non_biological.is_(False))
            .order_by(Taxon.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_taxa(
        self,
        search: str | None = None,
        is_non_biological: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[Taxon], int]:
        """List taxa with optional filtering and pagination."""
        conditions: list[ColumnElement[Any]] = []
        if search:
            pattern = f"%{search}%"
            conditions.append(Taxon.scientific_name.ilike(pattern))
        if is_non_biological is not None:
            conditions.append(Taxon.is_non_biological == is_non_biological)

        count_q = select(func.count()).select_from(Taxon)
        if conditions:
            count_q = count_q.where(*conditions)
        total: int = (await self.db.execute(count_q)).scalar_one()

        offset = (page - 1) * page_size
        query = (
            select(Taxon)
            .order_by(Taxon.scientific_name.asc())
            .offset(offset)
            .limit(page_size)
        )
        if conditions:
            query = query.where(*conditions)

        result = await self.db.execute(query)
        return list(result.scalars().all()), total

    async def search(
        self,
        query: str,
        locale: str | None = None,
        limit: int = 20,
    ) -> list[tuple[Taxon, str | None]]:
        """Search taxa by scientific name or vernacular name.

        Returns list of (Taxon, matching_common_name_or_None).
        """
        pattern = f"%{query}%"

        # Subquery for vernacular name matches
        vn_select = (
            select(
                TaxonVernacularName.taxon_id,
                TaxonVernacularName.name.label("vn_name"),
            )
            .where(TaxonVernacularName.name.ilike(pattern))
        )
        if locale:
            vn_select = vn_select.where(TaxonVernacularName.locale == locale)
        vn_subq = vn_select.subquery("vn_match")

        result = await self.db.execute(
            select(Taxon, vn_subq.c.vn_name)
            .outerjoin(vn_subq, vn_subq.c.taxon_id == Taxon.id)
            .where(
                or_(
                    Taxon.scientific_name.ilike(pattern),
                    vn_subq.c.vn_name.isnot(None),
                )
            )
            .order_by(Taxon.scientific_name.asc())
            .limit(limit)
        )
        return [(row.Taxon, row.vn_name) for row in result.all()]

    async def update(self, taxon: Taxon) -> Taxon:
        """Flush changes to an existing taxon."""
        await self.db.flush()
        return taxon

    async def add_vernacular_name(
        self,
        taxon_id: UUID,
        locale: str,
        name: str,
        source: str,
        is_primary: bool = False,
    ) -> TaxonVernacularName:
        """Add a vernacular name to a taxon (upsert by unique constraint)."""
        # Check existing
        result = await self.db.execute(
            select(TaxonVernacularName)
            .where(TaxonVernacularName.taxon_id == taxon_id)
            .where(TaxonVernacularName.locale == locale)
            .where(TaxonVernacularName.source == source)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.name = name
            existing.is_primary = is_primary
            await self.db.flush()
            return existing

        vn = TaxonVernacularName(
            taxon_id=taxon_id,
            locale=locale,
            name=name,
            source=source,
            is_primary=is_primary,
        )
        self.db.add(vn)
        await self.db.flush()
        return vn
