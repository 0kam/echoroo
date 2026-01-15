"""Machine learning modules for Echoroo.

This package provides ML inference capabilities including:
- Core abstractions: ModelLoader, InferenceEngine, ModelSpecification, InferenceResult
- Model registry: Dynamic model discovery and loading
- Species filters: SpeciesFilter, PassThroughFilter, BirdNETGeoFilter
- Species resolver: GBIF-based species name resolution with caching
- BirdNET: Bird species identification from audio and general-purpose audio embeddings
- Audio preprocessing utilities
- Background worker for processing inference jobs
- Vector similarity search for audio clips
- Active learning utilities for model improvement

Model Registration
------------------
Models register themselves when their module is imported. To ensure all models
are available, import the specific model modules or use the convenience imports:

>>> from echoroo.ml import birdnet, perch  # Import to register models
>>> from echoroo.ml.registry import ModelRegistry
>>> print(ModelRegistry.available_models())
['birdnet', 'perch']
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
from echoroo.ml.active_learning import (
    ActiveLearningConfig,
    SigmoidClassifier,
    compute_cosine_similarities,
    compute_initial_samples,
    compute_similarities,
    farthest_first_selection,
    get_dataset_clip_embeddings,
    run_active_learning_iteration,
)
from echoroo.ml.distance_metrics import DistanceMetric
from echoroo.ml.search import SearchFilter, SimilarityResult, VectorSearch, vector_search

# Type hints for lazy-loaded workers and resolvers (avoids circular imports at runtime)
if TYPE_CHECKING:
    from echoroo.ml.species_detection_worker import SpeciesDetectionWorker as SpeciesDetectionWorker
    from echoroo.ml.species_filter_worker import SpeciesFilterWorker as SpeciesFilterWorker
    from echoroo.ml.inference_batch_worker import InferenceBatchWorker as InferenceBatchWorker
    from echoroo.ml.species_resolver import SpeciesInfo as SpeciesInfo
    from echoroo.ml.species_resolver import SpeciesResolver as SpeciesResolver


# Import workers and resolvers lazily to avoid circular import at runtime
# (worker imports from echoroo.api, which imports from echoroo.schemas,
#  which imports from echoroo.ml)
# (species_resolver imports from echoroo.api, which causes circular import)
def __getattr__(name: str):
    if name == "SpeciesDetectionWorker":
        from echoroo.ml.species_detection_worker import SpeciesDetectionWorker
        return SpeciesDetectionWorker
    if name == "SpeciesFilterWorker":
        from echoroo.ml.species_filter_worker import SpeciesFilterWorker
        return SpeciesFilterWorker
    if name == "InferenceBatchWorker":
        from echoroo.ml.inference_batch_worker import InferenceBatchWorker
        return InferenceBatchWorker
    if name == "SpeciesInfo":
        from echoroo.ml.species_resolver import SpeciesInfo
        return SpeciesInfo
    if name == "SpeciesResolver":
        from echoroo.ml.species_resolver import SpeciesResolver
        return SpeciesResolver
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# Import model modules to trigger registration
# These imports ensure models are registered when echoroo.ml is imported
from echoroo.ml import birdnet as birdnet  # noqa: F401
from echoroo.ml import perch as perch  # noqa: F401

__all__ = [
    # Core abstractions
    "InferenceEngine",
    "InferenceResult",
    "ModelLoader",
    "ModelSpecification",
    # Workers
    "SpeciesDetectionWorker",
    "SpeciesFilterWorker",
    "InferenceBatchWorker",
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
    # Distance metrics
    "DistanceMetric",
    # Active learning
    "ActiveLearningConfig",
    "SigmoidClassifier",
    "compute_cosine_similarities",
    "compute_initial_samples",
    "compute_similarities",
    "farthest_first_selection",
    "get_dataset_clip_embeddings",
    "run_active_learning_iteration",
    # Species resolver
    "SpeciesInfo",
    "SpeciesResolver",
    # Model modules (for explicit imports)
    "birdnet",
    "perch",
]
