"""Species name resolution service using GBIF API with DB caching.

This module provides a service for resolving species names to GBIF taxon information,
including canonical names and vernacular (common) names. Features:

- Two-tier caching: in-memory + database for persistence across restarts
- Async parallel resolution for batch processing
- Rate limiting to respect GBIF API limits
- Non-species label detection to skip environmental sounds
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from echoroo.api.species import search_gbif_species
from echoroo.ml.constants import (
    GBIF_RATE_LIMIT_CALLS,
    GBIF_RATE_LIMIT_PERIOD,
    NON_SPECIES_LABELS,
    is_non_species_label,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "SpeciesInfo",
    "SpeciesResolver",
]

logger = logging.getLogger(__name__)


@dataclass
class SpeciesInfo:
    """GBIF resolved species information.

    Attributes
    ----------
    gbif_taxon_id : str | None
        GBIF taxon key (usage key) for this species, or None if not found.
    canonical_name : str
        Canonical scientific name. Falls back to the input name if GBIF lookup fails.
    vernacular_name : str | None
        Vernacular (common) name in the requested locale, or None if not available.
    """

    gbif_taxon_id: str | None
    canonical_name: str
    vernacular_name: str | None


class RateLimiter:
    """Simple rate limiter for API calls using a sliding window.

    Parameters
    ----------
    calls : int
        Maximum number of calls allowed per period. Default 10.
    period : float
        Time period in seconds. Default 1.0.
    """

    def __init__(
        self, calls: int = GBIF_RATE_LIMIT_CALLS, period: float = GBIF_RATE_LIMIT_PERIOD
    ):
        self._calls = calls
        self._period = period
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire rate limit slot, waiting if necessary."""
        async with self._lock:
            now = asyncio.get_event_loop().time()

            # Clean old timestamps
            self._timestamps = [
                t for t in self._timestamps if now - t < self._period
            ]

            if len(self._timestamps) >= self._calls:
                # Wait for oldest to expire
                sleep_time = self._period - (now - self._timestamps[0])
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                # Clean again after sleep
                now = asyncio.get_event_loop().time()
                self._timestamps = [
                    t for t in self._timestamps if now - t < self._period
                ]

            self._timestamps.append(asyncio.get_event_loop().time())


