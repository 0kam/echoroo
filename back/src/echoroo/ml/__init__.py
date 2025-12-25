"""Machine learning modules for Echoroo.

This package provides ML inference capabilities including:
- Core abstractions: ModelLoader, InferenceEngine, ModelSpecification, InferenceResult
- Model registry: Dynamic model discovery and loading
- Species filters: SpeciesFilter, PassThroughFilter, BirdNETGeoFilter
- BirdNET: Bird species identification from audio and general-purpose audio embeddings
- Audio preprocessing utilities
- Background worker for processing inference jobs
- Vector similarity search for audio clips

Model Registration
------------------
Models register themselves when their module is imported. To ensure all models
are available, import the specific model modules or use the convenience imports:

>>> from echoroo.ml import birdnet  # Import to register models
>>> from echoroo.ml.registry import ModelRegistry
>>> print(ModelRegistry.available_models())
['birdnet']
"""

from typing import TYPE_CHECKING

from echoroo.ml.base import (
    InferenceEngine,
    InferenceResult,
    ModelLoader,
    ModelSpecification,
)
from echoroo.ml.filters import (
    BirdNETGeoFilter,
    FilterContext,
    PassThroughFilter,
    SpeciesFilter,
)
from echoroo.ml.registry import ModelInfo, ModelNotFoundError, ModelRegistry
from echoroo.ml.search import SearchFilter, SimilarityResult, VectorSearch, vector_search

# Type hints for lazy-loaded workers (avoids circular imports at runtime)
if TYPE_CHECKING:
    from echoroo.ml.species_detection_worker import SpeciesDetectionWorker as SpeciesDetectionWorker
    from echoroo.ml.species_filter_worker import SpeciesFilterWorker as SpeciesFilterWorker


# Import workers lazily to avoid circular import at runtime
# (worker imports from echoroo.api, which imports from echoroo.schemas,
#  which imports from echoroo.ml)
def __getattr__(name: str):
    if name == "SpeciesDetectionWorker":
        from echoroo.ml.species_detection_worker import SpeciesDetectionWorker
        return SpeciesDetectionWorker
    if name == "SpeciesFilterWorker":
        from echoroo.ml.species_filter_worker import SpeciesFilterWorker
        return SpeciesFilterWorker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Import model modules to trigger registration
# These imports ensure models are registered when echoroo.ml is imported
from echoroo.ml import birdnet as birdnet  # noqa: F401

__all__ = [
    # Core abstractions
    "InferenceEngine",
    "InferenceResult",
    "ModelLoader",
    "ModelSpecification",
    # Workers
    "SpeciesDetectionWorker",
    "SpeciesFilterWorker",
    # Model registry
    "ModelRegistry",
    "ModelInfo",
    "ModelNotFoundError",
    # Species filters
    "FilterContext",
    "SpeciesFilter",
    "PassThroughFilter",
    "BirdNETGeoFilter",
    # Search
    "SearchFilter",
    "SimilarityResult",
    "VectorSearch",
    "vector_search",
    # Model modules (for explicit imports)
    "birdnet",
]
