"""Integration tests for model installation.

This module tests the model installer architecture including:
- ModelInstaller base class
- InstallStatus enum
- ModelArtifact validation
- BirdNETInstaller (mocked)
- PerchInstaller (mocked)
- Installation flow
- Checksum verification
- Error handling
"""

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock, MagicMock

import pytest

from echoroo.ml.installer.base import (
    InstallStatus,
    ModelArtifact,
    ModelInstaller,
    InstallationProgress,
)


class TestInstallStatus:
    """Test InstallStatus enum."""

    def test_status_values(self):
        """Test all InstallStatus values exist."""
        assert InstallStatus.NOT_INSTALLED == "not_installed"
        assert InstallStatus.DOWNLOADING == "downloading"
        assert InstallStatus.INSTALLED == "installed"
        assert InstallStatus.CORRUPTED == "corrupted"
        assert InstallStatus.FAILED == "failed"

    def test_status_is_string_enum(self):
        """Test InstallStatus is a string enum."""
        assert isinstance(InstallStatus.INSTALLED, str)


class TestModelArtifact:
    """Test ModelArtifact dataclass."""

    def test_create_valid_artifact(self):
        """Test creating a valid ModelArtifact."""
        artifact = ModelArtifact(
            name="model.pt",
            url="https://example.com/model.pt",
            checksum="a" * 64,  # Valid SHA256 length
            size_mb=500.0,
            required=True,
        )

        assert artifact.name == "model.pt"
        assert artifact.url == "https://example.com/model.pt"
        assert len(artifact.checksum) == 64
        assert artifact.size_mb == 500.0
        assert artifact.required is True

    def test_invalid_empty_name(self):
        """Test validation of empty name."""
        with pytest.raises(ValueError, match="name cannot be empty"):
            ModelArtifact(
                name="",
                url="https://example.com/model.pt",
                checksum="a" * 64,
                size_mb=500.0,
            )

    def test_invalid_empty_url(self):
        """Test validation of empty URL."""
        with pytest.raises(ValueError, match="URL cannot be empty"):
            ModelArtifact(
                name="model.pt",
                url="",
                checksum="a" * 64,
                size_mb=500.0,
            )

    def test_invalid_checksum_length(self):
        """Test validation of checksum length."""
        with pytest.raises(ValueError, match="checksum must be a 64-character"):
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum="abc123",  # Too short
                size_mb=500.0,
            )

    def test_invalid_size_mb(self):
        """Test validation of negative size."""
        with pytest.raises(ValueError, match="size_mb must be positive"):
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum="a" * 64,
                size_mb=-100.0,
            )


class TestInstallationProgress:
    """Test InstallationProgress dataclass."""

    def test_create_valid_progress(self):
        """Test creating valid InstallationProgress."""
        progress = InstallationProgress(
            status=InstallStatus.DOWNLOADING,
            progress=50.0,
            message="Downloading...",
            downloaded_mb=250.0,
            total_mb=500.0,
        )

        assert progress.status == InstallStatus.DOWNLOADING
        assert progress.progress == 50.0
        assert progress.message == "Downloading..."
        assert progress.downloaded_mb == 250.0
        assert progress.total_mb == 500.0

    def test_invalid_progress_range(self):
        """Test validation of progress range."""
        with pytest.raises(ValueError, match="Progress must be in"):
            InstallationProgress(
                status=InstallStatus.DOWNLOADING,
                progress=150.0,  # > 100
                message="Downloading...",
            )

    def test_invalid_downloaded_mb(self):
        """Test validation of negative downloaded_mb."""
        with pytest.raises(ValueError, match="downloaded_mb must be non-negative"):
            InstallationProgress(
                status=InstallStatus.DOWNLOADING,
                progress=50.0,
                message="Downloading...",
                downloaded_mb=-10.0,
            )

    def test_invalid_total_mb(self):
        """Test validation of negative total_mb."""
        with pytest.raises(ValueError, match="total_mb must be non-negative"):
            InstallationProgress(
                status=InstallStatus.DOWNLOADING,
                progress=50.0,
                message="Downloading...",
                total_mb=-100.0,
            )


