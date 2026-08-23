"""Celery worker tasks for taxon management.

Tasks run outside FastAPI's async event loop, so async database calls are
executed via asyncio.run() in a sync Celery task context — the same pattern
used by ml_tasks.py.
"""

from __future__ import annotations

import asyncio
import logging

from echoroo.workers.celery_app import app
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)

# Delay between GBIF requests to avoid rate limiting (seconds)
_GBIF_REQUEST_DELAY = 0.15

# Number of consecutive GBIF upstream failures that mark the service as "down
# hard". Once this many vernacular fetches raise back-to-back, the batch task
# re-raises so the Celery task state becomes FAILURE instead of reporting a
# completed run where every taxon was actually errored.
_GBIF_OUTAGE_THRESHOLD = 5

# COL XR dispatch sizing. Mirrors the service-side constants (imported lazily
# there to keep the slim API image free of the worker dependency tree) and the
# ``le=2000`` bound on the admin request schema: at ~0.35s/taxon a 2000-row
# dispatch is ~12 min, inside the 900s hard / 840s soft task limit.
_COL_XR_DEFAULT_BATCH_SIZE = 500
_COL_XR_MAX_BATCH_SIZE = 2000


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------


async def _run_seed_birdnet_taxa() -> dict[str, object]:
    """Async implementation of BirdNET taxa seeding."""
    from echoroo.services.taxon_seeder import seed_birdnet_taxa

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            created = await seed_birdnet_taxa(db)
            await db.commit()
        return {"status": "completed", "created": created}
    finally:
        await engine.dispose()


async def _run_load_bundled_vernacular_names() -> dict[str, object]:
    """Async implementation of the bundled vernacular-name load."""
    from echoroo.services.vernacular_bundle import load_bundled_ja_names

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            result = await load_bundled_ja_names(db)
            await db.commit()
        return {
            "status": "completed",
            "matched_taxa": result.matched_taxa,
            "inserted": result.inserted,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "unmatched_names": result.unmatched_names,
        }
    finally:
        await engine.dispose()


async def _run_resolve_gbif_batch(batch_size: int) -> dict[str, object]:
    """Async implementation of GBIF batch resolution."""
    from echoroo.repositories.taxon import TaxonRepository
    from echoroo.services.taxon import TaxonService

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            repo = TaxonRepository(db)
            service = TaxonService(taxon_repo=repo)
            batch_result = await service.resolve_gbif_batch(limit=batch_size)
            await db.commit()
        return {
            "status": "completed",
            "resolved": batch_result.resolved,
            "taxa_errored": batch_result.errored,
        }
    finally:
        await engine.dispose()


async def _run_resolve_col_xr_batch(
    batch_size: int, force: bool
) -> dict[str, object]:
    """Async implementation of Catalogue of Life XR identity resolution."""
    from echoroo.services.taxon import resolve_col_xr_batch

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            result = await resolve_col_xr_batch(
                db, batch_size=batch_size, force=force
            )
            await db.commit()
        return {"status": "completed", **result}
    finally:
        await engine.dispose()


