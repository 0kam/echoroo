"""Internal helper functions for the search API.

Contains utility functions used by multiple search sub-modules:
- Vernacular name resolution via GBIF
- Search result locale enrichment
- Similarity value clamping
- Annotation ORM -> response schema conversion
"""

from __future__ import annotations

import logging
import uuid as uuid_module

from sqlalchemy import String, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from echoroo.core.database import DbSession
from echoroo.models.annotation import Annotation
from echoroo.schemas.detection import DetectionResponse
from echoroo.schemas.search import (
    BatchSearchResponse,
    SpeciesMatchResult,
)

logger = logging.getLogger(__name__)


async def _resolve_vernacular_via_gbif(
    scientific_name: str,
    locale: str,
    db: DbSession,
) -> str | None:
    """Resolve vernacular name for a species not found in the local taxa table.

    Performs the following steps:
    1. Match the scientific name via GBIF /species/match to get a usageKey.
    2. Fetch vernacular names via GBIF /species/{key}/vernacularNames.
    3. Insert the taxon and its vernacular names into the local database for
       future lookups (so subsequent searches are fast).

    Args:
        scientific_name: Canonical scientific name to look up.
        locale: Locale code (e.g. "ja", "en").
        db: Database session for caching the resolved taxon.

    Returns:
        The vernacular name in the requested locale, or None if not found.
    """
    import datetime

    from echoroo.models.taxon import Taxon
    from echoroo.models.taxon_vernacular_name import TaxonVernacularName
    from echoroo.services.gbif import GBIFService

    # Outer guard: any unexpected failure (network, async/greenlet mismatch,
    # SQLAlchemy state error) must degrade to "no vernacular name" rather than
    # propagate a 500 to the API caller. Routes that call this function expect
    # a best-effort enrichment, not a hard dependency.
    try:
        gbif = GBIFService()

        # Step 1: resolve scientific name to GBIF taxon key
        resolve_result = await gbif.resolve_taxon(scientific_name)
        if resolve_result is None:
            logger.debug("GBIF could not resolve scientific name=%r", scientific_name)
            return None

        taxon_key = resolve_result.taxon_key
        logger.debug("GBIF resolved %r -> taxon_key=%d", scientific_name, taxon_key)

        # Step 2: fetch vernacular names from GBIF
        vernacular_entries = await gbif.get_vernacular_names(taxon_key)
        logger.debug(
            "GBIF vernacular names for key=%d: %d entries", taxon_key, len(vernacular_entries)
        )

        # Step 3: persist to local DB for future lookups
        try:
            taxon = Taxon(
                scientific_name=resolve_result.scientific_name,
                gbif_taxon_key=taxon_key,
                rank=resolve_result.rank,
                gbif_metadata=resolve_result.metadata,
                gbif_resolved_at=datetime.datetime.now(datetime.UTC),
            )
            db.add(taxon)
            await db.flush()  # populate taxon.id

            for entry in vernacular_entries:
                vn = TaxonVernacularName(
                    taxon_id=taxon.id,
                    locale=entry["locale"],
                    name=entry["name"],
                    source="gbif",
                    is_primary=False,
                )
                db.add(vn)

            await db.commit()
            logger.debug(
                "Cached taxon %r (id=%s) with %d vernacular names",
                scientific_name,
                taxon.id,
                len(vernacular_entries),
            )
        except Exception:
            # If insertion fails (e.g. race condition / duplicate), roll back and continue
            try:
                await db.rollback()
            except Exception:
                logger.debug(
                    "Rollback after cache failure for %r also failed; continuing",
                    scientific_name,
                    exc_info=True,
                )
            logger.debug(
                "Could not cache taxon for %r (may already exist); continuing without caching",
                scientific_name,
            )

        # Find the requested locale in vernacular_entries (resolved just above)
        for entry in vernacular_entries:
            if entry["locale"] == locale:
                return entry["name"]
    except Exception:
        logger.warning(
            "Unexpected error resolving vernacular name for %r via GBIF; "
            "returning None (caller will fall back to scientific name)",
            scientific_name,
            exc_info=True,
        )
        return None

    return None