class SpeciesResolver:
    """GBIF API-based species name resolution service with DB caching.

    This service resolves scientific names to GBIF taxon information including
    canonical names and vernacular names. It uses a two-tier caching strategy:

    1. In-memory cache for fast lookups within a session
    2. Database cache (species_cache table) for persistence across restarts

    Features:
    - Async parallel resolution for batch operations
    - Rate limiting to respect GBIF API limits
    - Automatic detection of non-species labels

    Examples
    --------
    Resolve a single species:
    >>> resolver = SpeciesResolver()
    >>> info = await resolver.resolve(session, "Passer montanus", locale="ja")
    >>> print(info.canonical_name)  # "Passer montanus"
    >>> print(info.vernacular_name)  # "スズメ"

    Resolve multiple species in batch:
    >>> names = ["Passer montanus", "Corvus corone", "Parus minor"]
    >>> results = await resolver.resolve_batch(session, names, locale="ja")
    >>> for name, info in results.items():
    ...     print(f"{name}: {info.vernacular_name}")
    """

    def __init__(
        self,
        rate_limit_calls: int = GBIF_RATE_LIMIT_CALLS,
        rate_limit_period: float = GBIF_RATE_LIMIT_PERIOD,
    ):
        """Initialize the species resolver.

        Parameters
        ----------
        rate_limit_calls : int
            Maximum GBIF API calls per rate_limit_period. Default 10.
        rate_limit_period : float
            Rate limit period in seconds. Default 1.0.
        """
        self._memory_cache: dict[tuple[str, str], SpeciesInfo] = {}
        self._rate_limiter = RateLimiter(rate_limit_calls, rate_limit_period)

    def _is_non_species_label(self, scientific_name: str) -> bool:
        """Check if a label represents a non-species sound.

        Parameters
        ----------
        scientific_name : str
            The scientific name to check.

        Returns
        -------
        bool
            True if this is a non-species environmental sound label.
        """
        normalized = scientific_name.lower().strip()
        return normalized in NON_SPECIES_LABELS

    async def _check_db_cache(
        self,
        session: AsyncSession,
        scientific_name: str,
        locale: str,
    ) -> SpeciesInfo | None:
        """Check database cache for species info.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        scientific_name : str
            Scientific name to look up.
        locale : str
            Locale for vernacular name (e.g., "ja", "en").

        Returns
        -------
        SpeciesInfo | None
            Cached info if found with vernacular name for requested locale, None otherwise.
        """
        from echoroo import models

        stmt = select(models.SpeciesCache).where(
            models.SpeciesCache.scientific_name == scientific_name,
        )
        result = await session.execute(stmt)
        cached = result.scalar_one_or_none()

        if cached is None:
            return None

        # Extract vernacular name for requested locale from JSON
        vernacular = None
        if cached.vernacular_names_json:
            vernacular = cached.vernacular_names_json.get(locale.lower())

        return SpeciesInfo(
            gbif_taxon_id=cached.gbif_taxon_id,
            canonical_name=cached.canonical_name,
            vernacular_name=vernacular,
        )

    async def _store_db_cache(
        self,
        session: AsyncSession,
        scientific_name: str,
        vernacular_names_json: dict[str, str] | None,
        info: SpeciesInfo,
        is_non_species: bool = False,
    ) -> None:
        """Store species info in database cache with all vernacular names.

        Uses upsert to handle concurrent inserts gracefully. All vernacular names
        from GBIF are stored in JSON format to avoid repeated API calls for
        different locales.

        Parameters
        ----------
        session : AsyncSession
            Database session.
        scientific_name : str
            Scientific name (cache key).
        vernacular_names_json : dict[str, str] | None
            All vernacular names from GBIF keyed by language code (e.g., {"ja": "ヒヨドリ", "en": "Brown-eared Bulbul"}).
        info : SpeciesInfo
            Resolved species information.
        is_non_species : bool
            Whether this is a non-species label.
        """
        from echoroo import models

        stmt = pg_insert(models.SpeciesCache).values(
            scientific_name=scientific_name,
            gbif_taxon_id=info.gbif_taxon_id,
            canonical_name=info.canonical_name,
            vernacular_names_json=vernacular_names_json,
            is_non_species=is_non_species,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["scientific_name"],
            set_={
                "gbif_taxon_id": stmt.excluded.gbif_taxon_id,
                "canonical_name": stmt.excluded.canonical_name,
                "vernacular_names_json": stmt.excluded.vernacular_names_json,
                "is_non_species": stmt.excluded.is_non_species,
            },
        )
        await session.execute(stmt)

    async def _resolve_from_gbif(
        self,
        scientific_name: str,
        locale: str,
    ) -> tuple[SpeciesInfo, dict[str, str] | None]:
        """Resolve species from GBIF API with rate limiting.

        Uses search API to find species, then fetches vernacular names directly
        if not included in search results to ensure completeness.

        Parameters
        ----------
        scientific_name : str
            Scientific name to resolve.
        locale : str
            Locale for vernacular name (e.g., "ja", "en").

        Returns
        -------
        tuple[SpeciesInfo, dict[str, str] | None]
            Tuple of (SpeciesInfo, vernacular_names_json).
            vernacular_names_json maps 2-letter language codes to vernacular names.
        """
        await self._rate_limiter.acquire()

        try:
            # Use limit=50 to get multiple GBIF entries and select the one with most complete data
            # Some species have complete entries deep in the result list (e.g., Horornis diphone at position 8)
            # A higher limit ensures we find the most comprehensive entry with vernacular names
            candidates = await search_gbif_species(scientific_name, limit=50)
            if candidates:
                candidate = candidates[0]
                usage_key = candidate.usage_key
                canonical = candidate.canonical_name or scientific_name

                # Extract all vernacular names and convert to JSON format
                # Map 3-letter GBIF codes to 2-letter ISO codes for storage
                vernacular_names_json = self._build_vernacular_names_json(
                    candidate.vernacular_names
                )

                # If no vernacular names in search results, fetch them directly
                # This is more reliable for getting complete vernacular name data
                if not vernacular_names_json:
                    from echoroo.api.species import get_gbif_vernacular_name

                    # Fetch vernacular name for requested locale
                    vernacular_name_from_api = await get_gbif_vernacular_name(
                        usage_key, locale
                    )
                    if vernacular_name_from_api:
                        vernacular_names_json = {locale.lower(): vernacular_name_from_api}
                        logger.debug(
                            "Fetched vernacular name for '%s' from GBIF API: %s",
                            scientific_name,
                            vernacular_name_from_api,
                        )

                # Extract vernacular name for requested locale
                vernacular = vernacular_names_json.get(locale.lower()) if vernacular_names_json else None
            else:
                logger.debug("No GBIF match found for '%s'", scientific_name)
                usage_key = None
                canonical = scientific_name
                vernacular = None
                vernacular_names_json = None
        except Exception as e:
            logger.warning("GBIF lookup failed for '%s': %s", scientific_name, e)
            usage_key = None
            canonical = scientific_name
            vernacular = None
            vernacular_names_json = None

        return (
            SpeciesInfo(
                gbif_taxon_id=usage_key,
                canonical_name=canonical,
                vernacular_name=vernacular,
            ),
            vernacular_names_json,
        )

    def _build_vernacular_names_json(
        self,
        vernacular_names: list[dict] | None,
    ) -> dict[str, str] | None:
        """Build vernacular names JSON from GBIF API response.

        Converts GBIF's 3-letter language codes to 2-letter ISO codes for
        consistent storage and lookup.

        Parameters
        ----------
        vernacular_names : list[dict] | None
            List of vernacular names from GBIF API (each dict has 'language' and 'vernacular_name').

        Returns
        -------
        dict[str, str] | None
            Dictionary mapping 2-letter language codes to vernacular names,
            or None if no vernacular names available.
        """
        if not vernacular_names:
            return None

        # Reverse mapping: 3-letter GBIF codes -> 2-letter ISO codes
        from echoroo.ml.constants import GBIF_LANG_CODE_MAP

        lang_3to2 = {v.lower(): k for k, v in GBIF_LANG_CODE_MAP.items()}

        result: dict[str, str] = {}
        for item in vernacular_names:
            language_raw = item.get("language")
            # Skip entries with no language code
            if not language_raw:
                continue

            gbif_lang = language_raw.lower()
            vernacular_name = item.get("vernacular_name")

            if not vernacular_name:
                continue

            # Convert 3-letter code to 2-letter if possible
            iso_code = lang_3to2.get(gbif_lang, gbif_lang)

            # Store the first occurrence of each language
            if iso_code not in result:
                result[iso_code] = vernacular_name

        return result if result else None

    async def resolve(
        self,
        session: AsyncSession,
        scientific_name: str,
        locale: str = "ja",
    ) -> SpeciesInfo:
        """Resolve a scientific name to GBIF taxon information.

        Uses a three-tier lookup:
        1. In-memory cache (fastest)
        2. Database cache (persistent)
        3. GBIF API (authoritative)

        Non-species labels (e.g., "Background", "No call") are detected and
        returned without GBIF lookup to avoid false matches.

        Parameters
        ----------
        session : AsyncSession
            Database session for cache operations.
        scientific_name : str
            The scientific name to resolve (e.g., "Passer montanus").
        locale : str, optional
            Language code for vernacular name (e.g., "ja", "en"). Defaults to "ja".

        Returns
        -------
        SpeciesInfo
            Resolved species information including GBIF taxon ID, canonical name,
            and vernacular name (if available).

        Examples
        --------
        >>> resolver = SpeciesResolver()
        >>> info = await resolver.resolve(session, "Passer montanus", locale="ja")
        >>> print(info.canonical_name)  # "Passer montanus"
        >>> print(info.vernacular_name)  # "スズメ"
        """
        cache_key = (scientific_name, locale)

        # 1. Check memory cache
        if cache_key in self._memory_cache:
            logger.debug(
                "Memory cache hit for species '%s' (locale=%s)",
                scientific_name,
                locale,
            )
            return self._memory_cache[cache_key]

        # 2. Handle non-species labels
        if self._is_non_species_label(scientific_name):
            logger.debug(
                "Skipping GBIF resolution for non-species label: %s",
                scientific_name,
            )
            info = SpeciesInfo(
                gbif_taxon_id=None,
                canonical_name=scientific_name,
                vernacular_name=None,
            )
            self._memory_cache[cache_key] = info
            return info

        # 3. Check database cache
        cached = await self._check_db_cache(session, scientific_name, locale)
        if cached is not None:
            logger.debug(
                "DB cache hit for species '%s' (locale=%s)",
                scientific_name,
                locale,
            )
            self._memory_cache[cache_key] = cached
            return cached

        # 4. Resolve from GBIF API
        logger.debug(
            "Resolving species '%s' via GBIF (locale=%s)",
            scientific_name,
            locale,
        )
        info, vernacular_names_json = await self._resolve_from_gbif(scientific_name, locale)

        # 5. Store in caches (all languages for future lookups)
        self._memory_cache[cache_key] = info
        await self._store_db_cache(
            session,
            scientific_name,
            vernacular_names_json,
            info,
        )
        await session.flush()

        logger.debug(
            "Resolved '%s' -> taxon_id=%s, canonical=%s, vernacular=%s",
            scientific_name,
            info.gbif_taxon_id,
            info.canonical_name,
            info.vernacular_name,
        )

        return info

    async def resolve_batch(
        self,
        session: AsyncSession,
        scientific_names: list[str],
        locale: str = "ja",
        concurrency: int = 5,
    ) -> dict[str, SpeciesInfo]:
        """Resolve multiple scientific names in parallel with concurrency control.

        This method is significantly more efficient than calling `resolve()`
        multiple times when you have many names to process. It:

        1. Checks memory cache for all names
        2. Batch-checks database cache for remaining names
        3. Resolves remaining names via GBIF API in parallel (with rate limiting)

        Parameters
        ----------
        session : AsyncSession
            Database session for cache operations.
        scientific_names : list[str]
            List of scientific names to resolve.
        locale : str, optional
            Language code for vernacular names (e.g., "ja", "en"). Defaults to "ja".
        concurrency : int, optional
            Maximum concurrent GBIF API calls. Default 5.

        Returns
        -------
        dict[str, SpeciesInfo]
            Dictionary mapping each input scientific name to its resolved SpeciesInfo.

        Examples
        --------
        >>> resolver = SpeciesResolver()
        >>> names = ["Passer montanus", "Corvus corone", "Parus minor"]
        >>> results = await resolver.resolve_batch(session, names, locale="ja")
        >>> for name, info in results.items():
        ...     print(f"{name}: {info.vernacular_name}")
        """
        results: dict[str, SpeciesInfo] = {}
        to_check_db: list[str] = []

        # Phase 1: Check memory cache
        for name in scientific_names:
            cache_key = (name, locale)
            if cache_key in self._memory_cache:
                results[name] = self._memory_cache[cache_key]
            elif self._is_non_species_label(name):
                # Handle non-species labels immediately
                info = SpeciesInfo(
                    gbif_taxon_id=None,
                    canonical_name=name,
                    vernacular_name=None,
                )
                self._memory_cache[cache_key] = info
                results[name] = info
            else:
                to_check_db.append(name)

        if not to_check_db:
            logger.debug(
                "All %d species names were in memory cache (locale=%s)",
                len(scientific_names),
                locale,
            )
            return results

        # Phase 2: Check database cache for remaining names
        from echoroo import models

        stmt = select(models.SpeciesCache).where(
            models.SpeciesCache.scientific_name.in_(to_check_db),
        )
        result = await session.execute(stmt)
        db_cached = {row.scientific_name: row for row in result.scalars().all()}

        to_resolve: list[str] = []
        for name in to_check_db:
            if name in db_cached:
                cached = db_cached[name]

                # Extract vernacular name for requested locale from JSON
                vernacular = None
                if cached.vernacular_names_json:
                    vernacular = cached.vernacular_names_json.get(locale.lower())

                info = SpeciesInfo(
                    gbif_taxon_id=cached.gbif_taxon_id,
                    canonical_name=cached.canonical_name,
                    vernacular_name=vernacular,
                )
                self._memory_cache[(name, locale)] = info
                results[name] = info
            else:
                to_resolve.append(name)

        if not to_resolve:
            logger.debug(
                "All %d remaining species were in DB cache (locale=%s)",
                len(to_check_db),
                locale,
            )
            return results

        logger.info(
            "Resolving %d/%d species via GBIF (locale=%s)",
            len(to_resolve),
            len(scientific_names),
            locale,
        )

        # Phase 3: Parallel GBIF resolution with semaphore
        semaphore = asyncio.Semaphore(concurrency)

        async def resolve_one(name: str) -> tuple[str, SpeciesInfo, dict[str, str] | None]:
            async with semaphore:
                info, vernacular_names_json = await self._resolve_from_gbif(name, locale)
                return name, info, vernacular_names_json

        tasks = [resolve_one(name) for name in to_resolve]
        resolved = await asyncio.gather(*tasks, return_exceptions=True)

        # Phase 4: Store results
        for result_item in resolved:
            if isinstance(result_item, BaseException):
                logger.error("Resolution failed: %s", result_item)
                continue
            # result_item is tuple[str, SpeciesInfo, dict | None] after BaseException check
            name, info, vernacular_names_json = result_item
            results[name] = info
            self._memory_cache[(name, locale)] = info
            await self._store_db_cache(
                session,
                name,
                vernacular_names_json,
                info,
                is_non_species=False,
            )

        await session.flush()

        logger.info(
            "Batch resolution complete: %d species resolved",
            len(results),
        )

        return results

    def clear_cache(self) -> None:
        """Clear the in-memory species resolution cache.

        This removes all cached GBIF lookup results from memory.
        Database cache entries are not affected.

        Examples
        --------
        >>> resolver = SpeciesResolver()
        >>> await resolver.resolve(session, "Passer montanus")
        >>> resolver.clear_cache()  # Force DB lookup next time
        """
        logger.info("Clearing species resolver memory cache (%d entries)", len(self._memory_cache))
        self._memory_cache.clear()

    def get_cache_stats(self) -> dict[str, int]:
        """Get in-memory cache statistics.

        Returns
        -------
        dict[str, int]
            Dictionary with cache statistics:
            - "size": Number of cached entries
            - "unique_species": Number of unique species (ignoring locale)

        Examples
        --------
        >>> resolver = SpeciesResolver()
        >>> await resolver.resolve(session, "Passer montanus", locale="ja")
        >>> await resolver.resolve(session, "Passer montanus", locale="en")
        >>> stats = resolver.get_cache_stats()
        >>> print(stats)
        {'size': 2, 'unique_species': 1}
        """
        unique_species = len({name for name, _ in self._memory_cache.keys()})
        return {
            "size": len(self._memory_cache),
            "unique_species": unique_species,
        }
