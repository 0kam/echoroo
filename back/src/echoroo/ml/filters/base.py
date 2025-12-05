"""Prediction filter base classes for ML model outputs.

This module provides a unified abstraction for filtering species predictions
from ML models. Filters can apply location-based, temporal, or ecological
constraints to reduce false positives by excluding unlikely species.

The filter abstraction decouples filtering logic from inference, allowing
any model to use any filter implementation. This enables:
- BirdNET to use eBird occurrence data
- Other models to use the same occurrence data
- Different filtering strategies (range maps, expert rules, etc.)

Key Components
--------------
FilterContext : dataclass
    Encapsulates location and temporal information for filtering.

PredictionFilter : ABC
    Abstract base class defining the filter interface.

PassThroughFilter : concrete
    Default no-op filter that passes all predictions unchanged.

Example
-------
>>> from echoroo.ml.filters.base import (
...     FilterContext,
...     PassThroughFilter,
... )
>>> from datetime import date
>>>
>>> # Create filter context
>>> context = FilterContext(
...     latitude=35.6762,
...     longitude=139.6503,
...     date=date(2024, 5, 15),
...     time_of_day="dawn",
... )
>>>
>>> # Use pass-through filter
>>> filter = PassThroughFilter()
>>> predictions = [("species_a", 0.95), ("species_b", 0.82)]
>>> filtered = filter.filter_predictions(predictions, context)
>>> assert filtered == predictions  # No filtering applied
>>>
>>> # Check context properties
>>> assert context.has_location
>>> assert context.has_temporal

Notes
-----
This is Phase 3 of the ML pipeline refactoring. The BirdNETMetadataFilter
will be migrated to OccurrenceFilter using this abstraction in a future phase.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "FilterContext",
    "PredictionFilter",
    "PassThroughFilter",
    "TimeOfDay",
]

logger = logging.getLogger(__name__)

# Type for time of day
TimeOfDay = Literal["dawn", "day", "dusk", "night"]


@dataclass
class FilterContext:
    """Recording context for filtering predictions.

    This dataclass encapsulates the geographic and temporal metadata needed
    to filter species predictions. It provides a standard interface that works
    across different filtering implementations.

    Attributes
    ----------
    latitude : float | None
        Recording latitude in decimal degrees (-90 to 90).
        None if location is unknown.
    longitude : float | None
        Recording longitude in decimal degrees (-180 to 180).
        None if location is unknown.
    date : date | None
        Recording date.
        None if date is unknown.
    time_of_day : TimeOfDay | None
        Time period when recording was made.
        One of: "dawn", "day", "dusk", "night".
        None if time is unknown.
    habitat : str | None
        Habitat type or description.
        None if habitat is unknown.

    Properties
    ----------
    has_location : bool
        True if both latitude and longitude are available.
    has_temporal : bool
        True if either date or time_of_day is available.

    Examples
    --------
    >>> # Full context
    >>> ctx = FilterContext(
    ...     latitude=35.6762,
    ...     longitude=139.6503,
    ...     date=date(2024, 5, 15),
    ...     time_of_day="dawn",
    ...     habitat="forest",
    ... )
    >>> assert ctx.has_location and ctx.has_temporal
    >>>
    >>> # Location only
    >>> ctx = FilterContext(latitude=35.6762, longitude=139.6503)
    >>> assert ctx.has_location and not ctx.has_temporal
    >>>
    >>> # Empty context (no filtering will be applied)
    >>> ctx = FilterContext()
    >>> assert not ctx.has_location and not ctx.has_temporal

    Notes
    -----
    - All fields are optional to handle recordings with incomplete metadata
    - Invalid values raise ValueError in __post_init__
    - Additional fields may be added in future versions
    """

    latitude: float | None = None
    longitude: float | None = None
    date: date | None = None
    time_of_day: TimeOfDay | None = None
    habitat: str | None = None

    def __post_init__(self) -> None:
        """Validate field values.

        Raises
        ------
        ValueError
            If latitude is not in [-90, 90].
            If longitude is not in [-180, 180].
            If time_of_day is not one of the valid values.
        """
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

        if self.time_of_day is not None:
            valid_times = {"dawn", "day", "dusk", "night"}
            if self.time_of_day not in valid_times:
                raise ValueError(
                    f"time_of_day must be one of {valid_times}, got '{self.time_of_day}'"
                )

    @property
    def has_location(self) -> bool:
        """Check if location information is available.

        Returns
        -------
        bool
            True if both latitude and longitude are not None.
        """
        return self.latitude is not None and self.longitude is not None

    @property
    def has_temporal(self) -> bool:
        """Check if temporal information is available.

        Returns
        -------
        bool
            True if either date or time_of_day is not None.
        """
        return self.date is not None or self.time_of_day is not None


class PredictionFilter(ABC):
    """Abstract base class for filtering ML model predictions.

    This class defines the interface for prediction filters. Filters can use
    location, time, habitat, or other contextual information to filter out
    unlikely species predictions, reducing false positives.

    The filter abstraction allows different implementations:
    - Occurrence-based: Use eBird or other occurrence data
    - Range-based: Use species range maps
    - Expert-based: Use expert knowledge rules
    - ML-based: Use trained filters

    Subclasses must implement three abstract methods:
    - filter_predictions: Filter a list of predictions
    - get_species_mask: Get a boolean mask for batch filtering
    - get_occurrence_probability: Get probability for a single species

    Examples
    --------
    Implementing a custom filter:

    >>> class RangeMapFilter(PredictionFilter):
    ...     def __init__(self, range_maps):
    ...         self.range_maps = range_maps
    ...
    ...     def filter_predictions(self, predictions, context):
    ...         if not context.has_location:
    ...             return predictions
    ...         return [
    ...             (sp, conf)
    ...             for sp, conf in predictions
    ...             if self._in_range(
    ...                 sp, context.latitude, context.longitude
    ...             )
    ...         ]
    ...
    ...     def get_species_mask(self, context):
    ...         # Return boolean array for all species
    ...         ...
    ...
    ...     def get_occurrence_probability(self, species, context):
    ...         # Return probability for specific species
    ...         ...

    Notes
    -----
    - Filters should gracefully handle missing context (return unfiltered)
    - Filters should log filtering decisions for debugging
    - Thread safety is the responsibility of implementers
    """

    @abstractmethod
    def filter_predictions(
        self,
        predictions: list[tuple[str, float]],
        context: FilterContext,
    ) -> list[tuple[str, float]]:
        """Filter predictions based on context.

        This method takes a list of species predictions and filters them
        based on the provided context (location, time, etc.). Predictions
        for species unlikely to be present are removed.

        Parameters
        ----------
        predictions : list[tuple[str, float]]
            List of (species_label, confidence) tuples from the model.
            Species labels should match the format used by the model.
            Confidences should be in [0, 1].
        context : FilterContext
            Recording context for filtering.

        Returns
        -------
        list[tuple[str, float]]
            Filtered list of predictions. Maintains original order and
            confidence scores. If filtering cannot be applied (missing
            context, no data, etc.), should return predictions unchanged.

        Examples
        --------
        >>> filter = MyFilter()
        >>> context = FilterContext(
        ...     latitude=35.6762, longitude=139.6503
        ... )
        >>> predictions = [
        ...     ("species_a", 0.95),
        ...     ("species_b", 0.82),
        ...     ("species_c", 0.65),
        ... ]
        >>> filtered = filter.filter_predictions(predictions, context)
        >>> # species_c removed as unlikely at this location
        >>> assert len(filtered) < len(predictions)

        Notes
        -----
        - Should not modify confidence scores, only remove predictions
        - Should preserve order of remaining predictions
        - Should log filtering decisions at debug level
        - Should handle empty predictions list gracefully
        """
        raise NotImplementedError

    @abstractmethod
    def get_species_mask(
        self,
        context: FilterContext,
    ) -> NDArray[np.bool_] | None:
        """Get boolean mask indicating which species are likely present.

        This method returns a boolean array aligned with the model's species
        list, where True indicates the species is likely present at the given
        context. This is useful for batch filtering of model outputs.

        Parameters
        ----------
        context : FilterContext
            Recording context for filtering.

        Returns
        -------
        NDArray[np.bool_] | None
            Boolean array of shape (n_species,) where True indicates the
            species is likely present. Returns None if:
            - Filtering cannot be applied (missing context)
            - Species data is not available
            - Filter implementation doesn't support masking

        Examples
        --------
        >>> filter = MyFilter()
        >>> context = FilterContext(
        ...     latitude=35.6762, longitude=139.6503
        ... )
        >>> mask = filter.get_species_mask(context)
        >>> if mask is not None:
        ...     print(f"{mask.sum()} species likely present")
        ...     # Use mask to filter model outputs
        ...     filtered_probs = model_probs * mask

        Notes
        -----
        - Mask should align with the model's species list
        - None indicates pass-through (no filtering)
        - Implementations should cache masks when appropriate
        """
        raise NotImplementedError

    @abstractmethod
    def get_occurrence_probability(
        self,
        species: str,
        context: FilterContext,
    ) -> float | None:
        """Get occurrence probability for a specific species.

        This method returns the probability that a species occurs at the
        given context. This can be used for ranking species or implementing
        probabilistic filtering.

        Parameters
        ----------
        species : str
            Species label in the format used by the model.
        context : FilterContext
            Recording context for lookup.

        Returns
        -------
        float | None
            Occurrence probability in [0, 1], or None if:
            - Species is not known to the filter
            - Context is insufficient for lookup
            - Filter implementation doesn't support probabilities

        Examples
        --------
        >>> filter = MyFilter()
        >>> context = FilterContext(
        ...     latitude=35.6762,
        ...     longitude=139.6503,
        ...     date=date(2024, 5, 15),
        ... )
        >>> prob = filter.get_occurrence_probability(
        ...     "species_a", context
        ... )
        >>> if prob is not None:
        ...     print(f"Occurrence probability: {prob:.2%}")

        Notes
        -----
        - None indicates unknown/unavailable probability
        - Should return probability in [0, 1] range
        - Can be used for soft filtering or ranking
        """
        raise NotImplementedError


class PassThroughFilter(PredictionFilter):
    """No-op filter that passes all predictions unchanged.

    This filter provides a default implementation that applies no filtering.
    It's useful as a fallback when:
    - No filtering data is available
    - User wants to disable filtering
    - Testing model performance without filters

    The PassThroughFilter always returns:
    - Original predictions unmodified
    - None for species mask (indicating no filtering)
    - None for occurrence probabilities (indicating unknown)

    Examples
    --------
    >>> filter = PassThroughFilter()
    >>> context = FilterContext(
    ...     latitude=35.6762, longitude=139.6503
    ... )
    >>>
    >>> predictions = [("species_a", 0.95), ("species_b", 0.82)]
    >>> filtered = filter.filter_predictions(predictions, context)
    >>> assert filtered == predictions
    >>>
    >>> mask = filter.get_species_mask(context)
    >>> assert mask is None
    >>>
    >>> prob = filter.get_occurrence_probability(
    ...     "species_a", context
    ... )
    >>> assert prob is None

    Notes
    -----
    This filter is stateless and thread-safe. It can be shared across
    multiple inference engines.
    """

    def filter_predictions(
        self,
        predictions: list[tuple[str, float]],
        context: FilterContext,
    ) -> list[tuple[str, float]]:
        """Return predictions unchanged.

        Parameters
        ----------
        predictions : list[tuple[str, float]]
            List of (species_label, confidence) tuples.
        context : FilterContext
            Recording context (ignored).

        Returns
        -------
        list[tuple[str, float]]
            Original predictions unmodified.
        """
        logger.debug(
            "PassThroughFilter: returning %d predictions unchanged",
            len(predictions),
        )
        return predictions

    def get_species_mask(
        self,
        context: FilterContext,
    ) -> NDArray[np.bool_] | None:
        """Return None indicating no filtering.

        Parameters
        ----------
        context : FilterContext
            Recording context (ignored).

        Returns
        -------
        None
            Always returns None to indicate no filtering.
        """
        logger.debug("PassThroughFilter: returning None for species mask")
        return None

    def get_occurrence_probability(
        self,
        species: str,
        context: FilterContext,
    ) -> float | None:
        """Return None indicating unknown probability.

        Parameters
        ----------
        species : str
            Species label (ignored).
        context : FilterContext
            Recording context (ignored).

        Returns
        -------
        None
            Always returns None to indicate unknown probability.
        """
        logger.debug(
            "PassThroughFilter: returning None for species '%s' probability",
            species,
        )
        return None

    def __repr__(self) -> str:
        """Return string representation of the filter.

        Returns
        -------
        str
            Simple class name.
        """
        return "PassThroughFilter()"