async def _enrich_species_config_with_locale(
    species_config: list[object],
    locale: str,
    db: DbSession,
) -> list[object]:
    """Enrich species_config common names with locale-specific vernacular names.

    Collects all scientific names from the species_config, batch-queries the
    taxa and taxon_vernacular_names tables for locale-specific names, and
    returns an updated species_config list with enriched common_name fields.

    For English locale, also looks up common names from the tags table when
    species_config doesn't already have a common_name set.

    Falls back to a GBIF API call for species not yet cached locally.

    Args:
        species_config: List of species config dicts (from session.species_config)
        locale: Locale code (e.g. "en", "ja")
        db: Database session

    Returns:
        Updated species_config list with locale-enriched common_name fields
    """
    if not species_config:
        return species_config

    # Collect scientific names and tag_ids for batch lookup
    sci_names: list[str] = []
    tag_ids: list[str] = []
    for sp in species_config:
        if isinstance(sp, dict):
            name = sp.get("scientific_name")
            if name and isinstance(name, str):
                sci_names.append(name)
            tid = sp.get("tag_id")
            if tid and isinstance(tid, str):
                tag_ids.append(tid)

    if not sci_names:
        return species_config

    vernacular_by_sci: dict[str, str] = {}

    if locale == "en":
        # For English, look up common_name from tags table by tag_id
        if tag_ids:
            try:
                tag_ids_uuid = [uuid_module.UUID(tid) for tid in tag_ids]
                tag_sql = text(
                    """
                    SELECT t.id AS tag_id, t.common_name, t.scientific_name
                    FROM tags t
                    WHERE t.id = ANY(:tag_ids)
                    """
                ).bindparams(bindparam("tag_ids", value=tag_ids_uuid, type_=ARRAY(PGUUID())))
                rows = (await db.execute(tag_sql)).fetchall()
                for row in rows:
                    if row.common_name and row.scientific_name:
                        vernacular_by_sci[row.scientific_name] = row.common_name
            except Exception:
                logger.warning("English species_config common_name lookup failed", exc_info=True)

        # Also try taxon_vernacular_names for English (for species without tags)
        missing = [n for n in sci_names if n not in vernacular_by_sci]
        if missing:
            try:
                vn_sql = text(
                    """
                    SELECT tx.scientific_name, tvn.name
                    FROM taxa tx
                    JOIN taxon_vernacular_names tvn ON tvn.taxon_id = tx.id
                    WHERE tx.scientific_name = ANY(:sci_names)
                      AND tvn.locale = 'en'
                    ORDER BY tx.scientific_name, tvn.is_primary DESC
                    """
                ).bindparams(bindparam("sci_names", value=missing, type_=ARRAY(String())))
                rows = (await db.execute(vn_sql)).fetchall()
                for row in rows:
                    if row.scientific_name not in vernacular_by_sci:
                        vernacular_by_sci[row.scientific_name] = row.name
            except Exception:
                logger.warning("English vernacular name lookup failed", exc_info=True)
    else:
        # For non-English, query taxon_vernacular_names with the target locale
        taxa_vn_sql = text(
            """
            SELECT tx.scientific_name, tvn.name
            FROM taxa tx
            JOIN taxon_vernacular_names tvn ON tvn.taxon_id = tx.id
            WHERE tx.scientific_name = ANY(:sci_names)
              AND tvn.locale = :locale
            ORDER BY tx.scientific_name, tvn.is_primary DESC
            """
        ).bindparams(bindparam("sci_names", value=sci_names, type_=ARRAY(String())))
        try:
            rows = (await db.execute(taxa_vn_sql, {"locale": locale})).fetchall()
            for row in rows:
                if row.scientific_name not in vernacular_by_sci:
                    vernacular_by_sci[row.scientific_name] = row.name
        except Exception:
            logger.warning("species_config vernacular lookup failed", exc_info=True)

        # For species not found locally, try GBIF (one at a time, with caching)
        for sci_name in sci_names:
            if sci_name not in vernacular_by_sci:
                resolved = await _resolve_vernacular_via_gbif(sci_name, locale, db)
                if resolved:
                    vernacular_by_sci[sci_name] = resolved

    # Build enriched species_config
    enriched: list[object] = []
    for sp in species_config:
        if isinstance(sp, dict):
            sci_name = sp.get("scientific_name", "")
            if isinstance(sci_name, str) and sci_name in vernacular_by_sci:
                updated = dict(sp)
                updated["common_name"] = vernacular_by_sci[sci_name]
                enriched.append(updated)
            else:
                enriched.append(sp)
        else:
            enriched.append(sp)

    return enriched


