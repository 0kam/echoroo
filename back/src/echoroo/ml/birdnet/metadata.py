"""BirdNET metadata filter module.

This module provides location and season-based filtering for BirdNET species
predictions using eBird occurrence data. Species predictions can be filtered
to only include species that are likely present at a given location and time
of year.

This module is a thin wrapper around the generic EBirdOccurrenceFilter,
providing BirdNET-specific defaults for metadata file location.

Example
-------
>>> from echoroo.ml.birdnet.metadata import BirdNETMetadataFilter
>>> from echoroo.ml.filters import FilterContext
>>> from datetime import date
>>>
>>> filter = BirdNETMetadataFilter()
>>> context = FilterContext(
...     latitude=35.6762,
...     longitude=139.6503,
...     date=date(2024, 5, 15),
... )
>>>
>>> # Filter predictions
>>> predictions = [
...     ("Turdus merula_Common Blackbird", 0.85),
...     ("Passer montanus_Eurasian Tree Sparrow", 0.72),
... ]
>>> filtered = filter.filter_predictions(predictions, context)
>>>
>>> # Get species likely present at location/time
>>> likely_species = filter.get_likely_species(context)

Notes
-----
For generic occurrence filtering, use EBirdOccurrenceFilter directly from
echoroo.ml.filters.occurrence.
"""

from __future__ import annotations

import logging
from pathlib import Path

from echoroo.ml.birdnet.constants import (
    DEFAULT_MODEL_DIR,
    METADATA_FILENAME,
)
from echoroo.ml.filters.occurrence import (
    DEFAULT_OCCURRENCE_THRESHOLD,
    EBirdOccurrenceFilter,
)

__all__ = [
    "BirdNETMetadataFilter",
    "MetadataNotLoadedError",
]

logger = logging.getLogger(__name__)


class MetadataNotLoadedError(Exception):
    """Raised when metadata file cannot be loaded."""

    pass


class BirdNETMetadataFilter(EBirdOccurrenceFilter):
    """Filter species predictions by location and season.

    This class uses eBird occurrence data to filter BirdNET species predictions
    to only include species that are likely present at a given location and
    time of year. This can significantly reduce false positives by excluding
    species that don't occur in the recording area.

    This class extends EBirdOccurrenceFilter with BirdNET-specific defaults
    for the metadata file location.

    Parameters
    ----------
    metadata_path : Path | None, optional
        Path to the species_presence.npz file.
        If None, defaults to ~/.echoroo/models/birdnet/species_presence.npz
    threshold : float, optional
        Minimum occurrence probability to consider a species present.
        Default is 0.03 (3%).

    Attributes
    ----------
    metadata_path : Path
        Path to the metadata file.
    is_loaded : bool
        Whether the metadata has been successfully loaded.
    threshold : float
        Current occurrence probability threshold.

    Examples
    --------
    >>> from echoroo.ml.filters import FilterContext
    >>> from datetime import date
    >>>
    >>> filter = BirdNETMetadataFilter()
    >>> context = FilterContext(
    ...     latitude=35.6762,
    ...     longitude=139.6503,
    ...     date=date(2024, 5, 15),
    ... )
    >>>
    >>> # Filter predictions to likely species
    >>> predictions = [("Passer montanus_Eurasian Tree Sparrow", 0.85)]
    >>> filtered = filter.filter_predictions(predictions, context)
    >>>
    >>> # Get species mask for batch processing
    >>> mask = filter.get_species_mask(context)
    >>>
    >>> # Get list of likely species
    >>> likely = filter.get_likely_species(context)

    Notes
    -----
    If the metadata file does not exist or cannot be loaded, all filtering
    methods will return unfiltered results (pass-through behavior). This
    allows the system to gracefully degrade when metadata is unavailable.
    """

    def __init__(
        self,
        metadata_path: Path | None = None,
        threshold: float = DEFAULT_OCCURRENCE_THRESHOLD,
    ) -> None:
        """Initialize the metadata filter.

        Parameters
        ----------
        metadata_path : Path | None, optional
            Path to the species_presence.npz file.
            If None, defaults to ~/.echoroo/models/birdnet/species_presence.npz
        threshold : float, optional
            Minimum occurrence probability threshold. Default is 0.03.
        """
        data_path = metadata_path or (DEFAULT_MODEL_DIR / METADATA_FILENAME)
        super().__init__(
            data_path=data_path,
            threshold=threshold,
        )

    @property
    def metadata_path(self) -> Path:
        """Get the metadata file path (alias for data_path)."""
        return self._data_path

    def __repr__(self) -> str:
        """Return string representation of the filter."""
        status = "loaded" if self._is_loaded else "not loaded"
        return (
            f"BirdNETMetadataFilter("
            f"metadata_path={self._data_path}, "
            f"threshold={self._threshold}, "
            f"status={status}, "
            f"species={self.num_species})"
        )
