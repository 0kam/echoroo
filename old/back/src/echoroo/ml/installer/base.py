"""Base classes for ML model installation and management.

This module provides the foundational abstractions for downloading, verifying,
and installing ML model files. It defines interfaces for tracking installation
status, managing downloads with progress callbacks, and verifying file integrity.

The design follows these principles:
- Async operations for non-blocking downloads
- SHA256 checksum verification for file integrity
- Progress callbacks for UI feedback
- Atomic file operations (download to temp, move on success)
- Comprehensive error handling and logging
- Thread-safe status checks

Example
-------
Implementing a custom model installer:

>>> from echoroo.ml.installer.base import ModelInstaller, ModelArtifact, InstallStatus
>>>
>>> class MyModelInstaller(ModelInstaller):
...     def __init__(self):
...         artifacts = [
...             ModelArtifact(
...                 name="model.pt",
...                 url="https://example.com/model.pt",
...                 checksum="abc123...",
...                 size_mb=500.0,
...                 required=True,
...             )
...         ]
...         super().__init__(
...             model_name="my_model",
...             model_dir=Path.home() / ".echoroo" / "models" / "my_model",
...             artifacts=artifacts,
...         )
...
...     async def _post_install(self):
...         # Custom post-installation logic
...         pass
>>>
>>> installer = MyModelInstaller()
>>> status = installer.check_status()
>>> if status == InstallStatus.NOT_INSTALLED:
...     await installer.install()
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

import aiohttp

logger = logging.getLogger(__name__)


class InstallStatus(str, Enum):
    """Status of a model installation.

    Attributes
    ----------
    NOT_INSTALLED : str
        Model files are not present on disk.
    DOWNLOADING : str
        Model files are currently being downloaded.
    INSTALLED : str
        Model files are present and verified.
    CORRUPTED : str
        Model files exist but checksum verification failed.
    FAILED : str
        Installation attempt failed with an error.
    """

    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    INSTALLED = "installed"
    CORRUPTED = "corrupted"
    FAILED = "failed"


@dataclass
class ModelArtifact:
    """Metadata for a model artifact (file) to be downloaded.

    Attributes
    ----------
    name : str
        Filename of the artifact (e.g., "model.pt", "labels.txt").
    url : str
        Download URL for the artifact.
    checksum : str
        Expected SHA256 checksum for file verification.
    size_mb : float
        Expected file size in megabytes.
    required : bool
        Whether this artifact is required for the model to function.
        Default is True.

    Examples
    --------
    >>> artifact = ModelArtifact(
    ...     name="model_weights.pt",
    ...     url="https://example.com/model.pt",
    ...     checksum="abc123...",
    ...     size_mb=500.0,
    ...     required=True,
    ... )
    >>> print(f"Artifact: {artifact.name} ({artifact.size_mb}MB)")
    Artifact: model_weights.pt (500.0MB)
    """

    name: str
    url: str
    checksum: str
    size_mb: float
    required: bool = True

    def __post_init__(self):
        """Validate artifact metadata."""
        if not self.name:
            raise ValueError("Artifact name cannot be empty")
        if not self.url:
            raise ValueError("Artifact URL cannot be empty")
        if not self.checksum or len(self.checksum) != 64:
            raise ValueError("Artifact checksum must be a 64-character SHA256 hash")
        if self.size_mb <= 0:
            raise ValueError(f"Artifact size_mb must be positive, got {self.size_mb}")


@dataclass
class InstallationProgress:
    """Progress information for ongoing installation.

    This class provides detailed status information during model installation,
    including download progress and current status messages.

    Attributes
    ----------
    status : InstallStatus
        Current installation status.
    progress : float
        Overall progress percentage (0.0 to 100.0).
    message : str
        Human-readable status message.
    downloaded_mb : float
        Amount of data downloaded in megabytes.
        Default is 0.0.
    total_mb : float
        Total data to download in megabytes.
        Default is 0.0.

    Examples
    --------
    >>> progress = InstallationProgress(
    ...     status=InstallStatus.DOWNLOADING,
    ...     progress=50.0,
    ...     message="Downloading model.pt...",
    ...     downloaded_mb=250.0,
    ...     total_mb=500.0,
    ... )
    >>> print(f"Progress: {progress.progress:.1f}% - {progress.message}")
    Progress: 50.0% - Downloading model.pt...
    """

    status: InstallStatus
    progress: float
    message: str
    downloaded_mb: float = 0.0
    total_mb: float = 0.0

    def __post_init__(self):
        """Validate progress data."""
        if not 0.0 <= self.progress <= 100.0:
            raise ValueError(f"Progress must be in [0, 100], got {self.progress}")
        if self.downloaded_mb < 0:
            raise ValueError(
                f"downloaded_mb must be non-negative, got {self.downloaded_mb}"
            )
        if self.total_mb < 0:
            raise ValueError(f"total_mb must be non-negative, got {self.total_mb}")


class ModelInstaller(ABC):
    """Abstract base class for model installation.

    This class provides a framework for downloading, verifying, and installing
    ML model files from remote sources. It handles common tasks like checksum
    verification, progress tracking, and atomic file operations.

    Subclasses must implement any model-specific installation logic in the
    `_post_install` method.

    Parameters
    ----------
    model_name : str
        Name of the model being installed (e.g., "birdnet", "perch").
    model_dir : Path
        Directory where model files will be installed.
    artifacts : list[ModelArtifact]
        List of artifacts (files) to download and verify.

    Attributes
    ----------
    model_name : str
        Name of the model.
    model_dir : Path
        Installation directory.
    artifacts : list[ModelArtifact]
        List of artifacts to install.

    Examples
    --------
    >>> installer = MyModelInstaller()
    >>> status = installer.check_status()
    >>> if status != InstallStatus.INSTALLED:
    ...     await installer.install(progress_callback=lambda p: print(p.message))
    """

    def __init__(
        self,
        model_name: str,
        model_dir: Path,
        artifacts: list[ModelArtifact],
    ):
        """Initialize the model installer.

        Parameters
        ----------
        model_name : str
            Name of the model being installed.
        model_dir : Path
            Directory where model files will be installed.
        artifacts : list[ModelArtifact]
            List of artifacts to download and verify.
        """
        self.model_name = model_name
        self.model_dir = Path(model_dir)
        self.artifacts = artifacts
        self._current_status = InstallStatus.NOT_INSTALLED

    def check_status(self) -> InstallStatus:
        """Check the current installation status.

        This method verifies that all required artifacts are present and
        have valid checksums.

        Returns
        -------
        InstallStatus
            Current installation status:
            - INSTALLED: All required files present and verified
            - CORRUPTED: Files present but checksum verification failed
            - NOT_INSTALLED: Required files missing

        Examples
        --------
        >>> installer = BirdNETInstaller()
        >>> status = installer.check_status()
        >>> if status == InstallStatus.INSTALLED:
        ...     print("Model ready to use")
        """
        if not self.model_dir.exists():
            return InstallStatus.NOT_INSTALLED

        # Check each required artifact
        for artifact in self.artifacts:
            if not artifact.required:
                continue

            file_path = self.model_dir / artifact.name

            if not file_path.exists():
                logger.debug(
                    f"{self.model_name}: Required file {artifact.name} not found"
                )
                return InstallStatus.NOT_INSTALLED

            # Verify checksum
            if not self._verify_checksum(file_path, artifact.checksum):
                logger.warning(
                    f"{self.model_name}: Checksum verification failed for {artifact.name}"
                )
                return InstallStatus.CORRUPTED

        logger.debug(f"{self.model_name}: All required files verified")
        return InstallStatus.INSTALLED

    async def install(
        self,
        progress_callback: Callable[[InstallationProgress], None] | None = None,
    ) -> bool:
        """Install the model by downloading all artifacts.

        This method downloads all required artifacts, verifies their checksums,
        and calls any model-specific post-installation logic.

        Parameters
        ----------
        progress_callback : Callable[[InstallationProgress], None] | None, optional
            Callback function to receive progress updates.
            Default is None (no progress reporting).

        Returns
        -------
        bool
            True if installation succeeded, False otherwise.

        Raises
        ------
        Exception
            Any exceptions during download or verification are logged
            and re-raised.

        Examples
        --------
        >>> def on_progress(progress):
        ...     print(f"{progress.progress:.0f}% - {progress.message}")
        >>> await installer.install(progress_callback=on_progress)
        0% - Starting installation...
        25% - Downloading model.pt...
        100% - Installation complete
        """
        try:
            self._current_status = InstallStatus.DOWNLOADING
            self._report_progress(
                progress_callback,
                0.0,
                "Starting installation...",
            )

            # Create model directory
            self.model_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Installing {self.model_name} to {self.model_dir}")

            # Calculate total download size
            total_mb = sum(a.size_mb for a in self.artifacts if a.required)
            downloaded_mb = 0.0

            # Download each artifact
            for idx, artifact in enumerate(self.artifacts):
                if not artifact.required:
                    continue

                # Update progress
                artifact_progress = (idx / len(self.artifacts)) * 100
                self._report_progress(
                    progress_callback,
                    artifact_progress,
                    f"Downloading {artifact.name}...",
                    downloaded_mb,
                    total_mb,
                )

                # Download file
                dest_path = self.model_dir / artifact.name
                await self._download_file(
                    artifact.url,
                    dest_path,
                    artifact.checksum,
                )

                downloaded_mb += artifact.size_mb
                logger.info(
                    f"{self.model_name}: Downloaded {artifact.name} "
                    f"({artifact.size_mb:.1f}MB)"
                )

            # Post-installation tasks
            self._report_progress(
                progress_callback,
                90.0,
                "Finalizing installation...",
                downloaded_mb,
                total_mb,
            )
            await self._post_install()

            # Verify installation
            status = self.check_status()
            if status != InstallStatus.INSTALLED:
                raise RuntimeError(
                    f"Installation verification failed: {status}"
                )

            self._current_status = InstallStatus.INSTALLED
            self._report_progress(
                progress_callback,
                100.0,
                "Installation complete",
                downloaded_mb,
                total_mb,
            )

            logger.info(f"{self.model_name} installation completed successfully")
            return True

        except Exception as e:
            self._current_status = InstallStatus.FAILED
            logger.error(f"{self.model_name} installation failed: {e}")
            self._report_progress(
                progress_callback,
                0.0,
                f"Installation failed: {str(e)}",
            )
            raise

    def uninstall(self) -> None:
        """Uninstall the model by removing all files.

        This method removes the model directory and all its contents.
        Use with caution as this operation cannot be undone.

        Examples
        --------
        >>> installer = BirdNETInstaller()
        >>> installer.uninstall()
        >>> assert installer.check_status() == InstallStatus.NOT_INSTALLED
        """
        if not self.model_dir.exists():
            logger.info(f"{self.model_name}: Already uninstalled")
            return

        # Remove all files in model directory
        for file_path in self.model_dir.glob("*"):
            if file_path.is_file():
                file_path.unlink()
                logger.debug(f"{self.model_name}: Removed {file_path.name}")

        # Remove directory if empty
        if not list(self.model_dir.iterdir()):
            self.model_dir.rmdir()
            logger.info(f"{self.model_name}: Uninstalled from {self.model_dir}")
        else:
            logger.warning(
                f"{self.model_name}: Directory not empty after uninstall: {self.model_dir}"
            )

        self._current_status = InstallStatus.NOT_INSTALLED

    async def _download_file(
        self,
        url: str,
        dest: Path,
        expected_checksum: str,
    ) -> None:
        """Download a file from URL and verify its checksum.

        This method downloads a file to a temporary location, verifies
        its checksum, and then moves it to the final destination atomically.

        Parameters
        ----------
        url : str
            URL to download from.
        dest : Path
            Destination file path.
        expected_checksum : str
            Expected SHA256 checksum.

        Raises
        ------
        aiohttp.ClientError
            If download fails.
        ValueError
            If checksum verification fails.
        """
        logger.info(f"Downloading {url} to {dest}")

        # Download to temporary file
        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        response.raise_for_status()

                        # Write to temp file
                        with open(tmp_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)

                # Verify checksum
                if not self._verify_checksum(tmp_path, expected_checksum):
                    raise ValueError(
                        f"Checksum verification failed for {dest.name}. "
                        f"Expected: {expected_checksum[:8]}..., "
                        f"got: {self._calculate_checksum(tmp_path)[:8]}..."
                    )

                # Move to final destination
                tmp_path.replace(dest)
                logger.debug(f"Successfully downloaded and verified {dest.name}")

            except Exception:
                # Clean up temp file on error
                if tmp_path.exists():
                    tmp_path.unlink()
                raise

    def _verify_checksum(self, path: Path, expected: str) -> bool:
        """Verify file checksum matches expected value.

        Parameters
        ----------
        path : Path
            Path to file to verify.
        expected : str
            Expected SHA256 checksum.

        Returns
        -------
        bool
            True if checksum matches, False otherwise.
        """
        actual = self._calculate_checksum(path)
        return actual == expected

    def _calculate_checksum(self, path: Path) -> str:
        """Calculate SHA256 checksum of a file.

        Parameters
        ----------
        path : Path
            Path to file.

        Returns
        -------
        str
            SHA256 checksum as hex string.
        """
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _report_progress(
        self,
        callback: Callable[[InstallationProgress], None] | None,
        progress: float,
        message: str,
        downloaded_mb: float = 0.0,
        total_mb: float = 0.0,
    ) -> None:
        """Report installation progress via callback.

        Parameters
        ----------
        callback : Callable[[InstallationProgress], None] | None
            Progress callback function, or None to skip reporting.
        progress : float
            Progress percentage (0-100).
        message : str
            Status message.
        downloaded_mb : float, optional
            Downloaded data in MB. Default is 0.0.
        total_mb : float, optional
            Total data in MB. Default is 0.0.
        """
        if callback is None:
            return

        progress_info = InstallationProgress(
            status=self._current_status,
            progress=progress,
            message=message,
            downloaded_mb=downloaded_mb,
            total_mb=total_mb,
        )
        callback(progress_info)

    @abstractmethod
    async def _post_install(self) -> None:
        """Perform model-specific post-installation tasks.

        This method is called after all artifacts have been downloaded
        and verified. Subclasses can override this to perform additional
        setup steps like extracting archives, compiling models, etc.

        Raises
        ------
        Exception
            Any exceptions raised during post-installation are propagated
            to the caller and will cause the installation to fail.
        """
        pass

    def __repr__(self) -> str:
        """Return string representation of the installer.

        Returns
        -------
        str
            String representation including model name and status.
        """
        status = self.check_status()
        return (
            f"{self.__class__.__name__}("
            f"model={self.model_name}, "
            f"status={status.value}, "
            f"dir={self.model_dir})"
        )
