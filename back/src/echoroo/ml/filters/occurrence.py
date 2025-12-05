"""Occurrence-based prediction filtering.

This module provides filters that use species occurrence data (such as eBird)
to filter ML model predictions. Species predictions are filtered based on
whether the species is known to occur at a given location and time of year.

The OccurrenceFilter is model-agnostic and can be used with any inference
engine that outputs species predictions.

Key Components
--------------
OccurrenceFilter : class
    Abstract base class for occurrence-based filtering. Subclasses implement
    specific data sources (eBird, GBIF, range maps, etc.).

OccurrenceDataSource : protocol
    Interface for loading and querying occurrence data.

Example
-------
>>> from echoroo.ml.filters import FilterContext
>>> from echoroo.ml.filters.occurrence import EBirdOccurrenceFilter
>>> from datetime import date
>>>
>>> # Create filter with eBird data
>>> filter = EBirdOccurrenceFilter("/path/to/species_presence.npz")
>>>
>>> # Create context from recording metadata
>>> context = FilterContext(
...     latitude=35.6762,
...     longitude=139.6503,
...     date=date(2024, 5, 15),
... )
>>>
>>> # Filter predictions from any model
>>> predictions = [("Turdus merula_Common Blackbird", 0.85)]
>>> filtered = filter.filter_predictions(predictions, context)

Notes
-----
This module separates the filtering logic from inference, allowing:
- Any model to use occurrence filtering
- Different occurrence data sources
- Easy testing with mock data
- Configurable filtering thresholds
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from echoroo.ml.filters.base import FilterContext, PredictionFilter

__all__ = [
    "OccurrenceFilter",
    "OccurrenceDataSource",
    "EBirdOccurrenceFilter",
    "DEFAULT_OCCURRENCE_THRESHOLD",
]

logger = logging.getLogger(__name__)

# Default threshold for occurrence-based filtering
# Species with occurrence probability below this are filtered out
DEFAULT_OCCURRENCE_THRESHOLD = 0.03  # 3%

# Number of weeks in occurrence data (matches eBird/BirdNET convention)
NUM_WEEKS = 48


class OccurrenceDataSource(Protocol):
    """Protocol for occurrence data sources.

    This protocol defines the interface for classes that provide species
    occurrence data. Implementations may load data from files, databases,
    or external APIs.

    Attributes
    ----------
    is_loaded : bool
        Whether the data has been successfully loaded.
    species_list : list[str]
        List of species labels in the data.
    num_species : int
        Number of species in the data.

    Methods
    -------
    get_occurrence_probability(species, latitude, longitude, week)
        Get occurrence probability for a species at a location/time.
    get_occurrence_vector(latitude, longitude, week)
        Get occurrence probabilities for all species at a location/time.
    """

    @property
    def is_loaded(self) -> bool:
        """Whether the occurrence data has been loaded."""
        ...

    @property
    def species_list(self) -> list[str]:
        """List of species labels."""
        ...

    @property
    def num_species(self) -> int:
        """Number of species in the data."""
        ...

    def get_occurrence_probability(
        self,
        species: str,
        latitude: float,
        longitude: float,
        week: int,
    ) -> float | None:
        """Get occurrence probability for a specific species.

        Parameters
        ----------
        species : str
            Species label.
        latitude : float
            Latitude in decimal degrees.
        longitude : float
            Longitude in decimal degrees.
        week : int
            Week of year (1-48).

        Returns
        -------
        float | None
            Occurrence probability (0-1), or None if unavailable.
        """
        ...

    def get_occurrence_vector(
        self,
        latitude: float,
        longitude: float,
        week: int,
    ) -> NDArray[np.float32] | None:
        """Get occurrence probabilities for all species.

        Parameters
        ----------
        latitude : float
            Latitude in decimal degrees.
        longitude : float
            Longitude in decimal degrees.
        week : int
            Week of year (1-48).

        Returns
        -------
        NDArray[np.float32] | None
            Array of occurrence probabilities, or None if unavailable.
        """
        ...


class OccurrenceFilter(PredictionFilter):
    """Abstract base class for occurrence-based filtering.

    This class extends PredictionFilter to provide occurrence-based filtering
    of species predictions. Subclasses implement specific data sources and
    lookup mechanisms.

    The filter uses occurrence probability data to determine which species
    are likely present at a given location and time. Predictions for species
    with occurrence probability below the threshold are filtered out.

    Parameters
    ----------
    threshold : float, optional
        Minimum occurrence probability to consider a species present.
        Default is 0.03 (3%).
    default_week : int, optional
        Week to use when temporal information is not available.
        Default is 24 (mid-year).

    Attributes
    ----------
    threshold : float
        Current occurrence probability threshold.
    default_week : int
        Default week used when no temporal info is provided.

    Examples
    --------
    >>> class MyOccurrenceFilter(OccurrenceFilter):
    ...     def _load_data(self):
    ...         # Load occurrence data from source
    ...         pass
    ...
    ...     def _get_species_list(self):
    ...         return ["species_a", "species_b"]
    ...
    ...     def _get_occurrence_vector(self, lat, lon, week):
    ...         # Return occurrence probabilities
    ...         return np.array([0.8, 0.1])

    Notes
    -----
    - Subclasses must implement _load_data and _get_occurrence_vector
    - The filter gracefully handles missing data (pass-through behavior)
    - Thread safety is the responsibility of subclass implementations
    """

    def __init__(
        self,
        threshold: float = DEFAULT_OCCURRENCE_THRESHOLD,
        default_week: int = 24,
    ) -> None:
        """Initialize the occurrence filter.

        Parameters
        ----------
        threshold : float, optional
            Minimum occurrence probability to consider a species present.
            Default is 0.03 (3%).
        default_week : int, optional
            Week to use when temporal information is not available.
            Default is 24 (mid-year).
        """
        self._threshold = threshold
        self._default_week = default_week
        self._is_loaded = False
        self._species_list: list[str] = []
        self._species_to_idx: dict[str, int] = {}

    @property
    def threshold(self) -> float:
        """Get the occurrence probability threshold."""
        return self._threshold

    @threshold.setter
    def threshold(self, value: float) -> None:
        """Set the occurrence probability threshold.

        Parameters
        ----------
        value : float
            New threshold value (0-1).

        Raises
        ------
        ValueError
            If value is not in [0, 1].
        """
        if not 0 <= value <= 1:
            raise ValueError(f"threshold must be in [0, 1], got {value}")
        self._threshold = value

    @property
    def default_week(self) -> int:
        """Get the default week used when no temporal info is provided."""
        return self._default_week

    @property
    def is_loaded(self) -> bool:
        """Check if occurrence data has been loaded."""
        return self._is_loaded

    @property
    def species_list(self) -> list[str]:
        """Get the list of species labels."""
        return self._species_list

    @property
    def num_species(self) -> int:
        """Get the number of species."""
        return len(self._species_list)

    @abstractmethod
    def _load_data(self) -> bool:
        """Load occurrence data from source.

        This method should be implemented by subclasses to load data from
        their specific source (file, database, API, etc.).

        Returns
        -------
        bool
            True if data was loaded successfully, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def _get_occurrence_vector(
        self,
        latitude: float,
        longitude: float,
        week: int,
    ) -> NDArray[np.float32] | None:
        """Get occurrence probabilities for all species at a location/time.

        This method should be implemented by subclasses to return occurrence
        probabilities for all species at the given location and week.

        Parameters
        ----------
        latitude : float
            Latitude in decimal degrees.
        longitude : float
            Longitude in decimal degrees.
        week : int
            Week of year (1-48).

        Returns
        -------
        NDArray[np.float32] | None
            Array of occurrence probabilities of shape (num_species,),
            or None if the location is not covered by the data.
        """
        raise NotImplementedError

    def _get_week_from_context(self, context: FilterContext) -> int:
        """Extract week number from context.

        Parameters
        ----------
        context : FilterContext
            Recording context.

        Returns
        -------
        int
            Week number (1-48).
        """
        if context.date is not None:
            # Calculate week number (1-48) from date
            day_of_year = context.date.timetuple().tm_yday
            # Each week is approximately 7.6 days (365/48)
            week = int((day_of_year - 1) / (365 / NUM_WEEKS)) + 1
            return min(max(week, 1), NUM_WEEKS)
        return self._default_week

    def filter_predictions(
        self,
        predictions: list[tuple[str, float]],
        context: FilterContext,
    ) -> list[tuple[str, float]]:
        """Filter predictions to species likely present at location/time.

        This method filters predictions based on occurrence probability data.
        Species with occurrence probability below the threshold are removed.

        Parameters
        ----------
        predictions : list[tuple[str, float]]
            List of (species_label, confidence) tuples from the model.
        context : FilterContext
            Recording context for filtering.

        Returns
        -------
        list[tuple[str, float]]
            Filtered list of predictions. If filtering cannot be applied,
            returns the original predictions unchanged.

        Notes
        -----
        - Species not in the occurrence data are included by default
        - Preserves original order and confidence scores
        - Logs filtered species at debug level
        """
        if not self._is_loaded:
            logger.debug(
                "Occurrence data not loaded, returning unfiltered predictions"
            )
            return predictions

        if not context.has_location:
            logger.debug(
                "No location in context, returning unfiltered predictions"
            )
            return predictions

        if not predictions:
            return predictions

        # Get species mask
        mask = self.get_species_mask(context)
        if mask is None:
            return predictions

        # Filter predictions
        filtered = []
        for species_label, confidence in predictions:
            species_idx = self._species_to_idx.get(species_label)

            if species_idx is None:
                # Species not in occurrence data, include by default
                logger.debug(
                    "Species '%s' not in occurrence data, including",
                    species_label,
                )
                filtered.append((species_label, confidence))
                continue

            if mask[species_idx]:
                filtered.append((species_label, confidence))
            else:
                logger.debug(
                    "Filtered out '%s' (occurrence below threshold)",
                    species_label,
                )

        logger.debug(
            "Filtered %d/%d predictions using occurrence data",
            len(predictions) - len(filtered),
            len(predictions),
        )
        return filtered

    def get_species_mask(
        self,
        context: FilterContext,
    ) -> NDArray[np.bool_] | None:
        """Get boolean mask indicating which species are likely present.

        Parameters
        ----------
        context : FilterContext
            Recording context for filtering.

        Returns
        -------
        NDArray[np.bool_] | None
            Boolean array of shape (num_species,) where True indicates
            the species is likely present (occurrence >= threshold).
            Returns None if filtering cannot be applied.
        """
        if not self._is_loaded:
            logger.debug("Occurrence data not loaded, returning None for mask")
            return None

        if not context.has_location:
            logger.debug("No location in context, returning None for mask")
            return None

        # Get week from context
        week = self._get_week_from_context(context)

        # Get occurrence vector - we know lat/lon are not None due to has_location check
        assert context.latitude is not None
        assert context.longitude is not None
        occurrence = self._get_occurrence_vector(
            context.latitude,
            context.longitude,
            week,
        )

        if occurrence is None:
            logger.debug(
                "No occurrence data for location (%.4f, %.4f)",
                context.latitude,
                context.longitude,
            )
            return None

        # Create boolean mask
        return occurrence >= self._threshold

    def get_occurrence_probability(
        self,
        species: str,
        context: FilterContext,
    ) -> float | None:
        """Get occurrence probability for a specific species.

        Parameters
        ----------
        species : str
            Species label.
        context : FilterContext
            Recording context for lookup.

        Returns
        -------
        float | None
            Occurrence probability (0-1), or None if unavailable.
        """
        if not self._is_loaded:
            return None

        if not context.has_location:
            return None

        species_idx = self._species_to_idx.get(species)
        if species_idx is None:
            return None

        week = self._get_week_from_context(context)

        # Get occurrence vector - we know lat/lon are not None
        assert context.latitude is not None
        assert context.longitude is not None
        occurrence = self._get_occurrence_vector(
            context.latitude,
            context.longitude,
            week,
        )

        if occurrence is None:
            return None

        return float(occurrence[species_idx])

    def get_likely_species(
        self,
        context: FilterContext,
    ) -> list[str]:
        """Get list of species likely present at location/time.

        Parameters
        ----------
        context : FilterContext
            Recording context for lookup.

        Returns
        -------
        list[str]
            List of species labels that are likely present
            (occurrence >= threshold). Empty list if filtering
            cannot be applied.
        """
        mask = self.get_species_mask(context)
        if mask is None:
            return []

        return [
            species
            for species, is_present in zip(self._species_list, mask)
            if is_present
        ]

    def __repr__(self) -> str:
        """Return string representation of the filter."""
        status = "loaded" if self._is_loaded else "not loaded"
        return (
            f"{self.__class__.__name__}("
            f"threshold={self._threshold}, "
            f"status={status}, "
            f"species={self.num_species})"
        )


