"""Prediction filtering for ML model outputs.

This module provides a unified abstraction for filtering species predictions
from ML models using contextual information (location, time, habitat, etc.).

The filtering system is model-agnostic, allowing any inference engine to use
any filter implementation. This decouples the filtering logic from inference.

Key Components
--------------
Base Classes:
- FilterContext: Encapsulates recording metadata
- PredictionFilter: Abstract base class for filters
- PassThroughFilter: Default no-op implementation

Occurrence-Based Filters:
- OccurrenceFilter: Abstract base for occurrence data filtering
- EBirdOccurrenceFilter: Uses eBird occurrence data (NPZ format)

Example
-------
>>> from echoroo.ml.filters import (
...     FilterContext,
...     EBirdOccurrenceFilter,
... )
>>> from datetime import date
>>>
>>> # Create context from recording metadata
>>> context = FilterContext(
...     latitude=35.6762,
...     longitude=139.6503,
...     date=date(2024, 5, 15),
... )
>>>
>>> # Use occurrence filter
>>> filter = EBirdOccurrenceFilter("/path/to/species_presence.npz")
>>> predictions = [("species_a", 0.95), ("species_b", 0.82)]
>>> filtered = filter.filter_predictions(predictions, context)
>>>
>>> # Or use pass-through for no filtering
>>> from echoroo.ml.filters import PassThroughFilter
>>> no_filter = PassThroughFilter()
>>> result = no_filter.filter_predictions(predictions, context)
>>> assert result == predictions

Architecture
------------
The filter architecture follows these principles:

1. **Separation of Concerns**: Inference engines produce raw predictions,
   filters refine them based on context.

2. **Composability**: Filters can be combined (future: ChainedFilter).

3. **Graceful Degradation**: Filters return unfiltered results when they
   cannot apply filtering (missing data, invalid context, etc.).

4. **Model Agnostic**: Any model's predictions can be filtered by any filter
   as long as species labels are compatible.
"""

from echoroo.ml.filters.base import (
    FilterContext,
    PassThroughFilter,
    PredictionFilter,
    TimeOfDay,
)
from echoroo.ml.filters.occurrence import (
    DEFAULT_OCCURRENCE_THRESHOLD,
    EBirdOccurrenceFilter,
    OccurrenceDataSource,
    OccurrenceFilter,
)

__all__ = [
    # Base classes
    "FilterContext",
    "PredictionFilter",
    "PassThroughFilter",
    "TimeOfDay",
    # Occurrence-based filters
    "OccurrenceFilter",
    "OccurrenceDataSource",
    "EBirdOccurrenceFilter",
    "DEFAULT_OCCURRENCE_THRESHOLD",
]