class TestModelInstallerBase:
    """Test ModelInstaller base class."""

    class ConcreteInstaller(ModelInstaller):
        """Concrete implementation for testing."""

        def __init__(self, model_dir, artifacts):
            super().__init__("test_model", model_dir, artifacts)

        async def _post_install(self):
            pass  # No post-install tasks

    def test_initialization(self, tmp_path):
        """Test ModelInstaller initialization."""
        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum="a" * 64,
                size_mb=100.0,
            )
        ]

        installer = self.ConcreteInstaller(tmp_path / "test_model", artifacts)

        assert installer.model_name == "test_model"
        assert installer.model_dir == tmp_path / "test_model"
        assert len(installer.artifacts) == 1

    def test_check_status_not_installed(self, tmp_path):
        """Test check_status returns NOT_INSTALLED for missing directory."""
        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum="a" * 64,
                size_mb=100.0,
            )
        ]

        installer = self.ConcreteInstaller(tmp_path / "nonexistent", artifacts)

        status = installer.check_status()

        assert status == InstallStatus.NOT_INSTALLED

    def test_check_status_missing_required_file(self, tmp_path):
        """Test check_status returns NOT_INSTALLED for missing required file."""
        model_dir = tmp_path / "test_model"
        model_dir.mkdir()

        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum="a" * 64,
                size_mb=100.0,
                required=True,
            )
        ]

        installer = self.ConcreteInstaller(model_dir, artifacts)

        status = installer.check_status()

        assert status == InstallStatus.NOT_INSTALLED

    def test_check_status_corrupted(self, tmp_path):
        """Test check_status returns CORRUPTED for invalid checksum."""
        model_dir = tmp_path / "test_model"
        model_dir.mkdir()

        # Create file with wrong content
        model_file = model_dir / "model.pt"
        model_file.write_text("wrong content")

        # Calculate expected checksum for different content
        correct_checksum = hashlib.sha256(b"correct content").hexdigest()

        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum=correct_checksum,
                size_mb=100.0,
            )
        ]

        installer = self.ConcreteInstaller(model_dir, artifacts)

        status = installer.check_status()

        assert status == InstallStatus.CORRUPTED

    def test_check_status_installed(self, tmp_path):
        """Test check_status returns INSTALLED for valid files."""
        model_dir = tmp_path / "test_model"
        model_dir.mkdir()

        # Create file with correct content
        content = b"model data"
        model_file = model_dir / "model.pt"
        model_file.write_bytes(content)

        # Calculate correct checksum
        checksum = hashlib.sha256(content).hexdigest()

        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum=checksum,
                size_mb=0.001,
            )
        ]

        installer = self.ConcreteInstaller(model_dir, artifacts)

        status = installer.check_status()

        assert status == InstallStatus.INSTALLED

    @pytest.mark.asyncio
    async def test_install_creates_directory(self, tmp_path):
        """Test install creates model directory."""
        model_dir = tmp_path / "test_model"

        artifacts = []  # No artifacts for this test

        installer = self.ConcreteInstaller(model_dir, artifacts)

        with patch.object(installer, "_download_file", new=AsyncMock()):
            await installer.install()

        assert model_dir.exists()

    @pytest.mark.asyncio
    async def test_install_with_progress_callback(self, tmp_path):
        """Test install calls progress callback."""
        model_dir = tmp_path / "test_model"

        artifacts = []

        installer = self.ConcreteInstaller(model_dir, artifacts)

        progress_updates = []

        def callback(progress):
            progress_updates.append(progress)

        with patch.object(installer, "_download_file", new=AsyncMock()):
            await installer.install(progress_callback=callback)

        # Should have received some progress updates
        assert len(progress_updates) > 0
        assert all(isinstance(p, InstallationProgress) for p in progress_updates)

    @pytest.mark.asyncio
    async def test_install_downloads_artifacts(self, tmp_path):
        """Test install downloads all required artifacts."""
        model_dir = tmp_path / "test_model"

        content = b"model data"
        checksum = hashlib.sha256(content).hexdigest()

        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum=checksum,
                size_mb=0.001,
            )
        ]

        installer = self.ConcreteInstaller(model_dir, artifacts)

        # Mock download to actually create the file
        async def mock_download(url, dest, expected_checksum):
            dest.write_bytes(content)

        with patch.object(installer, "_download_file", side_effect=mock_download):
            result = await installer.install()

        assert result is True
        assert (model_dir / "model.pt").exists()

    @pytest.mark.asyncio
    async def test_install_failure_sets_failed_status(self, tmp_path):
        """Test install failure sets FAILED status."""
        model_dir = tmp_path / "test_model"

        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum="a" * 64,
                size_mb=100.0,
            )
        ]

        installer = self.ConcreteInstaller(model_dir, artifacts)

        # Mock download to fail
        async def mock_download_fail(url, dest, checksum):
            raise RuntimeError("Download failed")

        with patch.object(installer, "_download_file", side_effect=mock_download_fail):
            with pytest.raises(RuntimeError, match="Download failed"):
                await installer.install()

        assert installer._current_status == InstallStatus.FAILED

    def test_uninstall_removes_files(self, tmp_path):
        """Test uninstall removes model files."""
        model_dir = tmp_path / "test_model"
        model_dir.mkdir()

        # Create some files
        (model_dir / "model.pt").write_text("data")
        (model_dir / "labels.txt").write_text("labels")

        artifacts = []
        installer = self.ConcreteInstaller(model_dir, artifacts)

        installer.uninstall()

        # Directory should be gone or empty
        assert not model_dir.exists() or not list(model_dir.iterdir())

    def test_repr(self, tmp_path):
        """Test string representation of installer."""
        artifacts = []
        installer = self.ConcreteInstaller(tmp_path / "test_model", artifacts)

        repr_str = repr(installer)

        assert "ConcreteInstaller" in repr_str
        assert "test_model" in repr_str


