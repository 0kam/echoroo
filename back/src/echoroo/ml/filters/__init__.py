"""Species filtering for ML model predictions.

This module provides a simple abstraction for filtering species predictions
based on geographic and temporal context. All filters normalize their output
to GBIF taxon keys for consistent matching across different data sources.

Example
-------
>>> from echoroo.ml.filters import FilterContext, BirdNETGeoFilter
>>>
>>> filter = BirdNETGeoFilter()
>>> context = FilterContext(latitude=35.67, longitude=139.65, week=19)
>>>
>>> # Get all species probabilities (normalized to GBIF taxon keys)
>>> probs = await filter.get_species_probabilities(context, session)
>>> # {"2493098": 0.85, ...}  # GBIF taxon keys
>>>
>>> # Or filter predictions directly
>>> predictions = [("2493098", 0.85)]  # GBIF taxon keys
>>> filtered = await filter.filter_predictions(predictions, context, session, threshold=0.03)
"""

from echoroo.ml.filters.base import (
    FilterContext,
    PassThroughFilter,
    SpeciesFilter,
)
from echoroo.ml.filters.birdnet_geo import BirdNETGeoFilter

__all__ = [
    "FilterContext",
    "SpeciesFilter",
    "PassThroughFilter",
    "BirdNETGeoFilter",
]
