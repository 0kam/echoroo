"""BirdNET model constants.

This module centralizes all BirdNET-specific constants to ensure consistency
across the loader, inference engine, and other components.

Constants
---------
BIRDNET_VERSION : str
    Version of the BirdNET model.
SAMPLE_RATE : int
    Audio sample rate expected by BirdNET (48kHz).
SEGMENT_DURATION : float
    Duration of each audio segment in seconds (3.0s).
SEGMENT_SAMPLES : int
    Number of samples per segment (144,000).
EMBEDDING_DIM : int
    Dimension of the embedding vector (1024).
DEFAULT_MODEL_DIR : Path
    Default directory for storing BirdNET model files.
DEFAULT_CONFIDENCE_THRESHOLD : float
    Default confidence threshold for predictions.
DEFAULT_TOP_K : int
    Default number of top predictions to return.
"""

from pathlib import Path

__all__ = [
    "BIRDNET_VERSION",
    "SAMPLE_RATE",
    "SEGMENT_DURATION",
    "SEGMENT_SAMPLES",
    "EMBEDDING_DIM",
    "DEFAULT_MODEL_DIR",
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "DEFAULT_TOP_K",
    "METADATA_FILENAME",
]

# Model version
BIRDNET_VERSION = "2.4"

# Audio specifications
SAMPLE_RATE = 48000  # Hz
SEGMENT_DURATION = 3.0  # seconds
SEGMENT_SAMPLES = int(SAMPLE_RATE * SEGMENT_DURATION)  # 144,000 samples

# Model specifications
EMBEDDING_DIM = 1024

# File paths
DEFAULT_MODEL_DIR = Path.home() / ".echoroo" / "models" / "birdnet"
METADATA_FILENAME = "species_presence.npz"

# Inference defaults
DEFAULT_CONFIDENCE_THRESHOLD = 0.1
DEFAULT_TOP_K = 10
