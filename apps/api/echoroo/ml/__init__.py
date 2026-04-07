"""ML model wrappers for audio species detection.

This package provides:
- Base abstractions (ModelLoader, InferenceEngine, ModelSpecification, InferenceResult)
- ModelRegistry for dynamic model discovery
- BirdNET V2.4 implementation (48kHz, 3s segments, 1024-dim embeddings)
- Perch V2 implementation (32kHz, 5s segments, 1536-dim embeddings)
- BirdNETWrapper (legacy, kept for backward compatibility)

Models are automatically registered with ModelRegistry when this package
is imported via the birdnet and perch sub-package imports below.
"""

# Import sub-packages to trigger automatic model registration
import echoroo.ml.birdnet  # noqa: F401
import echoroo.ml.perch  # noqa: F401
from echoroo.ml.base import InferenceEngine, InferenceResult, ModelLoader, ModelSpecification
from echoroo.ml.birdnet_wrapper import BirdNETDetection, BirdNETWrapper
from echoroo.ml.registry import ModelInfo, ModelNotFoundError, ModelRegistry

__all__ = [
    # Base abstractions
    "InferenceEngine",
    "InferenceResult",
    "ModelLoader",
    "ModelSpecification",
    # Registry
    "ModelInfo",
    "ModelNotFoundError",
    "ModelRegistry",
    # Legacy wrapper (kept for backward compatibility)
    "BirdNETDetection",
    "BirdNETWrapper",
]
