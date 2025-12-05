"""BirdNET model installer for automated setup.

This module provides an installer for BirdNET model files, specifically
handling the species presence metadata file (species_presence.npz).

The BirdNET model itself is installed via the `birdnet` Python package,
so this installer only manages auxiliary metadata files that enhance
the model's functionality with geographic filtering.

Installation details:
- Default directory: ~/.echoroo/models/birdnet/
- Required files:
  - species_presence.npz: Geographic species presence data for filtering
- Dependencies: birdnet package (installed separately)

Example
-------
Installing BirdNET metadata:

>>> from echoroo.ml.installer.birdnet import BirdNETInstaller
>>>
>>> installer = BirdNETInstaller()
>>> status = installer.check_status()
>>> if status != InstallStatus.INSTALLED:
...     await installer.install(progress_callback=lambda p: print(p.message))
>>> print("BirdNET metadata ready")
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from echoroo.ml.installer.base import (
    InstallStatus,
    ModelArtifact,
    ModelInstaller,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BirdNETInstaller",
    "DEFAULT_BIRDNET_DIR",
    "check_birdnet_available",
]

# Default installation directory
DEFAULT_BIRDNET_DIR = Path.home() / ".echoroo" / "models" / "birdnet"

# Species presence data artifact
# Note: This is a placeholder URL and checksum. Replace with actual values
# when the file is hosted.
SPECIES_PRESENCE_ARTIFACT = ModelArtifact(
    name="species_presence.npz",
    url="https://example.com/birdnet/species_presence.npz",
    checksum="0" * 64,  # Placeholder - replace with actual SHA256
    size_mb=10.0,  # Approximate size
    required=False,  # Optional metadata file
)


def check_birdnet_available() -> bool:
    """Check if the birdnet package is installed.

    BirdNET model weights are distributed via the `birdnet` pip package.
    This function checks if that package is available in the environment.

    Returns
    -------
    bool
        True if birdnet package is installed, False otherwise.

    Examples
    --------
    >>> if check_birdnet_available():
    ...     print("BirdNET package is ready")
    ... else:
    ...     print("Install with: pip install birdnet")
    """
    spec = importlib.util.find_spec("birdnet")
    return spec is not None


class BirdNETInstaller(ModelInstaller):
    """Installer for BirdNET model metadata files.

    This installer manages auxiliary metadata files for BirdNET, such as
    the species presence data used for geographic filtering. The core
    BirdNET model itself is installed via the `birdnet` pip package.

    The installer verifies that the birdnet package is available and
    handles downloading optional metadata files.

    Parameters
    ----------
    model_dir : Path | None, optional
        Directory where metadata files will be installed.
        If None, uses DEFAULT_BIRDNET_DIR.
        Default is None.

    Attributes
    ----------
    model_dir : Path
        Installation directory for metadata files.

    Examples
    --------
    >>> installer = BirdNETInstaller()
    >>>
    >>> # Check if birdnet package is installed
    >>> if not check_birdnet_available():
    ...     print("Please install: pip install birdnet")
    ...
    >>> # Check installation status
    >>> status = installer.check_status()
    >>> print(f"Status: {status.value}")
    >>>
    >>> # Install metadata files
    >>> if status == InstallStatus.NOT_INSTALLED:
    ...     await installer.install()

    Notes
    -----
    The BirdNET model itself (~100MB) is distributed via the `birdnet`
    package and is automatically downloaded when first used. This installer
    only manages optional metadata files.
    """

    def __init__(self, model_dir: Path | None = None):
        """Initialize the BirdNET installer.

        Parameters
        ----------
        model_dir : Path | None, optional
            Installation directory. If None, uses DEFAULT_BIRDNET_DIR.
            Default is None.
        """
        if model_dir is None:
            model_dir = DEFAULT_BIRDNET_DIR

        # Currently only species presence data, but can be extended
        artifacts = [SPECIES_PRESENCE_ARTIFACT]

        super().__init__(
            model_name="birdnet",
            model_dir=model_dir,
            artifacts=artifacts,
        )

    def check_status(self) -> InstallStatus:
        """Check BirdNET installation status.

        This method verifies:
        1. The birdnet package is installed
        2. Optional metadata files are present (if any)

        Returns
        -------
        InstallStatus
            Installation status:
            - INSTALLED: birdnet package available (metadata is optional)
            - NOT_INSTALLED: birdnet package not found

        Examples
        --------
        >>> installer = BirdNETInstaller()
        >>> status = installer.check_status()
        >>> if status == InstallStatus.INSTALLED:
        ...     print("BirdNET is ready to use")
        """
        # Check if birdnet package is available
        if not check_birdnet_available():
            logger.warning(
                "BirdNET package not installed. "
                "Install with: pip install birdnet"
            )
            return InstallStatus.NOT_INSTALLED

        # Check metadata files (optional)
        # Since metadata is optional, we return INSTALLED even if not present
        metadata_status = super().check_status()
        if metadata_status == InstallStatus.CORRUPTED:
            logger.warning("BirdNET metadata files are corrupted")
            return InstallStatus.CORRUPTED

        logger.debug("BirdNET package is available")
        return InstallStatus.INSTALLED

    async def _post_install(self) -> None:
        """Perform post-installation tasks for BirdNET.

        Currently no additional setup is required after downloading
        metadata files. This method can be extended in the future
        for tasks like:
        - Extracting compressed archives
        - Building search indexes
        - Validating metadata integrity
        """
        logger.info("BirdNET metadata installation complete")

    def get_metadata_path(self, filename: str) -> Path | None:
        """Get path to a metadata file if it exists.

        Parameters
        ----------
        filename : str
            Name of the metadata file (e.g., "species_presence.npz").

        Returns
        -------
        Path | None
            Path to the file if it exists and is verified, None otherwise.

        Examples
        --------
        >>> installer = BirdNETInstaller()
        >>> presence_path = installer.get_metadata_path("species_presence.npz")
        >>> if presence_path:
        ...     data = np.load(presence_path)
        """
        file_path = self.model_dir / filename

        if not file_path.exists():
            return None

        # Find artifact to get checksum
        artifact = next(
            (a for a in self.artifacts if a.name == filename),
            None,
        )

        if artifact is None:
            return None

        # Verify checksum
        if not self._verify_checksum(file_path, artifact.checksum):
            logger.warning(f"Checksum verification failed for {filename}")
            return None

        return file_path

    def __repr__(self) -> str:
        """Return string representation of the installer.

        Returns
        -------
        str
            String representation including package and metadata status.
        """
        package_available = check_birdnet_available()
        status = self.check_status()
        return (
            f"BirdNETInstaller("
            f"package_installed={package_available}, "
            f"metadata_status={status.value}, "
            f"dir={self.model_dir})"
        )
