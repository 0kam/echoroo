"""Perch model integration for Echoroo.

This module provides functionality to load and use the Perch V2 model
for audio embedding extraction from recordings.

Perch is a general-purpose audio embedding model developed by Google Research
for bioacoustic analysis. It is trained on a large corpus of audio data and
produces embeddings that capture acoustic features useful for downstream
classification and similarity tasks.

Model specifications:
- Input: 5 second audio at 32kHz (160,000 samples)
- Output: 1536-dim embedding vector
- Backend: birdnet library (ProtoBuf models via load_perch_v2())
"""

from echoroo.ml.perch.constants import (
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    SEGMENT_SAMPLES,
    VERSION,
)
from echoroo.ml.perch.exceptions import PerchModelNotFoundError
from echoroo.ml.perch.inference import PerchInference
from echoroo.ml.perch.loader import PerchLoader
from echoroo.ml.registry import ModelRegistry

__all__ = [
    # Constants
    "VERSION",
    "EMBEDDING_DIM",
    "SAMPLE_RATE",
    "SEGMENT_DURATION",
    "SEGMENT_SAMPLES",
    # Classes
    "PerchInference",
    "PerchLoader",
    "PerchModelNotFoundError",
]

# Register Perch V2 with the model registry
ModelRegistry.register(
    name="perch",
    loader_class=PerchLoader,
    engine_class=PerchInference,
    description="Perch V2 general-purpose audio embedding model (via birdnet)",
)
