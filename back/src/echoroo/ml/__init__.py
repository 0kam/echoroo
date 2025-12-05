"""Machine learning modules for Echoroo.

This package provides ML inference capabilities including:
- Core abstractions: ModelLoader, InferenceEngine, ModelSpecification, InferenceResult
- Model registry: Dynamic model discovery and loading
- Prediction filters: PredictionFilter, OccurrenceFilter, EBirdOccurrenceFilter
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

from echoroo.ml.base import (
    InferenceEngine,
    InferenceResult,
    ModelLoader,
    ModelSpecification,
)
from echoroo.ml.filters import (
    DEFAULT_OCCURRENCE_THRESHOLD,
    EBirdOccurrenceFilter,
    FilterContext,
    OccurrenceFilter,
    PassThroughFilter,
    PredictionFilter,
)
from echoroo.ml.registry import ModelInfo, ModelNotFoundError, ModelRegistry
from echoroo.ml.search import SearchFilter, SimilarityResult, VectorSearch, vector_search
from echoroo.ml.worker import InferenceWorker

# Import model modules to trigger registration
# These imports ensure models are registered when echoroo.ml is imported
from echoroo.ml import birdnet as birdnet  # noqa: F401

__all__ = [
    # Core abstractions
    "InferenceEngine",
    "InferenceResult",
    "InferenceWorker",
    "ModelLoader",
    "ModelSpecification",
    # Model registry
    "ModelRegistry",
    "ModelInfo",
    "ModelNotFoundError",
    # Prediction filters
    "FilterContext",
    "PredictionFilter",
    "PassThroughFilter",
    "OccurrenceFilter",
    "EBirdOccurrenceFilter",
    "DEFAULT_OCCURRENCE_THRESHOLD",
    # Search
    "SearchFilter",
    "SimilarityResult",
    "VectorSearch",
    "vector_search",
    # Model modules (for explicit imports)
    "birdnet",
]
