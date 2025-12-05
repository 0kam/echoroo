"""Test suite for the setup endpoints."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from echoroo.system import create_app
from echoroo.system.settings import (
    Settings,
    get_settings,
    load_settings_from_file,
    write_settings_to_file,
)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    base = tmp_path / "data"
    monkeypatch.setenv("ECHOROO_DATA_DIR", str(base))
    return base


@pytest.fixture
def setup_settings(tmp_path, data_dir):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(exist_ok=True)
    settings = Settings(
        db_dialect="sqlite",
        db_name=str(tmp_path / "test.db"),
        audio_dir=audio_dir,
        open_on_startup=False,
        log_to_file=False,
        log_to_stdout=True,
    )
    write_settings_to_file(settings)
    get_settings.cache_clear()
    return settings


@pytest.fixture
def setup_client(setup_settings: Settings):
    app = create_app(setup_settings)
    app.dependency_overrides[get_settings] = lambda: setup_settings
    with TestClient(app) as client:
        yield client


def test_get_audio_directory_returns_current_value(
    setup_client: TestClient,
    setup_settings: Settings,
):
    response = setup_client.get("/api/v1/setup/audio_dir/")
    assert response.status_code == 200
    payload = response.json()
    assert Path(payload["audio_dir"]) == setup_settings.audio_dir


def test_update_audio_directory_persists_to_settings_file(
    setup_client: TestClient,
    tmp_path,
):
    new_dir = tmp_path / "new_audio"
    new_dir.mkdir()

    response = setup_client.post(
        "/api/v1/setup/audio_dir/",
        json={"audio_dir": str(new_dir)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert Path(payload["audio_dir"]) == new_dir.resolve()

    get_settings.cache_clear()
    updated = load_settings_from_file()
    assert updated.audio_dir == new_dir.resolve()


# ============================================================================
# ML Model Setup Tests
# ============================================================================


from unittest.mock import Mock, patch, AsyncMock


class TestGetModelsStatus:
    """Test GET /api/v1/setup/models/status/ endpoint."""

    @patch("echoroo.routes.setup.check_all_models")
    @patch("echoroo.routes.setup.check_birdnet_available")
    @patch("echoroo.routes.setup.check_perch_available")
    @patch("echoroo.routes.setup.check_kaggle_credentials")
    def test_get_models_status_success(
        self,
        mock_kaggle,
        mock_perch,
        mock_birdnet,
        mock_check_all,
        setup_client,
    ):
        """Test getting models status successfully."""
        from echoroo.ml.installer.base import InstallStatus

        # Setup mocks
        mock_check_all.return_value = {
            "birdnet": InstallStatus.INSTALLED,
            "perch": InstallStatus.NOT_INSTALLED,
        }
        mock_birdnet.return_value = True
        mock_perch.return_value = True
        mock_kaggle.return_value = False

        # Make request
        response = setup_client.get("/api/v1/setup/models/status/")

        # Verify response
        assert response.status_code == 200
        data = response.json()

        assert "birdnet" in data
        assert "perch" in data
        assert "created_at" in data

    @patch("echoroo.routes.setup.check_all_models")
    def test_get_models_status_error_handling(self, mock_check_all, setup_client):
        """Test error handling in get_models_status."""
        # Setup mock to raise exception
        mock_check_all.side_effect = RuntimeError("Failed to check")

        # Make request
        response = setup_client.get("/api/v1/setup/models/status/")

        # Verify error response
        assert response.status_code == 500


class TestInstallModel:
    """Test POST /api/v1/setup/models/{model}/install/ endpoint."""

    @patch("echoroo.routes.setup.get_installer")
    def test_install_birdnet_success(self, mock_get_installer, setup_client):
        """Test installing BirdNET successfully."""
        from echoroo.ml.installer.base import InstallStatus

        # Setup mock installer
        mock_installer = Mock()
        mock_installer.check_status = Mock(
            side_effect=[
                InstallStatus.NOT_INSTALLED,  # Before install
                InstallStatus.INSTALLED,  # After install
            ]
        )
        mock_installer.install = AsyncMock(return_value=True)
        mock_installer.uninstall = Mock()

        mock_get_installer.return_value = mock_installer

        # Make request
        response = setup_client.post(
            "/api/v1/setup/models/birdnet/install/",
            json={"model_name": "birdnet", "force_reinstall": False},
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "installed" in data["message"].lower()

    @patch("echoroo.routes.setup.get_installer")
    def test_install_already_installed(self, mock_get_installer, setup_client):
        """Test installing already installed model."""
        from echoroo.ml.installer.base import InstallStatus

        # Setup mock installer
        mock_installer = Mock()
        mock_installer.check_status = Mock(return_value=InstallStatus.INSTALLED)

        mock_get_installer.return_value = mock_installer

        # Make request without force_reinstall
        response = setup_client.post(
            "/api/v1/setup/models/birdnet/install/",
            json={"model_name": "birdnet", "force_reinstall": False},
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "already installed" in data["message"]

    def test_install_invalid_model_name(self, setup_client):
        """Test installing with invalid model name."""
        response = setup_client.post(
            "/api/v1/setup/models/invalid_model/install/",
            json={"model_name": "invalid_model", "force_reinstall": False},
        )

        # Verify error response
        assert response.status_code == 400


class TestUninstallModel:
    """Test POST /api/v1/setup/models/{model}/uninstall/ endpoint."""

    @patch("echoroo.routes.setup.get_installer")
    def test_uninstall_success(self, mock_get_installer, setup_client):
        """Test uninstalling a model successfully."""
        from echoroo.ml.installer.base import InstallStatus

        # Setup mock installer
        mock_installer = Mock()
        mock_installer.check_status = Mock(
            side_effect=[
                InstallStatus.INSTALLED,  # Before uninstall
                InstallStatus.NOT_INSTALLED,  # After uninstall
            ]
        )
        mock_installer.uninstall = Mock()

        mock_get_installer.return_value = mock_installer

        # Make request
        response = setup_client.post("/api/v1/setup/models/birdnet/uninstall/")

        # Verify response
        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True

    def test_uninstall_invalid_model_name(self, setup_client):
        """Test uninstalling with invalid model name."""
        response = setup_client.post("/api/v1/setup/models/invalid_model/uninstall/")

        # Verify error response
        assert response.status_code == 400