async def _run_fetch_vernacular_names_batch(
    batch_size: int,
    locales: list[str] | None,
    skip_existing: bool = True,
) -> dict[str, object]:
    """Async implementation of vernacular names fetching from GBIF.

    Args:
        batch_size: Maximum number of taxa to process.
        locales: Locale codes to fetch (e.g. ["ja", "en"]). None = all.
        skip_existing: When True, skip taxa that already have vernacular names
                       for *all* requested locales.
    """
    from sqlalchemy import select

    from echoroo.core.exceptions import ExternalServiceError
    from echoroo.models.taxon import Taxon
    from echoroo.models.taxon_vernacular_name import TaxonVernacularName
    from echoroo.repositories.taxon import TaxonRepository
    from echoroo.services.gbif import GBIFService

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        async with session_factory() as db:
            # Fetch resolved taxa that have a GBIF key
            result = await db.execute(
                select(Taxon)
                .where(Taxon.gbif_taxon_key.isnot(None))
                .where(Taxon.is_non_biological.is_(False))
                .order_by(Taxon.gbif_resolved_at.asc())
                .limit(batch_size)
            )
            taxa = list(result.scalars().all())

        total = len(taxa)
        fetched_count = 0
        skipped_count = 0
        errored_count = 0
        consecutive_errors = 0
        gbif_service = GBIFService()

        for idx, taxon in enumerate(taxa, start=1):
            if taxon.gbif_taxon_key is None:
                skipped_count += 1
                continue

            # Skip taxa that already have names for all requested locales
            if skip_existing and locales:
                async with session_factory() as db:
                    existing_result = await db.execute(
                        select(TaxonVernacularName.locale)
                        .where(TaxonVernacularName.taxon_id == taxon.id)
                        .where(TaxonVernacularName.locale.in_(locales))
                    )
                    existing_locales = {row[0] for row in existing_result.all()}

                if existing_locales.issuperset(set(locales)):
                    skipped_count += 1
                    logger.debug(
                        "Skipping taxon %s — already has names for all locales %s",
                        taxon.scientific_name,
                        locales,
                    )
                    continue

            if idx % 50 == 0 or idx == total:
                logger.info("Processed %d/%d taxa", idx, total)

            try:
                vernacular_names = await gbif_service.get_vernacular_names(
                    taxon_key=taxon.gbif_taxon_key,
                    locales=locales,
                )
                consecutive_errors = 0
            except ExternalServiceError:
                # GBIF upstream failed — count as errored (not "no name found")
                # and bail out entirely if it looks like a hard outage.
                errored_count += 1
                consecutive_errors += 1
                logger.warning(
                    "GBIF upstream unavailable fetching vernacular names for "
                    "taxon %s (key=%s); consecutive_errors=%d",
                    taxon.scientific_name,
                    taxon.gbif_taxon_key,
                    consecutive_errors,
                )
                if consecutive_errors >= _GBIF_OUTAGE_THRESHOLD:
                    logger.error(
                        "Aborting vernacular names fetch after %d consecutive "
                        "GBIF failures; treating as hard outage",
                        consecutive_errors,
                    )
                    raise
                await asyncio.sleep(_GBIF_REQUEST_DELAY)
                continue

            # Throttle between GBIF API calls
            await asyncio.sleep(_GBIF_REQUEST_DELAY)

            if not vernacular_names:
                logger.debug(
                    "No vernacular names found for taxon %s (key=%s, locales=%s)",
                    taxon.scientific_name,
                    taxon.gbif_taxon_key,
                    locales,
                )
                continue

            async with session_factory() as db:
                repo = TaxonRepository(db)
                for vn_data in vernacular_names:
                    await repo.add_vernacular_name(
                        taxon_id=taxon.id,
                        locale=vn_data["locale"],
                        name=vn_data["name"],
                        source="gbif",
                        is_primary=False,
                    )
                await db.commit()

            fetched_count += 1
            logger.debug(
                "Fetched %d vernacular names for taxon %s (key=%s)",
                len(vernacular_names),
                taxon.scientific_name,
                taxon.gbif_taxon_key,
            )

        logger.info(
            "Vernacular names fetch complete: %d taxa updated, %d skipped, "
            "%d errored (total=%d)",
            fetched_count,
            skipped_count,
            errored_count,
            total,
        )
        return {
            "status": "completed",
            "taxa_updated": fetched_count,
            "taxa_skipped": skipped_count,
            "taxa_errored": errored_count,
            "taxa_total": total,
        }
    finally:
        await engine.dispose()


