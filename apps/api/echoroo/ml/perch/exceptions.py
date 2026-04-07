"""Perch module exception classes."""

__all__ = [
    "PerchModelNotFoundError",
]


class PerchModelNotFoundError(Exception):
    """Raised when the Perch model cannot be loaded.

    This exception is raised when:
    - The birdnet library cannot load the model
    - Model download fails
    - Model files are corrupted or missing
    """
