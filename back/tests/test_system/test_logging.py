"""Tests for the logging module."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from echoroo.system.logging import (
    _get_handlers,
    generate_dev_logging_config,
    generate_logging_config,
    get_logging_config,
)
from echoroo.system.settings import Settings


class TestGenerateDevLoggingConfig:
    """Test the development logging configuration generation."""

    def test_returns_dict(self):
        """Test that dev config returns a dictionary."""
        config = generate_dev_logging_config()
        assert isinstance(config, dict)

    def test_has_required_keys(self):
        """Test that dev config has required keys."""
        config = generate_dev_logging_config()
        assert "version" in config
        assert "disable_existing_loggers" in config
        assert "formatters" in config
        assert "handlers" in config
        assert "loggers" in config

    def test_version_is_one(self):
        """Test that config version is 1."""
        config = generate_dev_logging_config()
        assert config["version"] == 1

    def test_has_echoroo_formatter(self):
        """Test that echoroo formatter is defined."""
        config = generate_dev_logging_config()
        assert "echoroo" in config["formatters"]

    def test_has_uvicorn_loggers(self):
        """Test that uvicorn loggers are configured."""
        config = generate_dev_logging_config()
        assert "uvicorn" in config["loggers"]
        assert "uvicorn.error" in config["loggers"]
        assert "uvicorn.access" in config["loggers"]

    def test_has_echoroo_logger(self):
        """Test that echoroo logger is configured."""
        config = generate_dev_logging_config()
        assert "echoroo" in config["loggers"]
        assert config["loggers"]["echoroo"]["level"] == "DEBUG"

    def test_has_default_handlers(self):
        """Test that default handlers are configured."""
        config = generate_dev_logging_config()
        assert "default" in config["handlers"]
        assert "console" in config["handlers"]
        assert "console.error" in config["handlers"]


class TestGenerateLoggingConfig:
    """Test the production logging configuration generation."""

    def test_returns_dict(self, test_settings: Settings):
        """Test that config returns a dictionary."""
        config = generate_logging_config(test_settings)
        assert isinstance(config, dict)

    def test_has_required_keys(self, test_settings: Settings):
        """Test that config has required keys."""
        config = generate_logging_config(test_settings)
        assert "version" in config
        assert "disable_existing_loggers" in config
        assert "formatters" in config
        assert "handlers" in config
        assert "loggers" in config

    def test_version_is_one(self, test_settings: Settings):
        """Test that config version is 1."""
        config = generate_logging_config(test_settings)
        assert config["version"] == 1

    def test_has_echoroo_formatter(self, test_settings: Settings):
        """Test that echoroo formatter is defined."""
        config = generate_logging_config(test_settings)
        assert "echoroo" in config["formatters"]

    def test_log_level_from_settings(self, test_settings: Settings):
        """Test that log level comes from settings."""
        test_settings.log_level = "debug"
        config = generate_logging_config(test_settings)
        assert config["loggers"]["echoroo"]["level"] == "DEBUG"

        test_settings.log_level = "info"
        config = generate_logging_config(test_settings)
        assert config["loggers"]["echoroo"]["level"] == "INFO"

        test_settings.log_level = "warning"
        config = generate_logging_config(test_settings)
        assert config["loggers"]["echoroo"]["level"] == "WARNING"

    def test_file_handlers_when_log_to_file(self, test_settings: Settings):
        """Test that file handlers are included when log_to_file is True."""
        test_settings.log_to_file = True
        test_settings.log_to_stdout = False
        config = generate_logging_config(test_settings)
        assert "default" in config["handlers"]
        assert "access" in config["handlers"]
        assert "error" in config["handlers"]

    def test_console_handlers_when_log_to_stdout(self, test_settings: Settings):
        """Test that console handlers are included when log_to_stdout is True."""
        test_settings.log_to_file = False
        test_settings.log_to_stdout = True
        config = generate_logging_config(test_settings)
        assert "console" in config["handlers"]
        assert "console.error" in config["handlers"]

    def test_no_handlers_when_both_disabled(self, test_settings: Settings):
        """Test that no handlers are included when both are disabled."""
        test_settings.log_to_file = False
        test_settings.log_to_stdout = False
        config = generate_logging_config(test_settings)
        assert len(config["handlers"]) == 0

    def test_both_handlers_when_both_enabled(self, test_settings: Settings):
        """Test that both handlers are included when both are enabled."""
        test_settings.log_to_file = True
        test_settings.log_to_stdout = True
        config = generate_logging_config(test_settings)
        assert "default" in config["handlers"]
        assert "console" in config["handlers"]

    def test_creates_log_directory(self, test_settings: Settings, tmp_path: Path):
        """Test that log directory is created."""
        log_dir = tmp_path / "test_logs"
        test_settings.log_dir = log_dir
        test_settings.log_to_file = True

        config = generate_logging_config(test_settings)

        # Directory should be created
        assert log_dir.exists()

    def test_creates_log_files(self, test_settings: Settings, tmp_path: Path):
        """Test that log files are created."""
        log_dir = tmp_path / "test_logs"
        test_settings.log_dir = log_dir
        test_settings.log_to_file = True

        generate_logging_config(test_settings)

        assert (log_dir / "echoroo.log").exists()
        assert (log_dir / "access.log").exists()
        assert (log_dir / "error.log").exists()

    def test_log_files_not_created_when_disabled(
        self, test_settings: Settings, tmp_path: Path
    ):
        """Test that log files are not created when log_to_file is False."""
        log_dir = tmp_path / "test_logs"
        test_settings.log_dir = log_dir
        test_settings.log_to_file = False

        generate_logging_config(test_settings)

        # Log files should not be created
        assert not log_dir.exists()


class TestGetHandlers:
    """Test the _get_handlers helper function."""

    def test_both_enabled(self, test_settings: Settings):
        """Test handlers when both file and stdout are enabled."""
        test_settings.log_to_file = True
        test_settings.log_to_stdout = True
        handlers = _get_handlers("file_handler", "console_handler", test_settings)
        assert handlers == ["file_handler", "console_handler"]

    def test_only_file(self, test_settings: Settings):
        """Test handlers when only file is enabled."""
        test_settings.log_to_file = True
        test_settings.log_to_stdout = False
        handlers = _get_handlers("file_handler", "console_handler", test_settings)
        assert handlers == ["file_handler"]

    def test_only_stdout(self, test_settings: Settings):
        """Test handlers when only stdout is enabled."""
        test_settings.log_to_file = False
        test_settings.log_to_stdout = True
        handlers = _get_handlers("file_handler", "console_handler", test_settings)
        assert handlers == ["console_handler"]

    def test_both_disabled(self, test_settings: Settings):
        """Test handlers when both are disabled."""
        test_settings.log_to_file = False
        test_settings.log_to_stdout = False
        handlers = _get_handlers("file_handler", "console_handler", test_settings)
        assert handlers == []


class TestGetLoggingConfig:
    """Test the get_logging_config function."""

    def test_dev_mode_returns_dev_config(self, test_settings: Settings):
        """Test that dev mode returns dev config."""
        test_settings.dev = True
        config = get_logging_config(test_settings)
        assert config["loggers"]["echoroo"]["level"] == "DEBUG"

    def test_creates_config_file_if_not_exists(
        self, test_settings: Settings, tmp_path: Path
    ):
        """Test that config file is created if it doesn't exist."""
        test_settings.dev = False

        with patch("echoroo.system.logging.get_app_data_dir") as mock_data_dir:
            mock_data_dir.return_value = tmp_path
            config_file = tmp_path / test_settings.log_config

            assert not config_file.exists()
            config = get_logging_config(test_settings)
            assert config_file.exists()

            # Verify the file contains valid JSON
            saved_config = json.loads(config_file.read_text())
            assert saved_config == config

    def test_reads_existing_config_file(
        self, test_settings: Settings, tmp_path: Path
    ):
        """Test that existing config file is read."""
        test_settings.dev = False

        with patch("echoroo.system.logging.get_app_data_dir") as mock_data_dir:
            mock_data_dir.return_value = tmp_path
            config_file = tmp_path / test_settings.log_config

            # Create a config file
            original_config = generate_logging_config(test_settings)
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(json.dumps(original_config))

            # Get config should return the saved config
            config = get_logging_config(test_settings)
            assert config == original_config

    def test_config_file_is_json(self, test_settings: Settings, tmp_path: Path):
        """Test that the config file is valid JSON."""
        test_settings.dev = False

        with patch("echoroo.system.logging.get_app_data_dir") as mock_data_dir:
            mock_data_dir.return_value = tmp_path
            config_file = tmp_path / test_settings.log_config

            get_logging_config(test_settings)

            # Should be able to parse as JSON
            content = config_file.read_text()
            config = json.loads(content)
            assert isinstance(config, dict)
