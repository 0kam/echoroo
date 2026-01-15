"""Perch model constants.

This module centralizes all Perch-specific constants to ensure consistency
across the loader, inference engine, and other components.

Constants
---------
PERCH_VERSION : str
    Version of the Perch model.
SAMPLE_RATE : int
    Audio sample rate expected by Perch (32kHz).
SEGMENT_DURATION : float
    Duration of each audio segment in seconds (5.0s).
SEGMENT_SAMPLES : int
    Number of samples per segment (160,000).
EMBEDDING_DIM : int
    Dimension of the embedding vector (1536).
"""

__all__ = [
    "PERCH_VERSION",
    "SAMPLE_RATE",
    "SEGMENT_DURATION",
    "SEGMENT_SAMPLES",
    "EMBEDDING_DIM",
]

# Model version
PERCH_VERSION = "2.0"

# Audio specifications
SAMPLE_RATE = 32000  # Hz (target sample rate for Perch)

# Segment configuration
SEGMENT_DURATION = 5.0  # seconds
SEGMENT_SAMPLES = int(SAMPLE_RATE * SEGMENT_DURATION)  # 160,000 samples

# Model specifications
EMBEDDING_DIM = 1536