async def _enrich_search_results_with_locale(
    response: BatchSearchResponse,
    locale: str,
    db: DbSession,
) -> BatchSearchResponse:
    """Enrich batch search results with locale-specific vernacular names.

    For each species in the results, looks up the tag by tag_id, finds its
    taxon_id, then queries TaxonVernacularName for a locale-specific common name.
    Falls back to the stored common_name if no vernacular name is found.

    For species with no tag_id (e.g. searched directly from GBIF without being
    detected by BirdNET), falls back to a direct taxa table lookup by scientific
    name, and finally to a live GBIF API call if the taxon is not yet cached
    locally.  The GBIF result is persisted for future lookups.

    Uses a single batch query to avoid N+1 database calls.

    Note: asyncpg does not support inline PostgreSQL type casts (e.g. ``::uuid[]``)
    in parameterised queries.  We use ``bindparam(..., type_=ARRAY(PGUUID()))``
    so that SQLAlchemy emits the correct ``$1::UUID[]`` syntax at the driver level.

    Args:
        response: Batch search response to enrich
        locale: Locale code (e.g. "en", "ja")
        db: Database session

    Returns:
        New BatchSearchResponse with common_name fields enriched for the locale
    """
    if locale == "en":
        # common_name is already stored in English; nothing to enrich.
        logger.debug("Skipping locale enrichment: locale=en")
        return response

    # Collect all tag_ids from results (skip None values)
    tag_id_strings = [v.tag_id for v in response.results.values() if v.tag_id is not None]
    logger.debug(
        "Locale enrichment requested for locale=%r, found %d tag_ids: %s",
        locale,
        len(tag_id_strings),
        tag_id_strings,
    )

    # -----------------------------------------------------------------------
    # Phase 1: tag_id -> taxon_id -> vernacular lookup (existing detected species)
    # -----------------------------------------------------------------------
    taxon_id_by_tag: dict[str, str | None] = {}
    fallback_common_name_by_tag: dict[str, str | None] = {}

    if tag_id_strings:
        # Convert string tag_ids to UUID objects for proper asyncpg binding
        try:
            tag_ids_uuid = [uuid_module.UUID(tid) for tid in tag_id_strings]
        except ValueError:
            logger.warning(
                "Could not parse one or more tag_ids as UUID; skipping enrichment. tag_ids=%s",
                tag_id_strings,
            )
            return response

        # Batch fetch tag -> taxon_id mapping.
        # asyncpg requires ARRAY(PGUUID()) binding — inline ::uuid[] cast is not supported.
        tag_sql = text(
            """
            SELECT t.id AS tag_id, t.common_name, tx.id AS taxon_id
            FROM tags t
            LEFT JOIN taxa tx ON t.taxon_id = tx.id
            WHERE t.id = ANY(:tag_ids)
            """
        ).bindparams(bindparam("tag_ids", value=tag_ids_uuid, type_=ARRAY(PGUUID())))
        tag_rows = (await db.execute(tag_sql)).fetchall()
        logger.debug(
            "Tag query returned %d rows for %d requested tag_ids",
            len(tag_rows),
            len(tag_ids_uuid),
        )

        for row in tag_rows:
            tag_id_str = str(row.tag_id)
            taxon_id_by_tag[tag_id_str] = str(row.taxon_id) if row.taxon_id else None
            fallback_common_name_by_tag[tag_id_str] = row.common_name

    # Batch fetch vernacular names for all taxon IDs found via tags
    taxon_id_strings = [tid for tid in taxon_id_by_tag.values() if tid is not None]
    vernacular_by_taxon: dict[str, str] = {}
    if taxon_id_strings:
        taxon_ids_uuid = [uuid_module.UUID(tid) for tid in taxon_id_strings]
        vn_sql = text(
            """
            SELECT taxon_id, name
            FROM taxon_vernacular_names
            WHERE taxon_id = ANY(:taxon_ids)
              AND locale = :locale
            ORDER BY taxon_id, is_primary DESC
            """
        ).bindparams(bindparam("taxon_ids", value=taxon_ids_uuid, type_=ARRAY(PGUUID())))
        vn_rows = (await db.execute(vn_sql, {"locale": locale})).fetchall()
        logger.debug(
            "Vernacular name query returned %d rows for locale=%r, taxon_count=%d",
            len(vn_rows),
            locale,
            len(taxon_ids_uuid),
        )
        # Keep first (highest priority) per taxon_id
        for row in vn_rows:
            taxon_id_str = str(row.taxon_id)
            if taxon_id_str not in vernacular_by_taxon:
                vernacular_by_taxon[taxon_id_str] = row.name
    else:
        logger.debug("No taxon_ids found for the given tag_ids; vernacular lookup skipped")

    logger.debug(
        "Vernacular names resolved: %d/%d taxon_ids have a %r name",
        len(vernacular_by_taxon),
        len(taxon_id_strings),
        locale,
    )

    # -----------------------------------------------------------------------
    # Phase 2: For species still missing a locale name, try taxa by scientific_name
    # -----------------------------------------------------------------------
    # Build set of scientific names that need further enrichment:
    # - no tag_id (GBIF-only species), OR
    # - tag_id present but no vernacular name found above
    sci_names_needing_enrichment: set[str] = set()
    for species_result in response.results.values():
        tag_id = species_result.tag_id
        if tag_id is None:
            sci_names_needing_enrichment.add(species_result.scientific_name)
        else:
            taxon_id = taxon_id_by_tag.get(tag_id)
            if taxon_id is None or taxon_id not in vernacular_by_taxon:
                sci_names_needing_enrichment.add(species_result.scientific_name)

    vernacular_by_sci_name: dict[str, str] = {}
    if sci_names_needing_enrichment:
        # Look up taxa by scientific_name and join vernacular names in one query
        sci_name_list = list(sci_names_needing_enrichment)
        taxa_vn_sql = text(
            """
            SELECT tx.scientific_name, tvn.taxon_id, tvn.name
            FROM taxa tx
            JOIN taxon_vernacular_names tvn ON tvn.taxon_id = tx.id
            WHERE tx.scientific_name = ANY(:sci_names)
              AND tvn.locale = :locale
            ORDER BY tx.scientific_name, tvn.is_primary DESC
            """
        ).bindparams(bindparam("sci_names", value=sci_name_list, type_=ARRAY(String())))
        try:
            taxa_vn_rows = (await db.execute(taxa_vn_sql, {"locale": locale})).fetchall()
        except Exception:
            logger.warning("taxa vernacular name lookup failed", exc_info=True)
            taxa_vn_rows = []

        for row in taxa_vn_rows:
            sci = row.scientific_name
            if sci not in vernacular_by_sci_name:
                vernacular_by_sci_name[sci] = row.name

        logger.debug(
            "Direct taxa lookup resolved %d/%d scientific names for locale=%r",
            len(vernacular_by_sci_name),
            len(sci_names_needing_enrichment),
            locale,
        )

        # Phase 3: For species still not resolved, call GBIF API and cache results
        still_unresolved = sci_names_needing_enrichment - vernacular_by_sci_name.keys()
        for sci_name in still_unresolved:
            logger.debug(
                "Falling back to GBIF API for locale=%r enrichment of %r", locale, sci_name
            )
            resolved = await _resolve_vernacular_via_gbif(sci_name, locale, db)
            if resolved:
                vernacular_by_sci_name[sci_name] = resolved
                logger.debug("GBIF resolved %r -> %r in locale=%r", sci_name, resolved, locale)
            else:
                logger.debug("GBIF could not provide %r name for %r", locale, sci_name)

    # -----------------------------------------------------------------------
    # Rebuild results with enriched common names
    # -----------------------------------------------------------------------
    enriched_results: dict[str, SpeciesMatchResult] = {}
    for key, species_result in response.results.items():
        tag_id = species_result.tag_id
        resolved_name: str | None

        if tag_id is not None:
            taxon_id = taxon_id_by_tag.get(tag_id)
            if taxon_id is not None and taxon_id in vernacular_by_taxon:
                resolved_name = vernacular_by_taxon[taxon_id]
                logger.debug(
                    "Enriched %r (%s) via tag->taxon -> %r",
                    species_result.scientific_name,
                    tag_id,
                    resolved_name,
                )
            else:
                # Try scientific name fallback (phase 2/3)
                resolved_name = (
                    vernacular_by_sci_name.get(species_result.scientific_name)
                    or fallback_common_name_by_tag.get(tag_id)
                    or species_result.common_name
                )
                logger.debug(
                    "No tag->taxon vernacular for %r; using sci_name/fallback %r",
                    species_result.scientific_name,
                    resolved_name,
                )
        else:
            # No tag_id: use scientific name lookup (phase 2/3)
            resolved_name = (
                vernacular_by_sci_name.get(species_result.scientific_name)
                or species_result.common_name
            )
            logger.debug(
                "No tag_id for %r; resolved via sci_name -> %r",
                species_result.scientific_name,
                resolved_name,
            )

        enriched_results[key] = SpeciesMatchResult(
            tag_id=species_result.tag_id,
            scientific_name=species_result.scientific_name,
            common_name=resolved_name,
            matches=species_result.matches,
        )

    return BatchSearchResponse(
        results=enriched_results,
        total_matches=response.total_matches,
        search_duration_ms=response.search_duration_ms,
    )


