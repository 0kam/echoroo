"""Distance metrics for vector similarity search."""

from enum import Enum

class DistanceMetric(str, Enum):
    """Supported distance metrics for vector search."""
    COSINE = "cosine"
    EUCLIDEAN = "euclidean"
