"""Prediction filter base classes for ML model outputs.

This module provides a simple abstraction for filtering species predictions
based on geographic and temporal context. All filters normalize their output
to GBIF taxon keys for consistent matching across different data sources.

Key Components
--------------
FilterContext : dataclass
    Encapsulates latitude, longitude, and week for filtering.

SpeciesFilter : ABC
    Abstract base class with async methods returning GBIF-normalized results.

PassThroughFilter : concrete
    Default no-op filter.

Example
-------
>>> from echoroo.ml.filters import FilterContext, BirdNETGeoFilter
>>>
>>> filter = BirdNETGeoFilter()
>>> context = FilterContext(latitude=35.67, longitude=139.65, week=19)
>>> probs = await filter.get_species_probabilities(context, session)
>>> # probs = {"2493098": 0.85, ...}  # GBIF taxon keys
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FilterContext",
    "SpeciesFilter",
    "PassThroughFilter",
]

logger = logging.getLogger(__name__)

# Number of weeks used in occurrence models
NUM_WEEKS = 48


@dataclass
class FilterContext:
    """Recording context for filtering predictions.

    Attributes
    ----------
    latitude : float | None
        Recording latitude in decimal degrees (-90 to 90).
    longitude : float | None
        Recording longitude in decimal degrees (-180 to 180).
    week : int | None
        Week of year (1-48). Can be calculated from date.
    """

    latitude: float | None = None
    longitude: float | None = None
    week: int | None = None

    def __post_init__(self) -> None:
        """Validate field values."""
        if self.latitude is not None:
            if not -90 <= self.latitude <= 90:
                raise ValueError(
                    f"latitude must be in [-90, 90], got {self.latitude}"
                )

        if self.longitude is not None:
            if not -180 <= self.longitude <= 180:
                raise ValueError(
                    f"longitude must be in [-180, 180], got {self.longitude}"
                )

        if self.week is not None:
            if not 1 <= self.week <= NUM_WEEKS:
                raise ValueError(
                    f"week must be in [1, {NUM_WEEKS}], got {self.week}"
                )

    @property
    def is_valid(self) -> bool:
        """Check if context has all required fields for filtering."""
        return (
            self.latitude is not None
            and self.longitude is not None
            and self.week is not None
        )

    @classmethod
    def from_recording(
        cls,
        latitude: float | None,
        longitude: float | None,
        recording_date: date | None,
    ) -> FilterContext:
        """Create FilterContext from recording metadata.

        Parameters
        ----------
        latitude : float | None
            Recording latitude.
        longitude : float | None
            Recording longitude.
        recording_date : date | None
            Recording date (converted to week).

        Returns
        -------
        FilterContext
            Context with week calculated from date.
        """
        week = None
        if recording_date is not None:
            day_of_year = recording_date.timetuple().tm_yday
            week = int((day_of_year - 1) / (365 / NUM_WEEKS)) + 1
            week = min(max(week, 1), NUM_WEEKS)

        return cls(latitude=latitude, longitude=longitude, week=week)


class SpeciesFilter(ABC):
    """Abstract base class for species occurrence filtering.

    Implementations provide species occurrence probabilities for a given
    geographic and temporal context. This enables filtering of ML model
    predictions to exclude species unlikely to be present.

    All implementations MUST normalize their output to GBIF taxon keys.
    This ensures consistent matching regardless of the underlying data source
    (BirdNET labels, eBird codes, etc.).

    The core method is `get_species_probabilities`, which returns a dict
    mapping GBIF taxon keys to their occurrence probability (0-1).
    """

    @abstractmethod
    async def get_species_probabilities(
        self,
        context: FilterContext,
        session: AsyncSession,
    ) -> dict[str, float] | None:
        """Get species occurrence probabilities for a location and time.

        All implementations must normalize species identifiers to GBIF taxon keys
        before returning. This enables consistent matching with ClipPredictionTag
        values which are stored as GBIF taxon keys.

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
            Keys are GBIF taxon keys (e.g., "2493098" for Parus minor).
            Returns None if context is invalid or filtering unavailable.

        Examples
        --------
        >>> filter = BirdNETGeoFilter()
        >>> context = FilterContext(latitude=35.67, longitude=139.65, week=19)
        >>> probs = await filter.get_species_probabilities(context, session)
        >>> if probs:
        ...     for taxon_key, prob in probs.items():
        ...         print(f"GBIF:{taxon_key}: {prob:.2%}")
        """
        raise NotImplementedError

    async def filter_predictions(
        self,
        predictions: list[tuple[str, float]],
        context: FilterContext,
        session: AsyncSession,
        threshold: float = 0.03,
    ) -> list[tuple[str, float]]:
        """Filter predictions using occurrence probabilities.

        Predictions are matched against occurrence data using GBIF taxon keys.
        The prediction's species label is resolved to a GBIF taxon key for matching.

        Parameters
        ----------
        predictions : list[tuple[str, float]]
            List of (gbif_taxon_key, confidence) tuples.
            Note: Unlike raw model output, these should already be GBIF-normalized.
        context : FilterContext
            Recording context for filtering.
        session : AsyncSession
            Database session for GBIF resolution.
        threshold : float
            Minimum occurrence probability to keep a species. Default 0.03.

        Returns
        -------
        list[tuple[str, float]]
            Filtered predictions. Species with occurrence below threshold
            are removed. Returns original predictions if filtering fails.
        """
        probs = await self.get_species_probabilities(context, session)
        if probs is None:
            logger.debug("No occurrence data, returning unfiltered predictions")
            return predictions

        filtered = []
        for taxon_key, confidence in predictions:
            occurrence = probs.get(taxon_key)

            if occurrence is None:
                # Species not in occurrence data, include by default
                # (conservative: avoid false negatives)
                filtered.append((taxon_key, confidence))
            elif occurrence >= threshold:
                filtered.append((taxon_key, confidence))
            else:
                logger.debug(
                    "Filtered taxon '%s' (occurrence %.2f%% < %.2f%%)",
                    taxon_key,
                    occurrence * 100,
                    threshold * 100,
                )

        return filtered


class PassThroughFilter(SpeciesFilter):
    """No-op filter that passes all predictions unchanged."""

    async def get_species_probabilities(
        self,
        context: FilterContext,
        session: AsyncSession,
    ) -> dict[str, float] | None:
        """Return None indicating no filtering available."""
        return None

    def __repr__(self) -> str:
        return "PassThroughFilter()"
