"""Perch module exception classes.

This module defines common exceptions used throughout the Perch model
integration modules.
"""

__all__ = [
    "PerchModelNotFoundError",
]


class PerchModelNotFoundError(Exception):
    """Raised when Perch model cannot be loaded.

    This exception is raised when:
    - The birdnet library cannot load the model
    - Model download fails
    - Model files are corrupted or missing
    """

    pass
