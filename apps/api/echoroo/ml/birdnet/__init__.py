"""BirdNET model integration for Echoroo.

This module provides functionality to load and use the BirdNET V2.4 model
for bird species identification from audio recordings.

BirdNET is a deep learning model developed by the Cornell Lab of Ornithology
and Chemnitz University of Technology.

Model specifications:
- Input: 3 second audio at 48kHz (144,000 samples)
- Output: 1024-dim embedding + species classification logits
"""

from echoroo.ml.birdnet.constants import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DEFAULT_TOP_K,
    EMBEDDING_DIM,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    SEGMENT_SAMPLES,
    VERSION,
)
from echoroo.ml.birdnet.inference import BirdNETInference
from echoroo.ml.birdnet.loader import BirdNETLoader
from echoroo.ml.registry import ModelRegistry

__all__ = [
    # Constants
    "VERSION",
    "EMBEDDING_DIM",
    "SAMPLE_RATE",
    "SEGMENT_DURATION",
    "SEGMENT_SAMPLES",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_TOP_K",
    # Classes
    "BirdNETInference",
    "BirdNETLoader",
]

# Register BirdNET with the model registry
ModelRegistry.register(
    name="birdnet",
    loader_class=BirdNETLoader,
    engine_class=BirdNETInference,
    description="BirdNET V2.4 bird species identification model",
)
