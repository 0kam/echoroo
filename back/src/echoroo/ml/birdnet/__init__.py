"""BirdNET model integration for Echoroo.

This module provides functionality to load and use the BirdNET V2.4 model
for bird species identification from audio recordings.

BirdNET is a deep learning model developed by the Cornell Lab of Ornithology
and Chemnitz University of Technology for identifying bird species from
audio recordings.

Model specifications:
- Input: 3 second audio at 48kHz (144,000 samples)
- Output: 1024-dim embedding + species classification logits

The module now inherits from base classes (ModelLoader, InferenceEngine)
to provide a consistent interface with other ML models in Echoroo.
"""

from echoroo.ml.birdnet.constants import (
    BIRDNET_VERSION,
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    SEGMENT_SAMPLES,
)
from echoroo.ml.birdnet.inference import BirdNETInference
from echoroo.ml.birdnet.loader import BirdNETLoader, BirdNETNotLoadedError
from echoroo.ml.birdnet.metadata import (
    BirdNETMetadataFilter,
    MetadataNotLoadedError,
)
from echoroo.ml.registry import ModelRegistry

__all__ = [
    # Constants
    "BIRDNET_VERSION",
    "EMBEDDING_DIM",
    "SAMPLE_RATE",
    "SEGMENT_DURATION",
    "SEGMENT_SAMPLES",
    # Classes
    "BirdNETInference",
    "BirdNETLoader",
    "BirdNETMetadataFilter",
    "BirdNETNotLoadedError",
    "MetadataNotLoadedError",
]

# Register BirdNET with the model registry
ModelRegistry.register(
    name="birdnet",
    loader_class=BirdNETLoader,
    engine_class=BirdNETInference,
    filter_class=BirdNETMetadataFilter,
    description="BirdNET V2.4 bird species identification model",
)
