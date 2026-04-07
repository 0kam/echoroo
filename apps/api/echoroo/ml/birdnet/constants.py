"""BirdNET model constants.

This module centralizes all BirdNET-specific constants to ensure consistency
across the loader, inference engine, and other components.

Constants
---------
VERSION : str
    Version of the BirdNET model.
SAMPLE_RATE : int
    Audio sample rate expected by BirdNET (48kHz).
SEGMENT_DURATION : float
    Duration of each audio segment in seconds (3.0s).
SEGMENT_SAMPLES : int
    Number of samples per segment (144,000).
EMBEDDING_DIM : int
    Dimension of the embedding vector (1024).
DEFAULT_CONFIDENCE_THRESHOLD : float
    Default confidence threshold for predictions.
DEFAULT_TOP_K : int
    Default number of top predictions to return.
"""

__all__ = [
    "VERSION",
    "SAMPLE_RATE",
    "SEGMENT_DURATION",
    "SEGMENT_SAMPLES",
    "EMBEDDING_DIM",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_TOP_K",
]

# Model version
VERSION = "2.4"

# Audio specifications
SAMPLE_RATE = 48000  # Hz
SEGMENT_DURATION = 3.0  # seconds
SEGMENT_SAMPLES = int(SAMPLE_RATE * SEGMENT_DURATION)  # 144,000 samples

# Model specifications
EMBEDDING_DIM = 1024

# Inference defaults
DEFAULT_CONFIDENCE_THRESHOLD = 0.1
DEFAULT_TOP_K = 10