class EBirdOccurrenceFilter(OccurrenceFilter):
    """Occurrence filter using eBird data stored in NPZ format.

    This filter uses eBird occurrence probabilities indexed by H3 geographic
    cells and week of year. The data is typically derived from eBird Status
    and Trends products.

    The NPZ file should contain:
    - 'occurrence': ndarray of shape (num_h3_cells, 48, num_species)
    - 'h3_cells': array of H3 cell IDs
    - 'species': array of species labels

    Parameters
    ----------
    data_path : Path | str
        Path to the species_presence.npz file.
    threshold : float, optional
        Minimum occurrence probability to consider a species present.
        Default is 0.03 (3%).
    h3_resolution : int, optional
        H3 resolution for geographic indexing. Default is 3.

    Attributes
    ----------
    data_path : Path
        Path to the NPZ data file.
    h3_resolution : int
        H3 resolution used for geographic indexing.

    Examples
    --------
    >>> filter = EBirdOccurrenceFilter(
    ...     "/path/to/species_presence.npz",
    ...     threshold=0.05,
    ... )
    >>> context = FilterContext(
    ...     latitude=35.6762, longitude=139.6503
    ... )
    >>> mask = filter.get_species_mask(context)

    Notes
    -----
    - Requires the h3 library for geographic indexing
    - Gracefully degrades if h3 is not available or data file is missing
    - H3 resolution 3 provides approximately 100km hexagons
    """

    def __init__(
        self,
        data_path: Path | str,
        threshold: float = DEFAULT_OCCURRENCE_THRESHOLD,
        h3_resolution: int = 3,
    ) -> None:
        """Initialize the eBird occurrence filter.

        Parameters
        ----------
        data_path : Path | str
            Path to the species_presence.npz file.
        threshold : float, optional
            Minimum occurrence probability. Default is 0.03.
        h3_resolution : int, optional
            H3 resolution for geographic indexing. Default is 3.
        """
        super().__init__(threshold=threshold)
        self._data_path = Path(data_path)
        self._h3_resolution = h3_resolution
        self._occurrence_data: NDArray[np.float32] | None = None
        self._h3_cells: NDArray | None = None
        self._h3_to_idx: dict[str, int] = {}

        # Try to load data on initialization
        self._try_load()

    @property
    def data_path(self) -> Path:
        """Get the data file path."""
        return self._data_path

    @property
    def h3_resolution(self) -> int:
        """Get the H3 resolution."""
        return self._h3_resolution

    def _try_load(self) -> None:
        """Attempt to load data, logging any errors."""
        if not self._data_path.exists():
            logger.info(
                "eBird occurrence data not found at %s. "
                "Occurrence filtering will be disabled.",
                self._data_path,
            )
            return

        try:
            if self._load_data():
                logger.info(
                    "Loaded eBird occurrence data: %d species, %d H3 cells",
                    self.num_species,
                    len(self._h3_to_idx),
                )
        except Exception as e:
            logger.warning(
                "Failed to load eBird occurrence data from %s: %s. "
                "Occurrence filtering will be disabled.",
                self._data_path,
                e,
            )

    def _load_data(self) -> bool:
        """Load occurrence data from NPZ file.

        Returns
        -------
        bool
            True if data was loaded successfully.

        Raises
        ------
        ValueError
            If the file has invalid format or missing required keys.
        """
        data = np.load(self._data_path, allow_pickle=True)

        # Validate required keys
        required_keys = {"occurrence", "h3_cells", "species"}
        missing_keys = required_keys - set(data.keys())
        if missing_keys:
            raise ValueError(f"Data file missing required keys: {missing_keys}")

        occurrence_data = data["occurrence"].astype(np.float32)
        h3_cells = data["h3_cells"]
        species_list = list(data["species"])

        # Validate shape before assigning to instance variables
        if occurrence_data.ndim != 3:
            raise ValueError(
                f"Occurrence data must be 3D (h3_cells, weeks, species), "
                f"got shape {occurrence_data.shape}"
            )

        num_cells, num_weeks, num_species = occurrence_data.shape
        if num_weeks != NUM_WEEKS:
            logger.warning(
                "Occurrence data has %d weeks, expected %d",
                num_weeks,
                NUM_WEEKS,
            )

        if num_species != len(species_list):
            raise ValueError(
                f"Species count mismatch: data has {num_species}, "
                f"labels have {len(species_list)}"
            )

        # Build lookup dictionaries (before assigning to instance variables)
        species_to_idx = {
            species: idx for idx, species in enumerate(species_list)
        }
        h3_to_idx = {
            str(cell): idx for idx, cell in enumerate(h3_cells)
        }

        # Assign to instance variables after validation
        self._occurrence_data = occurrence_data
        self._h3_cells = h3_cells
        self._species_list = species_list
        self._species_to_idx = species_to_idx
        self._h3_to_idx = h3_to_idx

        self._is_loaded = True
        return True

    def _get_h3_cell(self, latitude: float, longitude: float) -> str | None:
        """Convert lat/lon to H3 cell ID.

        Parameters
        ----------
        latitude : float
            Latitude in decimal degrees.
        longitude : float
            Longitude in decimal degrees.

        Returns
        -------
        str | None
            H3 cell ID, or None if h3 library is not available.
        """
        try:
            import h3
        except ImportError:
            logger.debug("h3 library not available for location lookup")
            return None

        h3_cell = h3.latlng_to_cell(latitude, longitude, self._h3_resolution)
        return str(h3_cell)

    def _get_occurrence_vector(
        self,
        latitude: float,
        longitude: float,
        week: int,
    ) -> NDArray[np.float32] | None:
        """Get occurrence probabilities for all species at location/time.

        Parameters
        ----------
        latitude : float
            Latitude in decimal degrees.
        longitude : float
            Longitude in decimal degrees.
        week : int
            Week of year (1-48).

        Returns
        -------
        NDArray[np.float32] | None
            Array of occurrence probabilities, or None if location not found.
        """
        if not self._is_loaded or self._occurrence_data is None:
            return None

        # Get H3 cell
        h3_cell = self._get_h3_cell(latitude, longitude)
        if h3_cell is None:
            return None

        if h3_cell not in self._h3_to_idx:
            logger.debug("H3 cell %s not found in occurrence data", h3_cell)
            return None

        cell_idx = self._h3_to_idx[h3_cell]
        # Convert 1-based week to 0-based index
        week_idx = week - 1

        return self._occurrence_data[cell_idx, week_idx, :]

    def __repr__(self) -> str:
        """Return string representation of the filter."""
        status = "loaded" if self._is_loaded else "not loaded"
        return (
            f"EBirdOccurrenceFilter("
            f"data_path={self._data_path}, "
            f"threshold={self._threshold}, "
            f"status={status}, "
            f"species={self.num_species})"
        )
