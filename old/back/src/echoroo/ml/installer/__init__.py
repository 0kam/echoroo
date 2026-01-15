"""ML model installation and management.

This module provides infrastructure for downloading, installing, and managing
ML model files in Echoroo. It includes installers for BirdNET and a unified
interface for checking installation status and triggering downloads.

The installation system supports:
- Async downloads with progress tracking
- SHA256 checksum verification
- Atomic file operations
- Model-specific post-installation logic
- Multiple model backends (pip packages, direct downloads)

Example
-------
Using the installers:

>>> from echoroo.ml.installer import get_installer, check_all_models
>>>
>>> # Check all models
>>> status = check_all_models()
>>> print(f"BirdNET: {status['birdnet']}")
>>>
>>> # Install a specific model
>>> installer = get_installer("birdnet")
>>> if installer.check_status() != InstallStatus.INSTALLED:
...     await installer.install()
"""

from echoroo.ml.installer.base import (
    InstallStatus,
    InstallationProgress,
    ModelArtifact,
    ModelInstaller,
)
from echoroo.ml.installer.birdnet import (
    BirdNETInstaller,
    check_birdnet_available,
)

__all__ = [
    "BirdNETInstaller",
    "InstallStatus",
    "InstallationProgress",
    "ModelArtifact",
    "ModelInstaller",
    "check_all_models",
    "check_birdnet_available",
    "get_installer",
]


def get_installer(model_name: str) -> ModelInstaller:
    """Get the installer for a specific model.

    Parameters
    ----------
    model_name : str
        Name of the model ("birdnet").

    Returns
    -------
    ModelInstaller
        Installer instance for the specified model.

    Raises
    ------
    ValueError
        If model_name is not recognized.

    Examples
    --------
    >>> installer = get_installer("birdnet")
    >>> status = installer.check_status()
    >>> print(f"Status: {status.value}")
    """
    model_name = model_name.lower()

    if model_name == "birdnet":
        return BirdNETInstaller()
    else:
        raise ValueError(
            f"Unknown model: {model_name}. "
            f"Available models: birdnet"
        )


def check_all_models() -> dict[str, InstallStatus]:
    """Check installation status of all available models.

    Returns
    -------
    dict[str, InstallStatus]
        Dictionary mapping model names to their installation status.

    Examples
    --------
    >>> status = check_all_models()
    >>> for model, status in status.items():
    ...     print(f"{model}: {status.value}")
    birdnet: installed
    """
    results = {}

    for model_name in ["birdnet"]:
        try:
            installer = get_installer(model_name)
            results[model_name] = installer.check_status()
        except Exception as e:
            # If we can't create installer, mark as failed
            results[model_name] = InstallStatus.FAILED

    return results
