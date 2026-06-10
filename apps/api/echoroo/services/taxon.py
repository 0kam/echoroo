"""Taxon service for business logic."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError

from echoroo.core.pagination import paginate
from echoroo.models.taxon import Taxon
from echoroo.repositories.taxon import TaxonRepository, normalize_locale
from echoroo.schemas.taxon import (
    TaxonDetailResponse,
    TaxonListResponse,
    TaxonResponse,
    TaxonSearchResult,
    VernacularNameResponse,
)
from echoroo.services.gbif import GBIFService
from echoroo.services.vernacular import resolve_vernacular_names

logger = logging.getLogger(__name__)


def _en_common_name_for_seed(
    common_name: str | None,
    locale: str,
    vernacular_names: list[dict[str, str | None]] | None,
) -> str | None:
    """Derive the value to seed into the legacy/en ``common_name`` slot.

    The legacy ``common_name`` is persisted by
    ``get_or_create_by_scientific_name`` as an English (``locale="en"``)
    vernacular row. The client, however, sends ``common_name`` as the
    locale-RESOLVED display name (e.g. a Japanese 和名 under a ``ja`` UI), so
    passing it through verbatim would pollute the en slot with a non-English
    string. This helper decouples the two:

    * When language-tagged ``vernacular_names`` are provided, prefer their
      ``en`` entry (language normalized) as the authoritative English name.
    * When the requested ``locale`` is English (or no ``vernacular_names`` are
      provided), keep the existing behaviour and use the client's
      ``common_name`` directly (backward compatible).
    * Otherwise (non-en locale, no ``en`` entry available) return ``None`` so
      no en row is fabricated from a non-English display name. The scientific
      name remains the floor and the correct locale rows are persisted by
      ``persist_vernacular_names``.
    """
    # Prefer an explicit ``en`` entry from the language-tagged list, whatever
    # the requested display locale. This is the authoritative English name.
    if vernacular_names:
        for entry in vernacular_names:
            raw_name = entry.get("name")
            raw_lang = entry.get("language")
            if not raw_name or not raw_lang:
                continue
            if normalize_locale(str(raw_lang)) == "en":
                name = str(raw_name).strip()
                if name:
                    return name

    # English UI (or no language-tagged list): the client's locale-resolved
    # name IS English, so it is safe to seed it directly (legacy behaviour).
    if normalize_locale(locale or "en") == "en":
        return common_name

    # Non-en locale with no en entry: do not fabricate an en row from a
    # non-English display name.
    return None


class TaxonService:
    """Service for taxon management."""

    def __init__(
        self,
        taxon_repo: TaxonRepository,
        gbif_service: GBIFService | None = None,
    ) -> None:
        self.taxon_repo = taxon_repo
        self.gbif_service = gbif_service or GBIFService()

    async def list_taxa(
        self,
        search: str | None = None,
        is_non_biological: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> TaxonListResponse:
        pagination = paginate(page, page_size)

        taxa, total = await self.taxon_repo.list_taxa(
            search=search,
            is_non_biological=is_non_biological,
            page=pagination.page,
            page_size=pagination.page_size,
        )

        return TaxonListResponse(
            items=[TaxonResponse.model_validate(t) for t in taxa],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=pagination.total_pages(total),
        )

    async def get_detail(self, taxon_id: UUID) -> TaxonDetailResponse:
        taxon = await self.taxon_repo.get_by_id(taxon_id)
        if not taxon:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Taxon not found",
            )

        return TaxonDetailResponse(
            **TaxonResponse.model_validate(taxon).model_dump(),
            gbif_metadata=taxon.gbif_metadata,
            gbif_resolved_at=taxon.gbif_resolved_at,
            vernacular_names=[
                VernacularNameResponse.model_validate(vn)
                for vn in taxon.vernacular_names
            ],
            updated_at=taxon.updated_at,
        )

    async def search(
        self,
        query: str,
        locale: str | None = None,
        limit: int = 20,
    ) -> list[TaxonSearchResult]:
        """Search taxa, resolving each result's display ``common_name``.

        Matching is locale-agnostic (an English-name query still works under a
        ``ja`` UI). The ``locale`` argument controls only the display name:
        each result's ``common_name`` is resolved with a requested-locale →
        English fallback chain. When no vernacular row exists in either the
        requested locale or English, ``common_name`` stays ``None`` (the
        scientific-name floor is applied by the frontend display formatter).
        """
        taxa = await self.taxon_repo.search(query, limit=limit)

        # Batch-resolve the display name for the requested locale (ja→en
        # fallback). Default to English when no locale is supplied.
        display_locale = locale or "en"
        common_names = await resolve_vernacular_names(
            self.taxon_repo.db,
            [taxon.id for taxon in taxa],
            display_locale,
        )

        return [
            TaxonSearchResult(
                id=taxon.id,
                scientific_name=taxon.scientific_name,
                gbif_taxon_key=taxon.gbif_taxon_key,
                rank=taxon.rank,
                is_non_biological=taxon.is_non_biological,
                common_name=common_names.get(taxon.id),
            )
            for taxon in taxa
        ]

    async def get_or_create(
        self,
        scientific_name: str,
        common_name: str | None = None,
        is_non_biological: bool = False,
    ) -> TaxonResponse:
        taxon = await self.taxon_repo.get_or_create_by_scientific_name(
            scientific_name=scientific_name,
            common_name=common_name,
            is_non_biological=is_non_biological,
        )
        return TaxonResponse.model_validate(taxon)

    async def create_from_gbif(
        self,
        scientific_name: str,
        gbif_taxon_key: int | None = None,
        common_name: str | None = None,
        locale: str = "en",
        vernacular_names: list[dict[str, str | None]] | None = None,
    ) -> TaxonSearchResult:
        """Materialise a GBIF search pick into a local taxon (idempotent).

        Get-or-creates the ``taxa`` row keyed by ``scientific_name`` (the
        unique business key). When a ``gbif_taxon_key`` is supplied and the
        taxon does not yet have one, the key is backfilled — but only if no
        other taxon already owns it, because ``ix_taxa_gbif_taxon_key`` is a
        partial-unique index (``WHERE gbif_taxon_key IS NOT NULL``). If the
        key is already owned elsewhere it is silently left unset rather than
        raising; the row is still returned so the caller can use it.

        Vernacular persistence: the legacy/en ``common_name`` slot is seeded
        from the AUTHORITATIVE English name, never from a non-English display
        value. The client sends ``common_name`` as the locale-RESOLVED display
        name (e.g. a 和名 under a ``ja`` UI), so the en seed is derived via
        :func:`_en_common_name_for_seed`: prefer the ``en`` entry of
        ``vernacular_names``; fall back to the client ``common_name`` only when
        the request locale is English; otherwise omit the en row entirely
        (rather than polluting it with a non-English string). In addition, any
        language-tagged ``vernacular_names`` are persisted with their REAL
        locale (``jpn`` normalized to ``ja``) and source, idempotently. When a
        non-English display locale is requested but no matching vernacular row
        ends up present and the taxon has a GBIF key, the existing async
        ja-fetch task is enqueued as a best-effort backfill (never blocking).

        The returned shape mirrors :meth:`search` (``TaxonSearchResult``) so
        the frontend can reuse the same type, including a locale-resolved
        ``common_name`` (requested locale → English fallback).
        """
        # Decouple the legacy/en ``common_name`` seed from the client's
        # locale-resolved display value so a non-English name (e.g. a ja 和名)
        # never lands in the en vernacular row. The authoritative English name
        # is taken from the ``en`` entry of ``vernacular_names`` when present.
        en_common_name = _en_common_name_for_seed(
            common_name, locale, vernacular_names
        )

        # ``get_or_create_by_scientific_name`` has already ``add``+``flush``ed
        # the taxon (no commit) when it is newly created, so the SAVEPOINT
        # below scopes only the subsequent key assignment.
        taxon = await self.taxon_repo.get_or_create_by_scientific_name(
            scientific_name=scientific_name,
            common_name=en_common_name,
        )

        # Backfill the GBIF key only when the taxon lacks one. Guard the
        # partial-unique constraint: skip the assignment when another taxon
        # already owns this key, and defensively catch a concurrent insert
        # that races past the pre-check.
        if gbif_taxon_key is not None and taxon.gbif_taxon_key is None:
            owner = await self.taxon_repo.get_by_gbif_taxon_key(gbif_taxon_key)
            if owner is None or owner.id == taxon.id:
                try:
                    # SAVEPOINT-scope BOTH the key assignment and its flush so
                    # a lost race for the unique key rolls back ONLY this
                    # assignment — never the just-created taxon (and its seeded
                    # en vernacular) living in the same uncommitted
                    # transaction. Assigning inside the savepoint lets the
                    # ROLLBACK TO SAVEPOINT discard the pending dirty attribute,
                    # so the next flush does not re-emit the failing UPDATE.
                    async with self.taxon_repo.db.begin_nested():
                        taxon.gbif_taxon_key = gbif_taxon_key
                        await self.taxon_repo.update(taxon)
                except IntegrityError:
                    # Lost the race for the unique key. ROLLBACK TO SAVEPOINT
                    # reverted the DB row and expired the ORM instance, leaving
                    # the surrounding transaction usable. Refresh the SAME
                    # taxon (the row still exists — never re-fetch a phantom)
                    # in the async context so its attributes — including the
                    # now-NULL gbif_taxon_key — are eagerly reloaded; this
                    # avoids a synchronous lazy-load (MissingGreenlet) when the
                    # response is built below.
                    await self.taxon_repo.db.refresh(taxon)

        # Persist any language-tagged vernacular names with their real locale
        # (idempotent). This is how a non-English 和名 resolved during the live
        # search gets stored as ``ja`` instead of being lost or mis-tagged.
        if vernacular_names:
            await self.taxon_repo.persist_vernacular_names(
                taxon.id, vernacular_names
            )

        # Normalize the requested display locale to its primary subtag so
        # ``ja-JP``/``JA`` resolve and gate like ``ja``.
        display_locale = normalize_locale(locale or "en")
        common_names = await resolve_vernacular_names(
            self.taxon_repo.db,
            [taxon.id],
            display_locale,
        )

        # Best-effort async backfill: when ja is requested and the taxon has a
        # GBIF key but NO locale-specific ja row exists yet, enqueue the existing
        # ja-fetch task rather than blocking the response. The previous condition
        # relied on ``resolve_vernacular_names`` whose en-fallback made the
        # "missing" check ~never true, so the task practically never fired; check
        # the absence of an EXACT ja row (no fallback) instead. Only fire for ja
        # (the task only fetches Japanese names). Failures to enqueue are
        # swallowed — display already degrades to English/scientific.
        if display_locale == "ja" and taxon.gbif_taxon_key is not None:
            try:
                has_ja = await self.taxon_repo.has_vernacular_in_locale(
                    taxon.id, "ja"
                )
            except Exception:  # noqa: BLE001 — backfill probe is best-effort
                logger.debug(
                    "ja vernacular presence check failed", exc_info=True
                )
                has_ja = True  # fail closed: do not spam the queue on error
            if not has_ja:
                self._maybe_enqueue_ja_fetch()

        return TaxonSearchResult(
            id=taxon.id,
            scientific_name=taxon.scientific_name,
            gbif_taxon_key=taxon.gbif_taxon_key,
            rank=taxon.rank,
            is_non_biological=taxon.is_non_biological,
            common_name=common_names.get(taxon.id),
        )

    @staticmethod
    def _maybe_enqueue_ja_fetch() -> None:
        """Enqueue the batch ja-vernacular fetch task, best-effort.

        There is no single-taxon fetch variant; the existing batch task skips
        taxa that already have a ja name, so enqueuing it backfills the newly
        materialized taxon without redundant work. Any import/dispatch failure
        is swallowed so the materialize response is never blocked.
        """
        try:
            from echoroo.workers.taxon_tasks import (  # noqa: PLC0415
                fetch_japanese_vernacular_names,
            )

            fetch_japanese_vernacular_names.delay()
        except Exception:  # noqa: BLE001 — backfill is best-effort
            logger.debug("Failed to enqueue ja vernacular fetch", exc_info=True)

    async def resolve_gbif_batch(self, limit: int = 100) -> int:
        """Resolve GBIF data for unresolved taxa. Returns count of resolved.

        Taxa are processed SEQUENTIALLY. ``resolve_one`` ends with a
        ``self.db.flush()`` (via ``taxon_repo.update``); running these
        concurrently on the single shared ``AsyncSession`` triggers
        ``InvalidRequestError: Session is already flushing`` because an
        ``AsyncSession`` is not safe for concurrent use. Concurrency also bought
        nothing here: the GBIF HTTP client is rate-limited per request, so the
        calls serialize regardless.

        Each taxon is resolved inside its own try/except so a single failing
        taxon (network/GBIF error, or a flush error from one row) does not abort
        the whole batch. A failed taxon is left unresolved and retried on the
        next batch run.
        """
        unresolved = await self.taxon_repo.get_unresolved(limit=limit)
        if not unresolved:
            return 0

        async def resolve_one(taxon: Taxon) -> bool:
            """Resolve a single taxon; return True if GBIF data was found."""
            result = await self.gbif_service.resolve_taxon(taxon.scientific_name)
            if result is None:
                taxon.gbif_resolved_at = datetime.now(UTC)
                await self.taxon_repo.update(taxon)
                return False

            taxon.gbif_taxon_key = result.taxon_key
            taxon.rank = result.rank
            taxon.gbif_metadata = result.metadata
            taxon.gbif_resolved_at = datetime.now(UTC)
            await self.taxon_repo.update(taxon)
            return True

        resolved_count = 0
        for taxon in unresolved:
            try:
                if await resolve_one(taxon):
                    resolved_count += 1
            except Exception:  # noqa: BLE001 — isolate one bad taxon from the batch
                logger.exception(
                    "Failed to resolve GBIF data for taxon %s (id=%s)",
                    taxon.scientific_name,
                    taxon.id,
                )
        return resolved_count