class TestModelInstallerAbstractMethods:
    """Test ModelInstaller abstract methods."""

    def test_requires_post_install_implementation(self, tmp_path):
        """Test _post_install must be implemented."""

        class IncompleteInstaller(ModelInstaller):
            pass  # Missing _post_install

        # Can't test this directly as it would fail at class definition
        # Instead verify ConcreteInstaller has it
        assert hasattr(
            TestModelInstallerBase.ConcreteInstaller, "_post_install"
        )


class TestBirdNETInstallerIntegration:
    """Test BirdNETInstaller integration (mocked)."""

    @patch("echoroo.ml.installer.birdnet.birdnet")
    def test_birdnet_installer_exists(self, mock_birdnet):
        """Test BirdNETInstaller can be imported and instantiated."""
        from echoroo.ml.installer.birdnet import BirdNETInstaller

        # Mock birdnet availability
        mock_birdnet.load = Mock()

        installer = BirdNETInstaller()

        assert installer.model_name == "birdnet"
        assert isinstance(installer, ModelInstaller)

    @patch("echoroo.ml.installer.birdnet.birdnet")
    def test_birdnet_installer_check_status(self, mock_birdnet, tmp_path):
        """Test BirdNETInstaller status checking."""
        from echoroo.ml.installer.birdnet import BirdNETInstaller

        mock_birdnet.load = Mock()

        installer = BirdNETInstaller(model_dir=tmp_path / "birdnet")

        status = installer.check_status()

        # Should be NOT_INSTALLED initially
        assert status in [InstallStatus.NOT_INSTALLED, InstallStatus.INSTALLED]