async def _run_fetch_japanese_vernacular_names(  # pyright: ignore[reportUnusedFunction]
    batch_size: int,
) -> dict[str, object]:
    """Async implementation: fetch Japanese vernacular names for all resolved taxa.

    Iterates over *all* taxa with a GBIF key (not just a single batch) and
    requests Japanese (ja) vernacular names from GBIF.  Taxa that already have
    a Japanese name stored in the database are skipped to avoid redundant API
    calls.

    Args:
        batch_size: Number of taxa to load from the database per page.  The
                    task continues until all qualifying taxa have been processed.
    """
    from sqlalchemy import func, select

    from echoroo.core.exceptions import ExternalServiceError
    from echoroo.models.taxon import Taxon
    from echoroo.models.taxon_vernacular_name import TaxonVernacularName
    from echoroo.repositories.taxon import TaxonRepository
    from echoroo.services.gbif import GBIFService

    engine, session_factory = get_worker_engine_and_session_factory()
    try:
        # Count total qualifying taxa upfront for progress logging
        async with session_factory() as db:
            count_result = await db.execute(
                select(func.count())
                .select_from(Taxon)
                .where(Taxon.gbif_taxon_key.isnot(None))
                .where(Taxon.is_non_biological.is_(False))
            )
            total_taxa: int = count_result.scalar_one()

        logger.info(
            "Starting Japanese vernacular name fetch for %d qualifying taxa",
            total_taxa,
        )

        gbif_service = GBIFService()
        processed = 0
        fetched_count = 0
        skipped_count = 0
        errored_count = 0
        consecutive_errors = 0
        offset = 0

        while True:
            async with session_factory() as db:
                result = await db.execute(
                    select(Taxon)
                    .where(Taxon.gbif_taxon_key.isnot(None))
                    .where(Taxon.is_non_biological.is_(False))
                    .order_by(Taxon.id.asc())
                    .offset(offset)
                    .limit(batch_size)
                )
                taxa_page = list(result.scalars().all())

            if not taxa_page:
                break

            for taxon in taxa_page:
                processed += 1

                if taxon.gbif_taxon_key is None:
                    skipped_count += 1
                    continue

                # Skip if the taxon already has a Japanese vernacular name
                async with session_factory() as db:
                    existing_result = await db.execute(
                        select(TaxonVernacularName.id)
                        .where(TaxonVernacularName.taxon_id == taxon.id)
                        .where(TaxonVernacularName.locale == "ja")
                        .limit(1)
                    )
                    if existing_result.scalar_one_or_none() is not None:
                        skipped_count += 1
                        logger.debug(
                            "Skipping %s — Japanese name already exists",
                            taxon.scientific_name,
                        )
                        continue

                try:
                    vernacular_names = await gbif_service.get_vernacular_names(
                        taxon_key=taxon.gbif_taxon_key,
                        locales=["ja"],
                    )
                    consecutive_errors = 0
                except ExternalServiceError:
                    # GBIF upstream failed — count as errored (not "no name
                    # found") and abort on a sustained outage.
                    errored_count += 1
                    consecutive_errors += 1
                    logger.warning(
                        "GBIF upstream unavailable fetching ja name for "
                        "%s (key=%s); consecutive_errors=%d",
                        taxon.scientific_name,
                        taxon.gbif_taxon_key,
                        consecutive_errors,
                    )
                    if consecutive_errors >= _GBIF_OUTAGE_THRESHOLD:
                        logger.error(
                            "Aborting Japanese vernacular fetch after %d "
                            "consecutive GBIF failures; treating as hard outage",
                            consecutive_errors,
                        )
                        raise
                    await asyncio.sleep(_GBIF_REQUEST_DELAY)
                    continue

                # Throttle between GBIF API calls
                await asyncio.sleep(_GBIF_REQUEST_DELAY)

                if not vernacular_names:
                    logger.debug(
                        "No Japanese name found for %s (key=%s)",
                        taxon.scientific_name,
                        taxon.gbif_taxon_key,
                    )
                    continue

                async with session_factory() as db:
                    repo = TaxonRepository(db)
                    for vn_data in vernacular_names:
                        await repo.add_vernacular_name(
                            taxon_id=taxon.id,
                            locale="ja",
                            name=vn_data["name"],
                            source="gbif",
                            is_primary=False,
                        )
                    await db.commit()

                fetched_count += 1
                logger.debug(
                    "Saved %d Japanese name(s) for %s",
                    len(vernacular_names),
                    taxon.scientific_name,
                )

                if processed % 50 == 0:
                    logger.info(
                        "Progress: %d/%d taxa processed (%d updated, %d skipped)",
                        processed,
                        total_taxa,
                        fetched_count,
                        skipped_count,
                    )

            offset += batch_size

        logger.info(
            "Japanese vernacular name fetch complete: "
            "%d updated, %d skipped, %d errored, %d total processed",
            fetched_count,
            skipped_count,
            errored_count,
            processed,
        )
        return {
            "status": "completed",
            "taxa_updated": fetched_count,
            "taxa_skipped": skipped_count,
            "taxa_errored": errored_count,
            "taxa_total": processed,
        }
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Celery task definitions
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.taxon_tasks.seed_birdnet_taxa",
    time_limit=300,      # 5 min hard limit
    soft_time_limit=270,  # 4.5 min soft limit
)
def seed_birdnet_taxa() -> dict[str, object]:
    """Seed BirdNET taxa into the database.

    Reads the BirdNET species list and inserts any taxa not already present
    in the taxa table.  The operation is idempotent.

    Returns:
        Dict with ``status`` and ``created`` (number of newly inserted taxa).
    """
    logger.info("Starting BirdNET taxa seeding task")
    try:
        result: dict[str, object] = asyncio.run(_run_seed_birdnet_taxa())
        logger.info("BirdNET taxa seeding complete: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("BirdNET taxa seeding failed: %s", exc)
        raise


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.taxon_tasks.load_bundled_vernacular_names",
    time_limit=300,      # 5 min hard limit
    soft_time_limit=270,  # 4.5 min soft limit
)
def load_bundled_vernacular_names() -> dict[str, object]:
    """Load the bundled Japanese vernacular names onto the local taxa.

    Reads the versioned IOC World Bird List bundle shipped inside the package
    (``echoroo.data.vernacular``) and upserts a ``ja`` / ``ioc`` row for every
    matching taxon, translating BirdNET's eBird/Clements scientific names via
    the packaged AviList crosswalk.  No network access is involved and the
    operation is idempotent — only names that actually changed are rewritten.

    ``seed_birdnet_taxa`` already performs this load, so this task exists for
    re-running after the bundle is regenerated from a newer upstream release.

    Returns:
        Dict with ``status`` plus the ``matched_taxa`` / ``inserted`` /
        ``updated`` / ``unchanged`` / ``unmatched_names`` counters.
    """
    logger.info("Starting bundled vernacular name load task")
    try:
        result: dict[str, object] = asyncio.run(
            _run_load_bundled_vernacular_names()
        )
        logger.info("Bundled vernacular name load complete: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Bundled vernacular name load failed: %s", exc)
        raise


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.taxon_tasks.resolve_gbif_batch",
    time_limit=600,      # 10 min hard limit
    soft_time_limit=570,  # 9.5 min soft limit
)
def resolve_gbif_batch(batch_size: int = 100) -> dict[str, object]:
    """Resolve GBIF data for unresolved taxa.

    Fetches GBIF classification metadata (taxon key, rank, kingdom/phylum/
    class/order/family/genus) for up to ``batch_size`` taxa that have not
    yet been resolved.

    Args:
        batch_size: Maximum number of taxa to resolve in this invocation.

    Returns:
        Dict with ``status`` and ``resolved`` (number of taxa resolved).
    """
    logger.info("Starting GBIF batch resolution task (batch_size=%d)", batch_size)
    try:
        result: dict[str, object] = asyncio.run(_run_resolve_gbif_batch(batch_size))
        logger.info("GBIF batch resolution complete: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("GBIF batch resolution failed: %s", exc)
        raise


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.taxon_tasks.resolve_col_xr_batch",
    time_limit=900,       # 15 min hard limit
    soft_time_limit=840,  # 14 min soft limit
)
def resolve_col_xr_batch(
    batch_size: int = _COL_XR_DEFAULT_BATCH_SIZE, force: bool = False
) -> dict[str, object]:
    """Resolve taxa against the Catalogue of Life XR checklist.

    GBIF's legacy backbone is frozen, so COL XR carries the re-matchable
    external identity of a taxon. For up to ``batch_size`` taxa this stores the
    COL usage key, the accepted usage key/name/rank, the usage status,
    authorships, the filtered classification, and the COL release the match was
    pinned to.

    Both selection modes are resumable, and progress is committed every 100
    taxa, so a dispatch that hits the time limit still banks its work:

    * without ``force``: biological taxa with no ``col_xr_resolved_at`` stamp;
    * with ``force``: biological taxa not yet stamped with the COL release this
      run is pinned to. Successive forced dispatches therefore ADVANCE through
      the catalogue rather than redoing the same first rows.

    Rejected matches (HIGHERRANK / NONE) are stamped with the release too —
    they are a resolved "no identity" at that release, not a pending row.

    ``batch_size`` is clamped to 2000: at the measured ~0.35s per taxon that is
    ~12 min, inside this task's 900s hard / 840s soft limit.

    Args:
        batch_size: Maximum number of taxa to resolve in this invocation
            (clamped to 1..2000).
        force: Re-resolve taxa whose release pin differs from the current COL
            release. Use after a release bump to refresh the catalogue.

    Returns:
        Dict with ``status`` plus ``processed`` / ``accepted`` / ``review`` /
        ``rejected`` / ``unavailable`` counters and the pinned ``release``.
    """
    effective_batch_size = min(max(batch_size, 1), _COL_XR_MAX_BATCH_SIZE)
    logger.info(
        "Starting COL XR resolution task (batch_size=%d, force=%s)",
        effective_batch_size,
        force,
    )
    try:
        result: dict[str, object] = asyncio.run(
            _run_resolve_col_xr_batch(effective_batch_size, force)
        )
        logger.info("COL XR resolution complete: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("COL XR resolution failed: %s", exc)
        raise


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.taxon_tasks.fetch_japanese_vernacular_names",
    time_limit=3600,       # 1 hour hard limit (may process thousands of taxa)
    soft_time_limit=3540,  # 59 min soft limit
)
def fetch_japanese_vernacular_names(
    batch_size: int = 100,
) -> dict[str, object]:
    """Fetch Japanese vernacular names (和名) from GBIF for all resolved taxa.

    Iterates over every taxon in the database that has a GBIF taxon key and is
    biological.  For each taxon, the GBIF vernacular names API is queried for
    Japanese (ja) names and the results are persisted.

    Taxa that already have at least one Japanese name stored are skipped to
    avoid redundant API calls.  A small inter-request delay is applied to
    respect GBIF rate limits.

    Args:
        batch_size: Number of taxa to load from the database per page during
                    the internal pagination loop (default 100).

    Returns:
        Dict with ``status``, ``taxa_updated``, ``taxa_skipped``, and
        ``taxa_total``.
    """
    logger.info(
        "Starting Japanese vernacular name fetch task (batch_size=%d)", batch_size
    )
    try:
        result: dict[str, object] = asyncio.run(
            _run_fetch_japanese_vernacular_names(batch_size)
        )
        logger.info("Japanese vernacular name fetch complete: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Japanese vernacular name fetch failed: %s", exc)
        raise


