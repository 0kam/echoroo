"""Tests for the data module."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from echoroo.system.data import (
    _get_linux_app_data_dir,
    _get_macos_app_data_dir,
    _get_windows_app_data_dir,
    get_app_data_dir,
    get_echoroo_db_file,
    get_echoroo_settings_file,
)


class TestPlatformDataDirs:
    """Test platform-specific data directory functions."""

    def test_windows_app_data_dir(self):
        """Test Windows app data directory path."""
        with patch("pathlib.Path.home") as mock_home:
            mock_home.return_value = Path("C:/Users/TestUser")
            result = _get_windows_app_data_dir()
            assert result == Path("C:/Users/TestUser/AppData/Local/echoroo")

    def test_linux_app_data_dir(self):
        """Test Linux app data directory path."""
        with patch("pathlib.Path.home") as mock_home:
            mock_home.return_value = Path("/home/testuser")
            result = _get_linux_app_data_dir()
            assert result == Path("/home/testuser/.local/share/echoroo")

    def test_macos_app_data_dir(self):
        """Test macOS app data directory path."""
        with patch("pathlib.Path.home") as mock_home:
            mock_home.return_value = Path("/Users/testuser")
            result = _get_macos_app_data_dir()
            assert result == Path("/Users/testuser/Library/Application Support/echoroo")


class TestGetAppDataDir:
    """Test get_app_data_dir function."""

    def test_uses_env_var_if_set(self, tmp_path: Path):
        """Test that ECHOROO_DATA_DIR environment variable is used."""
        custom_dir = tmp_path / "custom_data"
        with patch.dict(os.environ, {"ECHOROO_DATA_DIR": str(custom_dir)}):
            result = get_app_data_dir()
            assert result == custom_dir
            assert custom_dir.exists()

    def test_creates_env_var_directory(self, tmp_path: Path):
        """Test that directory from env var is created if it doesn't exist."""
        custom_dir = tmp_path / "new_data_dir"
        assert not custom_dir.exists()

        with patch.dict(os.environ, {"ECHOROO_DATA_DIR": str(custom_dir)}):
            result = get_app_data_dir()
            assert custom_dir.exists()

    def test_windows_platform(self, tmp_path: Path):
        """Test Windows platform detection."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "win32"):
                with patch("pathlib.Path.home") as mock_home:
                    mock_home.return_value = Path("C:/Users/TestUser")
                    result = get_app_data_dir()
                    assert "AppData" in str(result)
                    assert "echoroo" in str(result)

    def test_linux_platform(self, tmp_path: Path):
        """Test Linux platform detection."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "linux"):
                with patch("pathlib.Path.home") as mock_home:
                    # Use a valid home path that can be created
                    mock_home.return_value = tmp_path / "home" / "testuser"
                    result = get_app_data_dir()
                    assert ".local" in str(result)
                    assert "share" in str(result)

    def test_macos_platform(self, tmp_path: Path):
        """Test macOS platform detection."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "darwin"):
                with patch("pathlib.Path.home") as mock_home:
                    # Use a valid home path that can be created
                    mock_home.return_value = tmp_path / "Users" / "testuser"
                    result = get_app_data_dir()
                    assert "Library" in str(result)
                    assert "Application Support" in str(result)

    def test_unsupported_platform_raises_error(self, tmp_path: Path):
        """Test that unsupported platform raises RuntimeError."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "unsupported_os"):
                with pytest.raises(RuntimeError, match="Unsupported platform"):
                    get_app_data_dir()

    def test_creates_directory(self, tmp_path: Path):
        """Test that directory is created if it doesn't exist."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "linux"):
                with patch("pathlib.Path.home") as mock_home:
                    # Use a path that doesn't exist
                    home_path = tmp_path / "home" / "user"
                    mock_home.return_value = home_path

                    # The directory should be created
                    result = get_app_data_dir()
                    assert result.exists()
                    assert "echoroo" in str(result)

    def test_creates_nested_directories(self, tmp_path: Path):
        """Test that nested directories are created."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("sys.platform", "linux"):
                with patch("pathlib.Path.home") as mock_home:
                    home_path = tmp_path / "nested" / "home" / "user"
                    mock_home.return_value = home_path
                    result = get_app_data_dir()
                    assert result.exists()


class TestGetEchorooSettingsFile:
    """Test get_echoroo_settings_file function."""

    def test_returns_path(self):
        """Test that function returns a Path object."""
        result = get_echoroo_settings_file()
        assert isinstance(result, Path)

    def test_returns_json_file(self):
        """Test that the returned path is a JSON file."""
        result = get_echoroo_settings_file()
        assert result.name == "settings.json"

    def test_in_app_data_dir(self):
        """Test that settings file is in app data directory."""
        with patch("echoroo.system.data.get_app_data_dir") as mock_get_dir:
            mock_get_dir.return_value = Path("/home/user/.local/share/echoroo")
            result = get_echoroo_settings_file()
            assert result.parent == Path("/home/user/.local/share/echoroo")

    def test_consistent_path(self):
        """Test that function returns consistent path."""
        result1 = get_echoroo_settings_file()
        result2 = get_echoroo_settings_file()
        assert result1 == result2


class TestGetEchorooDbFile:
    """Test get_echoroo_db_file function."""

    def test_returns_path(self):
        """Test that function returns a Path object."""
        result = get_echoroo_db_file()
        assert isinstance(result, Path)

    def test_returns_db_file(self):
        """Test that the returned path is a database file."""
        result = get_echoroo_db_file()
        assert result.name == "echoroo.db"

    def test_in_app_data_dir(self):
        """Test that database file is in app data directory."""
        with patch("echoroo.system.data.get_app_data_dir") as mock_get_dir:
            mock_get_dir.return_value = Path("/home/user/.local/share/echoroo")
            result = get_echoroo_db_file()
            assert result.parent == Path("/home/user/.local/share/echoroo")

    def test_consistent_path(self):
        """Test that function returns consistent path."""
        result1 = get_echoroo_db_file()
        result2 = get_echoroo_db_file()
        assert result1 == result2