def _clamp_similarity_in_raw(raw: object) -> None:
    """Clamp similarity values in a Celery result dict to the valid [0.0, 1.0] range.

    pgvector cosine similarity can produce values slightly above 1.0 (e.g. 1.0000001)
    due to floating-point rounding.  ``SimilarityResult.similarity`` has a ``le=1.0``
    constraint, so we clamp in-place before passing the raw dict to ``model_validate``.

    Mutates *raw* directly; safe because the dict is a freshly-deserialized Celery result
    and is never reused elsewhere.

    Args:
        raw: The raw Celery task result dict to normalise.
    """
    if not isinstance(raw, dict):
        return
    results = raw.get("results")
    if not isinstance(results, dict):
        return
    for species_data in results.values():
        if not isinstance(species_data, dict):
            continue
        matches = species_data.get("matches")
        if not isinstance(matches, list):
            continue
        for match in matches:
            if isinstance(match, dict) and "similarity" in match:
                import contextlib
                with contextlib.suppress(TypeError, ValueError):
                    match["similarity"] = max(0.0, min(1.0, float(match["similarity"])))


def _annotation_to_detection_response(annotation: Annotation) -> DetectionResponse:
    """Convert an Annotation ORM instance to a DetectionResponse schema.

    Args:
        annotation: Annotation ORM instance with relationships loaded

    Returns:
        DetectionResponse schema instance
    """
    from echoroo.schemas.tag import TagResponse

    tag_resp = None
    if annotation.tag is not None:
        tag_resp = TagResponse.model_validate(annotation.tag)

    return DetectionResponse(
        id=annotation.id,
        recording_id=annotation.recording_id,
        tag_id=annotation.tag_id,
        detection_run_id=annotation.detection_run_id,
        source=annotation.source,
        status=annotation.status,
        confidence=annotation.confidence,
        start_time=annotation.start_time,
        end_time=annotation.end_time,
        freq_low=annotation.freq_low,
        freq_high=annotation.freq_high,
        reviewed_by_id=annotation.reviewed_by_id,
        reviewed_at=annotation.reviewed_at,
        created_at=annotation.created_at,
        updated_at=annotation.updated_at,
        tag=tag_resp,
    )
