"""BirdNET geo model filter implementation.

This module provides species filtering using BirdNET's geo model,
which predicts species occurrence probabilities based on location and time.

The filter normalizes BirdNET species labels to GBIF taxon keys, enabling
consistent matching with other data sources. Results are cached in memory
and optionally in the database for performance.

Example
-------
>>> from echoroo.ml.filters import FilterContext, BirdNETGeoFilter
>>>
>>> filter = BirdNETGeoFilter()
>>> context = FilterContext(latitude=35.67, longitude=139.65, week=19)
>>> probs = await filter.get_species_probabilities(context, session)
>>> # {"2493098": 0.85, ...}  # GBIF taxon keys
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any, Literal

from echoroo.ml.filters.base import FilterContext, SpeciesFilter

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["BirdNETGeoFilter"]

logger = logging.getLogger(__name__)

# Location bucket resolution for caching (1 degree grid)
_LOCATION_BUCKET_RESOLUTION = 1


class BirdNETGeoFilter(SpeciesFilter):
    """Species filter using BirdNET's geo model.

    This filter uses BirdNET's pre-trained geo model to predict species
    occurrence probabilities based on latitude, longitude, and week of year.
    The model is loaded lazily on first use.

    All results are normalized to GBIF taxon keys for consistent matching
    with other data sources. GBIF resolution results are cached in memory
    to avoid repeated API calls.

    Parameters
    ----------
    version : str
        BirdNET model version. Default is "2.4".
    backend : str
        TensorFlow backend. Default is "tf" (TFLite).

    Examples
    --------
    >>> filter = BirdNETGeoFilter()
    >>> context = FilterContext(latitude=42.5, longitude=-76.45, week=4)
    >>> probs = await filter.get_species_probabilities(context, session)
    >>> print(f"Found {len(probs)} species with GBIF taxon keys")
    """

    def __init__(
        self,
        version: Literal["2.4"] = "2.4",
        backend: Literal["tf", "pb"] = "tf",
    ) -> None:
        self._version: Literal["2.4"] = version
        self._backend: Literal["tf", "pb"] = backend
        self._model: Any | None = None
        self._lock = threading.Lock()
        self._load_failed = False

        # GBIF resolution cache: {scientific_name: (taxon_key, canonical_name)}
        self._gbif_cache: dict[str, tuple[str | None, str | None]] = {}

        # Occurrence cache: {(lat_bucket, lon_bucket, week): {taxon_key: probability}}
        self._occurrence_cache: dict[
            tuple[int, int, int], dict[str, float]
        ] = {}

    def _ensure_loaded(self) -> bool:
        """Load the geo model if not already loaded.

        Returns
        -------
        bool
            True if model is loaded and ready.
        """
        if self._model is not None:
            return True

        if self._load_failed:
            return False

        with self._lock:
            # Double-check after acquiring lock
            if self._model is not None:
                return True

            try:
                import birdnet

                # Type stubs may not match runtime signature
                self._model = birdnet.load(  # type: ignore[call-overload]
                    "geo", self._version, self._backend
                )
                logger.info(
                    "Loaded BirdNET geo model v%s (%s backend)",
                    self._version,
                    self._backend,
                )
                return True

            except ImportError:
                logger.warning(
                    "birdnet package not installed, geo filtering disabled"
                )
                self._load_failed = True
                return False

            except Exception as e:
                logger.warning("Failed to load BirdNET geo model: %s", e)
                self._load_failed = True
                return False

    @property
    def is_loaded(self) -> bool:
        """Check if geo model is loaded."""
        return self._model is not None

    def _parse_scientific_name(self, label: str) -> str:
        """Parse scientific name from BirdNET species label.

        BirdNET labels have format "Genus species_Common Name".
        This extracts just the scientific name part.

        Parameters
        ----------
        label : str
            BirdNET species label (e.g., "Parus minor_Japanese Tit").

        Returns
        -------
        str
            Scientific name (e.g., "Parus minor").
        """
        # Split on underscore to separate scientific from common name
        parts = label.split("_", 1)
        scientific = parts[0] if parts else label
        # Clean up any internal underscores in scientific name
        return scientific.replace("_", " ").strip()

    async def _resolve_gbif_taxon(
        self,
        scientific_name: str,
        session: AsyncSession,
    ) -> tuple[str | None, str | None]:
        """Resolve GBIF taxon key for a scientific name.

        Uses memory cache first, then falls back to GBIF API.
        DB cache (SpeciesOccurrenceCache) will be added later.

        Parameters
        ----------
        scientific_name : str
            Scientific name to resolve.
        session : AsyncSession
            Database session (for future DB cache).

        Returns
        -------
        tuple[str | None, str | None]
            (taxon_key, canonical_name) or (None, None) if not found.
        """
        # Check memory cache first
        if scientific_name in self._gbif_cache:
            return self._gbif_cache[scientific_name]

        # TODO: Check DB cache (SpeciesOccurrenceCache) when available
        # stmt = select(SpeciesOccurrenceCache).where(
        #     SpeciesOccurrenceCache.scientific_name == scientific_name
        # )
        # cached = await session.scalar(stmt)
        # if cached is not None:
        #     result = (cached.gbif_taxon_key, cached.canonical_name)
        #     self._gbif_cache[scientific_name] = result
        #     return result

        # Query GBIF API (lazy import to avoid circular dependency)
        try:
            from echoroo.api import search_gbif_species

            candidates = await search_gbif_species(scientific_name, limit=1)
            if candidates:
                candidate = candidates[0]
                taxon_key = candidate.usage_key
                canonical = candidate.canonical_name or scientific_name
            else:
                taxon_key = None
                canonical = None
        except Exception as e:
            logger.warning(
                "GBIF lookup failed for '%s': %s", scientific_name, e
            )
            taxon_key = None
            canonical = None

        # Cache result
        self._gbif_cache[scientific_name] = (taxon_key, canonical)

        # TODO: Store in DB cache when available
        # session.add(SpeciesOccurrenceCache(
        #     scientific_name=scientific_name,
        #     gbif_taxon_key=taxon_key,
        #     canonical_name=canonical,
        # ))

        return taxon_key, canonical

    def _get_location_bucket(
        self, context: FilterContext
    ) -> tuple[int, int, int]:
        """Get location bucket key for caching.

        Buckets are 1-degree grid cells to reduce redundant geo predictions.

        Parameters
        ----------
        context : FilterContext
            Location and time context.

        Returns
        -------
        tuple[int, int, int]
            (lat_bucket, lon_bucket, week) for cache key.
        """
        lat_bucket = int(context.latitude // _LOCATION_BUCKET_RESOLUTION)  # type: ignore[operator]
        lon_bucket = int(context.longitude // _LOCATION_BUCKET_RESOLUTION)  # type: ignore[operator]
        return (lat_bucket, lon_bucket, context.week)  # type: ignore[return-value]

    def _get_raw_probabilities(
        self, context: FilterContext
    ) -> dict[str, float] | None:
        """Get raw species probabilities from BirdNET geo model.

        Parameters
        ----------
        context : FilterContext
            Location and time context.

        Returns
        -------
        dict[str, float] | None
            Mapping of BirdNET label to probability, or None if unavailable.
        """
        if not self._ensure_loaded():
            return None

        assert self._model is not None

        try:
            # BirdNET geo model expects: latitude, longitude, week
            result = self._model.predict(
                context.latitude,
                context.longitude,
                week=context.week,
            )

            # Convert result to dict
            probs: dict[str, float] = {}
            for species_name, confidence in zip(
                result.species_list, result.species_probs
            ):
                probs[str(species_name)] = float(confidence)

            return probs

        except Exception as e:
            logger.warning("BirdNET geo prediction failed: %s", e)
            return None

    async def get_species_probabilities(
        self,
        context: FilterContext,
        session: AsyncSession,
    ) -> dict[str, float] | None:
        """Get species occurrence probabilities normalized to GBIF taxon keys.

        Parameters
        ----------
        context : FilterContext
            Location (latitude, longitude) and time (week).
        session : AsyncSession
            Database session for GBIF resolution and caching.

        Returns
        -------
        dict[str, float] | None
            Mapping of GBIF taxon key to occurrence probability (0-1).
            Returns None if context is invalid or model unavailable.
        """
        if not context.is_valid:
            logger.debug("Invalid context for geo filtering")
            return None

        # Check occurrence cache for this location/time bucket
        bucket = self._get_location_bucket(context)
        if bucket in self._occurrence_cache:
            logger.debug("Using cached occurrence data for bucket %s", bucket)
            return self._occurrence_cache[bucket]

        # Get raw probabilities from BirdNET geo model
        # Run in executor to avoid blocking the async loop
        loop = asyncio.get_running_loop()
        raw_probs = await loop.run_in_executor(
            None, self._get_raw_probabilities, context
        )

        if raw_probs is None:
            return None

        # Normalize to GBIF taxon keys
        gbif_probs: dict[str, float] = {}
        for label, probability in raw_probs.items():
            scientific_name = self._parse_scientific_name(label)
            taxon_key, _ = await self._resolve_gbif_taxon(
                scientific_name, session
            )

            if taxon_key is not None:
                # Use taxon key as the key
                gbif_probs[taxon_key] = probability
            else:
                # Fall back to scientific name if GBIF resolution failed
                # This ensures we don't lose species data
                logger.debug(
                    "No GBIF taxon key for '%s', using scientific name",
                    scientific_name,
                )
                gbif_probs[scientific_name] = probability

        # Cache the result
        self._occurrence_cache[bucket] = gbif_probs

        logger.debug(
            "BirdNET geo: %d species at (%.2f, %.2f) week %d",
            len(gbif_probs),
            context.latitude,
            context.longitude,
            context.week,
        )

        return gbif_probs

    def clear_cache(self) -> None:
        """Clear all caches (GBIF and occurrence)."""
        self._gbif_cache.clear()
        self._occurrence_cache.clear()
        logger.debug("BirdNETGeoFilter caches cleared")

    def __repr__(self) -> str:
        status = "loaded" if self._model else "not loaded"
        cache_info = (
            f"gbif_cache={len(self._gbif_cache)}, "
            f"occurrence_cache={len(self._occurrence_cache)}"
        )
        return (
            f"BirdNETGeoFilter(version={self._version!r}, "
            f"status={status}, {cache_info})"
        )
