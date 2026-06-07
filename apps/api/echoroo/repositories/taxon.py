"""Taxon repository for database operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.repositories.base import BaseRepository

# GBIF/ISO 639-3 → ISO 639-1 normalization for incoming vernacular locales.
# Mirrors the subset used by the materialize path; "jpn" → "ja" is the key one.
_LOCALE_NORMALIZE: dict[str, str] = {
    "jpn": "ja", "eng": "en", "deu": "de", "fra": "fr", "spa": "es",
    "ita": "it", "por": "pt", "nld": "nl", "swe": "sv", "fin": "fi",
    "dan": "da", "nor": "no", "pol": "pl", "rus": "ru", "zho": "zh",
    "kor": "ko",
}

# Allowed provenance values for a persisted vernacular name. Any unknown/empty
# value from a (client-supplied) payload is coerced to a safe default so an
# arbitrary string can never reach the ``source`` column.
_VERNACULAR_SOURCE_ALLOWED: frozenset[str] = frozenset(
    {"gbif", "inaturalist", "birdnet", "user"}
)
_VERNACULAR_SOURCE_DEFAULT = "gbif"

# Column length ceilings (mirror the model: name String(300), source String(20),
# locale String(10)). Inputs are guarded against these to avoid DB errors.
_VERNACULAR_NAME_MAX = 300
_VERNACULAR_LOCALE_MAX = 10


def normalize_locale(locale: str) -> str:
    """Normalize a locale to a lowercase primary-subtag ISO code.

    Two normalizations are applied so callers can pass any reasonable form:

    1. Strip a BCP-47 region/script suffix and lowercase the primary subtag,
       e.g. ``ja-JP`` / ``ja_JP`` / ``EN`` → ``ja`` / ``ja`` / ``en``.
    2. Collapse a 3-letter ISO 639-3/GBIF code to its 2-letter equivalent,
       e.g. ``jpn`` → ``ja``.

    Unknown codes are returned as their lowercased primary subtag unchanged.
    """
    # Take the primary subtag (text before the first '-' or '_') and lowercase.
    primary = locale.strip().split("-", 1)[0].split("_", 1)[0].lower()
    return _LOCALE_NORMALIZE.get(primary, primary)


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

    async def get_by_gbif_taxon_key(self, gbif_taxon_key: int) -> Taxon | None:
        """Return the taxon that owns a GBIF key, if any.

        Used to honour the partial-unique ``ix_taxa_gbif_taxon_key`` index
        (``WHERE gbif_taxon_key IS NOT NULL``) before backfilling a key onto
        another taxon.
        """
        result = await self.db.execute(
            select(Taxon).where(Taxon.gbif_taxon_key == gbif_taxon_key)
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

        Concurrency: the insert is wrapped in a SAVEPOINT so that a
        concurrent first-time create of the same ``scientific_name`` (which
        races the read-then-insert and trips the ``unique(scientific_name)``
        constraint on flush) rolls back only the savepoint and re-queries to
        return the row the winning transaction created — preserving
        get-OR-create semantics instead of surfacing a 500.
        """
        existing = await self.get_by_scientific_name(scientific_name)
        if existing is not None:
            return existing

        taxon = Taxon(
            scientific_name=scientific_name,
            is_non_biological=is_non_biological,
        )
        created = False
        try:
            async with self.db.begin_nested():
                self.db.add(taxon)
                await self.db.flush()
            created = True
        except IntegrityError:
            # Lost the race for the unique scientific_name — the savepoint is
            # rolled back, leaving the surrounding transaction usable. Return
            # the row the other transaction committed/flushed.
            refetched = await self.get_by_scientific_name(scientific_name)
            if refetched is not None:
                return refetched
            raise

        if created and common_name:
            # Only seed the en vernacular when THIS call created the row, so
            # the race-lost path never duplicates the vernacular insert.
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
        limit: int = 20,
    ) -> list[Taxon]:
        """Search taxa by scientific name or vernacular name.

        Matching is locale-agnostic: a taxon matches when its scientific name
        OR any of its vernacular names (in any locale) ILIKE the query. This
        keeps English-name searches working even when the UI requests a
        non-English display locale; the display name resolution is handled
        separately by the service layer.

        Returns the list of matching ``Taxon`` rows.
        """
        pattern = f"%{query}%"

        # Correlated EXISTS for vernacular name matches across ALL locales so
        # that, for example, an English-name search still surfaces the taxon
        # under a ``ja`` UI. EXISTS (rather than a JOIN) guarantees each taxon
        # is counted at most once even when several of its vernacular rows
        # (e.g. both a ``ja`` and an ``en`` row, or multiple sources) match the
        # query, so the ``limit`` counts distinct taxa instead of being
        # consumed by duplicate rows. The matched vernacular row itself is
        # intentionally not returned here — the display name is resolved by the
        # service using the requested locale (with ja→en fallback).
        vn_exists = (
            select(TaxonVernacularName.id)
            .where(
                TaxonVernacularName.taxon_id == Taxon.id,
                TaxonVernacularName.name.ilike(pattern),
            )
            .exists()
        )

        result = await self.db.execute(
            select(Taxon)
            .where(
                or_(
                    Taxon.scientific_name.ilike(pattern),
                    vn_exists,
                )
            )
            .order_by(Taxon.scientific_name.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

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

    async def has_vernacular_in_locale(self, taxon_id: UUID, locale: str) -> bool:
        """Return True when a taxon has a vernacular row in the EXACT locale.

        Unlike ``resolve_vernacular_names`` this performs NO English fallback —
        it answers "does a locale-specific row exist?" so the ja-backfill enqueue
        can fire only when a ``ja`` name is genuinely absent. The ``locale`` is
        normalized (``jpn``/``ja-JP`` → ``ja``) before the lookup.
        """
        normalized = normalize_locale(locale)
        result = await self.db.execute(
            select(TaxonVernacularName.id)
            .where(TaxonVernacularName.taxon_id == taxon_id)
            .where(TaxonVernacularName.locale == normalized)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def persist_vernacular_names(
        self,
        taxon_id: UUID,
        entries: list[dict[str, str | None]],
    ) -> int:
        """Idempotently persist language-tagged vernacular names for a taxon.

        Each entry is a dict with keys ``name``, ``language`` and optional
        ``source``. ``is_primary`` is left False (the English seed from the
        create path keeps its primary flag).

        Input hardening (the payload is client-supplied):
        * ``language`` is normalized to its primary lowercase subtag
          (``jpn``/``ja-JP``/``JA`` → ``ja``) and capped to the column length.
        * ``source`` is restricted to a known allow-set
          (``gbif``/``inaturalist``/``birdnet``/``user``); any unknown/empty
          value is coerced to the safe default ``gbif``.
        * ``name`` is trimmed and truncated to the column length to avoid DB
          errors on over-length input.

        Idempotency / constraint handling:
        * A row with the SAME ``(taxon_id, locale, name)`` is left untouched, so
          repeated materialize calls never duplicate a name.
        * The table has a UNIQUE ``(taxon_id, locale, source)`` constraint. When
          a row already exists for that triple it is INSERT-only / fill-only: a
          non-empty existing name is NEVER overwritten by the payload (prevents a
          stale or malicious overwrite); an empty existing name is filled in.

        Returns the number of rows newly inserted (fills/updates are not
        counted).
        """
        if not entries:
            return 0

        # Load existing rows for this taxon once so per-entry checks are O(1).
        existing_rows = (
            await self.db.execute(
                select(TaxonVernacularName).where(
                    TaxonVernacularName.taxon_id == taxon_id
                )
            )
        ).scalars().all()
        by_name: set[tuple[str, str]] = {
            (row.locale, row.name) for row in existing_rows
        }
        by_locale_source: dict[tuple[str, str], TaxonVernacularName] = {
            (row.locale, row.source): row for row in existing_rows
        }

        inserted = 0
        for entry in entries:
            raw_name = entry.get("name")
            raw_lang = entry.get("language")
            if not raw_name or not raw_lang:
                continue
            name = str(raw_name).strip()[:_VERNACULAR_NAME_MAX]
            locale = normalize_locale(str(raw_lang))[:_VERNACULAR_LOCALE_MAX]
            if not name or not locale:
                continue

            # Restrict source to the known allow-set; unknown/empty → default.
            raw_source = str(entry.get("source") or "").strip().lower()
            source = (
                raw_source
                if raw_source in _VERNACULAR_SOURCE_ALLOWED
                else _VERNACULAR_SOURCE_DEFAULT
            )

            if (locale, name) in by_name:
                continue  # exact name already present — nothing to do
            conflict = by_locale_source.get((locale, source))
            if conflict is not None:
                # A row already owns this (locale, source). Insert-only /
                # fill-only: keep a non-empty existing name (no overwrite from
                # the client payload); only fill an empty placeholder.
                if not (conflict.name or "").strip():
                    # Drop the stale (locale, "") key before re-keying by_name so
                    # the dedup set never reports a name that no longer exists.
                    by_name.discard((locale, conflict.name))
                    conflict.name = name
                    by_name.add((locale, name))
                continue

            row = TaxonVernacularName(
                taxon_id=taxon_id,
                locale=locale,
                name=name,
                source=source,
                is_primary=False,
            )
            self.db.add(row)
            by_name.add((locale, name))
            by_locale_source[(locale, source)] = row
            inserted += 1

        await self.db.flush()
        return inserted