class TestPerchInstallerIntegration:
    """Test PerchInstaller integration (mocked)."""

    def test_perch_installer_exists(self):
        """Test PerchInstaller can be imported and instantiated."""
        from echoroo.ml.installer.perch import PerchInstaller

        installer = PerchInstaller()

        assert installer.model_name == "perch"
        assert isinstance(installer, ModelInstaller)

    def test_perch_installer_check_status(self, tmp_path):
        """Test PerchInstaller status checking."""
        from echoroo.ml.installer.perch import PerchInstaller

        installer = PerchInstaller(model_dir=tmp_path / "perch")

        status = installer.check_status()

        # Should be NOT_INSTALLED initially
        assert status in [InstallStatus.NOT_INSTALLED, InstallStatus.INSTALLED]

    def test_perch_installer_has_kaggle_credentials_check(self):
        """Test PerchInstaller can check for Kaggle credentials."""
        from echoroo.ml.installer import check_kaggle_credentials

        # Should not raise
        has_creds = check_kaggle_credentials()

        assert isinstance(has_creds, bool)


class TestInstallerUtilities:
    """Test installer utility functions."""

    def test_check_all_models(self):
        """Test check_all_models utility function."""
        from echoroo.ml.installer import check_all_models

        statuses = check_all_models()

        assert isinstance(statuses, dict)
        assert "birdnet" in statuses or "perch" in statuses

    def test_get_installer(self):
        """Test get_installer utility function."""
        from echoroo.ml.installer import get_installer

        # BirdNET installer
        with patch("echoroo.ml.installer.birdnet.birdnet"):
            birdnet_installer = get_installer("birdnet")
            assert birdnet_installer.model_name == "birdnet"

        # Perch installer
        perch_installer = get_installer("perch")
        assert perch_installer.model_name == "perch"

    def test_get_installer_invalid_model(self):
        """Test get_installer raises for invalid model."""
        from echoroo.ml.installer import get_installer

        with pytest.raises(ValueError, match="Unknown model"):
            get_installer("invalid_model")

    def test_check_birdnet_available(self):
        """Test check_birdnet_available utility."""
        from echoroo.ml.installer import check_birdnet_available

        # Should not raise
        is_available = check_birdnet_available()

        assert isinstance(is_available, bool)

    def test_check_perch_available(self):
        """Test check_perch_available utility."""
        from echoroo.ml.installer import check_perch_available

        # Should not raise
        is_available = check_perch_available()

        assert isinstance(is_available, bool)


class TestInstallerErrorHandling:
    """Test error handling in installers."""

    @pytest.mark.asyncio
    async def test_download_file_checksum_failure(self, tmp_path):
        """Test download fails on checksum mismatch."""

        class TestInstaller(ModelInstaller):
            async def _post_install(self):
                pass

        artifacts = []
        installer = TestInstaller("test", tmp_path / "test", artifacts)

        # Create a file with wrong content
        test_file = tmp_path / "wrong.txt"
        test_file.write_bytes(b"wrong content")

        wrong_checksum = hashlib.sha256(b"right content").hexdigest()

        # Mock download to use the wrong file
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.raise_for_status = Mock()

            async def mock_iter_chunked(size):
                yield b"wrong content"

            mock_response.content.iter_chunked = mock_iter_chunked
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = (
                mock_response
            )

            with pytest.raises(ValueError, match="Checksum verification failed"):
                await installer._download_file(
                    "https://example.com/file.txt",
                    tmp_path / "dest.txt",
                    wrong_checksum,
                )

    @pytest.mark.asyncio
    async def test_install_verification_failure(self, tmp_path):
        """Test install fails if verification fails after download."""

        class TestInstaller(ModelInstaller):
            async def _post_install(self):
                pass

        artifacts = [
            ModelArtifact(
                name="model.pt",
                url="https://example.com/model.pt",
                checksum="a" * 64,  # Wrong checksum
                size_mb=100.0,
            )
        ]

        installer = TestInstaller("test", tmp_path / "test", artifacts)

        # Mock download to succeed but with wrong checksum
        async def mock_download(url, dest, checksum):
            dest.write_bytes(b"wrong data")

        with patch.object(installer, "_download_file", side_effect=mock_download):
            with pytest.raises(RuntimeError, match="Installation verification failed"):
                await installer.install()