@app.task(  # type: ignore[untyped-decorator]
    name="echoroo.workers.taxon_tasks.fetch_vernacular_names_batch",
    time_limit=600,      # 10 min hard limit
    soft_time_limit=570,  # 9.5 min soft limit
)
def fetch_vernacular_names_batch(
    batch_size: int = 50,
    locales: list[str] | None = None,
    skip_existing: bool = True,
) -> dict[str, object]:
    """Fetch vernacular names from GBIF for resolved taxa.

    For each GBIF-resolved taxon (up to ``batch_size``), retrieves vernacular
    names and persists them via ``TaxonRepository.add_vernacular_name``.

    Args:
        batch_size: Maximum number of taxa to process in this invocation.
        locales: Optional list of ISO 639-1 locale codes to filter
                 (e.g. ``["en", "ja"]``).  If ``None``, all available
                 locales are fetched.
        skip_existing: When True (default), skip taxa that already have
                       names for all requested locales.

    Returns:
        Dict with ``status``, ``taxa_updated``, ``taxa_skipped``, and
        ``taxa_total``.
    """
    logger.info(
        "Starting vernacular names fetch task (batch_size=%d, locales=%s, skip_existing=%s)",
        batch_size,
        locales,
        skip_existing,
    )
    try:
        result: dict[str, object] = asyncio.run(
            _run_fetch_vernacular_names_batch(batch_size, locales, skip_existing)
        )
        logger.info("Vernacular names fetch complete: %s", result)
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("Vernacular names fetch failed: %s", exc)
        raise
