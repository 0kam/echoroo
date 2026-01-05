"""Species name resolution service using GBIF API.

This module provides a service for resolving species names to GBIF taxon information,
including canonical names and vernacular (common) names. It includes caching and
batch processing capabilities for performance optimization.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from echoroo.api.species import get_gbif_vernacular_name, search_gbif_species

__all__ = [
    "SpeciesInfo",
    "SpeciesResolver",
]

logger = logging.getLogger(__name__)

# Non-species labels that should be skipped during resolution
# These represent environmental sounds, not biological species
NON_SPECIES_LABELS = frozenset({
    "background",
    "no call",
    "nocall",
    "silence",
    "dog",
    "engine",
    "environmental",
    "fireworks",
    "gun",
    "noise",
    "power tools",
    "siren",
    "human non-vocal",
    "human vocal",
    "human whistle",
})


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


class SpeciesResolver:
    """GBIF API-based species name resolution service.

    This service resolves scientific names to GBIF taxon information including
    canonical names and vernacular names. It includes built-in caching to minimize
    API calls and supports batch processing for better performance.

    Examples
    --------
    Resolve a single species:
    >>> resolver = SpeciesResolver()
    >>> info = await resolver.resolve("Passer montanus", locale="ja")
    >>> print(info.canonical_name)  # "Passer montanus"
    >>> print(info.vernacular_name)  # "スズメ"

    Resolve multiple species in batch:
    >>> names = ["Passer montanus", "Corvus corone", "Parus minor"]
    >>> results = await resolver.resolve_batch(names, locale="ja")
    >>> for name, info in results.items():
    ...     print(f"{name}: {info.vernacular_name}")
    """

    def __init__(self):
        """Initialize the species resolver with an empty cache."""
        self._cache: dict[tuple[str, str], SpeciesInfo] = {}

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

    async def resolve(
        self,
        scientific_name: str,
        locale: str = "ja",
    ) -> SpeciesInfo:
        """Resolve a scientific name to GBIF taxon information.

        This method queries the GBIF API to resolve the scientific name to
        a taxon key and fetches the vernacular (common) name in the specified
        locale. Results are cached for subsequent calls.

        Non-species labels (e.g., "Background", "No call") are detected and
        returned without GBIF lookup to avoid false matches.

        Parameters
        ----------
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
        >>> info = await resolver.resolve("Passer montanus", locale="ja")
        >>> print(info.canonical_name)  # "Passer montanus"
        >>> print(info.vernacular_name)  # "スズメ"
        >>> print(info.gbif_taxon_id)  # "5231670"
        """
        # Check cache first
        cache_key = (scientific_name, locale)
        if cache_key in self._cache:
            logger.debug(
                "Cache hit for species '%s' (locale=%s)",
                scientific_name,
                locale,
            )
            return self._cache[cache_key]

        # Skip GBIF resolution for non-species labels
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
            self._cache[cache_key] = info
            return info

        # Perform GBIF lookup
        logger.debug(
            "Resolving species '%s' via GBIF (locale=%s)",
            scientific_name,
            locale,
        )

        try:
            candidates = await search_gbif_species(scientific_name, limit=1)
            if candidates:
                candidate = candidates[0]
                usage_key = candidate.usage_key
                canonical = candidate.canonical_name or scientific_name

                # Fetch vernacular name from GBIF
                vernacular = await get_gbif_vernacular_name(usage_key, locale)
            else:
                logger.debug(
                    "No GBIF match found for '%s'",
                    scientific_name,
                )
                usage_key = None
                canonical = scientific_name
                vernacular = None

        except Exception as e:
            logger.warning(
                "GBIF lookup failed for '%s': %s",
                scientific_name,
                e,
            )
            usage_key = None
            canonical = scientific_name
            vernacular = None

        # Create and cache result
        info = SpeciesInfo(
            gbif_taxon_id=usage_key,
            canonical_name=canonical,
            vernacular_name=vernacular,
        )
        self._cache[cache_key] = info

        logger.debug(
            "Resolved '%s' -> taxon_id=%s, canonical=%s, vernacular=%s",
            scientific_name,
            usage_key,
            canonical,
            vernacular,
        )

        return info

    async def resolve_batch(
        self,
        scientific_names: list[str],
        locale: str = "ja",
    ) -> dict[str, SpeciesInfo]:
        """Resolve multiple scientific names in batch.

        This method resolves multiple species names efficiently by:
        1. Checking the cache for already-resolved names
        2. Filtering out non-species labels
        3. Resolving only the remaining names via GBIF API

        This is more efficient than calling `resolve()` multiple times
        when you have many names to process.

        Parameters
        ----------
        scientific_names : list[str]
            List of scientific names to resolve.
        locale : str, optional
            Language code for vernacular names (e.g., "ja", "en"). Defaults to "ja".

        Returns
        -------
        dict[str, SpeciesInfo]
            Dictionary mapping each input scientific name to its resolved SpeciesInfo.

        Examples
        --------
        >>> resolver = SpeciesResolver()
        >>> names = ["Passer montanus", "Corvus corone", "Parus minor"]
        >>> results = await resolver.resolve_batch(names, locale="ja")
        >>> for name, info in results.items():
        ...     print(f"{name}: {info.vernacular_name}")
        Passer montanus: スズメ
        Corvus corone: ハシボソガラス
        Parus minor: ヒガラ
        """
        results: dict[str, SpeciesInfo] = {}

        # Separate cached and uncached names
        to_resolve: list[str] = []
        for name in scientific_names:
            cache_key = (name, locale)
            if cache_key in self._cache:
                results[name] = self._cache[cache_key]
            else:
                to_resolve.append(name)

        if not to_resolve:
            logger.debug(
                "All %d species names were cached (locale=%s)",
                len(scientific_names),
                locale,
            )
            return results

        logger.info(
            "Resolving %d/%d species via GBIF (locale=%s)",
            len(to_resolve),
            len(scientific_names),
            locale,
        )

        # Resolve uncached names
        for name in to_resolve:
            info = await self.resolve(name, locale)
            results[name] = info

        logger.info(
            "Batch resolution complete: %d species resolved",
            len(results),
        )

        return results

    def clear_cache(self) -> None:
        """Clear the species resolution cache.

        This removes all cached GBIF lookup results. Use this if you want to
        force fresh lookups from the GBIF API or to free memory.

        Examples
        --------
        >>> resolver = SpeciesResolver()
        >>> await resolver.resolve("Passer montanus")
        >>> resolver.clear_cache()  # Force fresh lookup next time
        """
        logger.info("Clearing species resolver cache (%d entries)", len(self._cache))
        self._cache.clear()

    def get_cache_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns
        -------
        dict[str, int]
            Dictionary with cache statistics:
            - "size": Number of cached entries
            - "unique_species": Number of unique species (ignoring locale)

        Examples
        --------
        >>> resolver = SpeciesResolver()
        >>> await resolver.resolve("Passer montanus", locale="ja")
        >>> await resolver.resolve("Passer montanus", locale="en")
        >>> stats = resolver.get_cache_stats()
        >>> print(stats)
        {'size': 2, 'unique_species': 1}
        """
        unique_species = len({name for name, _ in self._cache.keys()})
        return {
            "size": len(self._cache),
            "unique_species": unique_species,
        }
