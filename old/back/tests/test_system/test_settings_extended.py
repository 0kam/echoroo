"""Extended tests for the settings module."""

import json
import os
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from echoroo.system.settings import (
    DEFAULT_CORS_ORIGINS,
    Settings,
    get_default_cors_origins,
    get_settings,
    load_settings_from_file,
    migrate_settings,
    store_default_settings,
    write_settings_to_file,
)


class TestGetDefaultCorsOrigins:
    """Test the get_default_cors_origins function."""

    def test_includes_localhost_3000(self):
        """Test that localhost:3000 is included."""
        origins = get_default_cors_origins()
        assert "http://localhost:3000" in origins

    def test_includes_127_0_0_1_3000(self):
        """Test that 127.0.0.1:3000 is included."""
        origins = get_default_cors_origins()
        assert "http://127.0.0.1:3000" in origins

    def test_with_custom_domain(self):
        """Test CORS origins with custom domain."""
        with patch.dict(
            os.environ,
            {"ECHOROO_DOMAIN": "example.com", "ECHOROO_PROTOCOL": "http"},
        ):
            origins = get_default_cors_origins()
            assert "http://example.com:3000" in origins

    def test_with_https_protocol(self):
        """Test CORS origins with HTTPS protocol."""
        with patch.dict(
            os.environ,
            {"ECHOROO_DOMAIN": "example.com", "ECHOROO_PROTOCOL": "https"},
        ):
            origins = get_default_cors_origins()
            assert "https://example.com:3000" in origins

    def test_with_custom_frontend_port(self):
        """Test CORS origins with custom frontend port."""
        with patch.dict(
            os.environ,
            {"ECHOROO_FRONTEND_PORT": "3001"},
        ):
            origins = get_default_cors_origins()
            assert "http://localhost:3001" in origins

    def test_does_not_duplicate_localhost(self):
        """Test that localhost is not duplicated for different protocols."""
        origins = get_default_cors_origins()
        localhost_origins = [o for o in origins if "localhost" in o]
        assert len(localhost_origins) == len(set(localhost_origins))

    def test_sorted_output(self):
        """Test that origins are sorted."""
        origins = get_default_cors_origins()
        assert origins == sorted(origins)


class TestSettingsDefaults:
    """Test Settings class defaults."""

    def test_default_values(self):
        """Test that default settings have correct values."""
        settings = Settings()
        assert settings.dev is False
        assert settings.debug is False
        assert settings.db_dialect == "sqlite"
        assert settings.host == "localhost"
        assert settings.port == 5000
        assert settings.log_level == "info"
        assert settings.auth_cookie_secure is False
        assert settings.auth_cookie_samesite == "lax"

    def test_audio_dir_default(self):
        """Test that audio_dir defaults to home directory."""
        settings = Settings()
        assert settings.audio_dir == Path.home()

    def test_open_on_startup_default(self):
        """Test that open_on_startup defaults to True."""
        settings = Settings()
        assert settings.open_on_startup is True

    def test_cors_origins_auto_generated(self):
        """Test that CORS origins are auto-generated if not provided."""
        settings = Settings()
        assert settings.cors_origins is not None
        assert len(settings.cors_origins) > 0


class TestSettingsValidation:
    """Test Settings validation."""

    def test_settings_from_dict(self):
        """Test creating settings from dictionary."""
        data = {
            "dev": True,
            "host": "0.0.0.0",
            "port": 8000,
        }
        settings = Settings(**data)
        assert settings.dev is True
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000

    def test_settings_from_json(self):
        """Test creating settings from JSON string."""
        data = {
            "dev": False,
            "host": "example.com",
            "port": 5000,
        }
        json_str = json.dumps(data)
        settings = Settings.model_validate_json(json_str)
        assert settings.host == "example.com"

    def test_invalid_log_level_accepted(self):
        """Test that custom log levels are accepted."""
        settings = Settings(log_level="custom")
        assert settings.log_level == "custom"

    def test_cors_origins_validation(self):
        """Test CORS origins validation."""
        settings = Settings(cors_origins=["http://example.com", "https://test.com"])
        assert settings.cors_origins == ["http://example.com", "https://test.com"]


class TestSettingsEnvironmentVariables:
    """Test Settings loading from environment variables."""

    def test_env_prefix_echoroo(self):
        """Test that ECHOROO_ prefix is required."""
        with patch.dict(os.environ, {"ECHOROO_DEV": "true", "ECHOROO_PORT": "8000"}):
            settings = Settings()
            assert settings.dev is True
            assert settings.port == 8000

    def test_env_var_overrides_default(self):
        """Test that environment variables override defaults."""
        with patch.dict(os.environ, {"ECHOROO_HOST": "0.0.0.0"}):
            settings = Settings()
            assert settings.host == "0.0.0.0"

    def test_bool_conversion(self):
        """Test boolean conversion from environment."""
        with patch.dict(os.environ, {"ECHOROO_DEBUG": "true"}):
            settings = Settings()
            assert settings.debug is True

    def test_int_conversion(self):
        """Test integer conversion from environment."""
        with patch.dict(os.environ, {"ECHOROO_PORT": "9000"}):
            settings = Settings()
            assert settings.port == 9000


class TestStoreDefaultSettings:
    """Test the store_default_settings function."""

    def test_creates_settings_file(self, tmp_path: Path):
        """Test that settings file is created."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            with patch(
                "echoroo.system.settings.get_echoroo_db_file"
            ) as mock_db_file:
                mock_db_file.return_value = tmp_path / "echoroo.db"
                store_default_settings()

            assert settings_file.exists()

    def test_settings_file_is_valid_json(self, tmp_path: Path):
        """Test that settings file contains valid JSON."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            with patch(
                "echoroo.system.settings.get_echoroo_db_file"
            ) as mock_db_file:
                mock_db_file.return_value = tmp_path / "echoroo.db"
                store_default_settings()

            # Should be able to parse as JSON
            content = json.loads(settings_file.read_text())
            assert isinstance(content, dict)


class TestWriteSettingsToFile:
    """Test the write_settings_to_file function."""

    def test_writes_settings_to_file(self, tmp_path: Path):
        """Test that settings are written to file."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            settings = Settings(host="example.com", port=8000)
            write_settings_to_file(settings)

            assert settings_file.exists()

    def test_creates_parent_directory(self, tmp_path: Path):
        """Test that parent directory is created."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "subdir" / "settings.json"
            mock_file.return_value = settings_file

            settings = Settings()
            write_settings_to_file(settings)

            assert settings_file.parent.exists()
            assert settings_file.exists()

    def test_clears_cache(self, tmp_path: Path):
        """Test that get_settings cache is cleared."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            settings = Settings()
            # Call get_settings to populate cache
            with patch("echoroo.system.settings.load_settings_from_file") as mock_load:
                mock_load.return_value = settings
                get_settings()

            # Write settings should clear cache
            write_settings_to_file(settings)

            # Cache info should show 0 hits (cache was cleared)
            cache_info = get_settings.cache_info()
            assert cache_info.currsize == 0


class TestLoadSettingsFromFile:
    """Test the load_settings_from_file function."""

    def test_creates_file_if_not_exists(self, tmp_path: Path):
        """Test that file is created if it doesn't exist."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            with patch(
                "echoroo.system.settings.store_default_settings"
            ) as mock_store:
                mock_store.side_effect = lambda: settings_file.write_text(
                    Settings().model_dump_json()
                )

                settings = load_settings_from_file()
                assert isinstance(settings, Settings)

    def test_loads_from_existing_file(self, tmp_path: Path):
        """Test that settings are loaded from existing file."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            original_settings = Settings(host="example.com", port=8000)
            settings_file.write_text(original_settings.model_dump_json())

            settings = load_settings_from_file()
            assert settings.host == "example.com"
            assert settings.port == 8000

    def test_handles_invalid_json(self, tmp_path: Path):
        """Test that invalid JSON triggers default settings creation."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            # Write invalid JSON
            settings_file.write_text("{invalid json}")

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")

                with patch(
                    "echoroo.system.settings.store_default_settings"
                ) as mock_store:
                    mock_store.side_effect = lambda: settings_file.write_text(
                        Settings().model_dump_json()
                    )

                    settings = load_settings_from_file()
                    assert isinstance(settings, Settings)
                    assert len(w) > 0


class TestMigrateSettings:
    """Test the migrate_settings function."""

    def test_migrates_wildcard_cors(self, tmp_path: Path):
        """Test that wildcard CORS origins are migrated."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            settings = Settings(cors_origins=["*"])

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                migrated = migrate_settings(settings_file, settings)

                assert migrated.cors_origins != ["*"]
                assert migrated.cors_origins == list(DEFAULT_CORS_ORIGINS)
                assert len(w) > 0

    def test_migrates_samesite_none_secure(self, tmp_path: Path):
        """Test that SameSite=None/Secure=True is migrated."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            settings = Settings(
                auth_cookie_samesite="none",
                auth_cookie_secure=True,
            )

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                migrated = migrate_settings(settings_file, settings)

                assert migrated.auth_cookie_samesite == "lax"
                assert migrated.auth_cookie_secure is False
                assert len(w) > 0

    def test_no_migration_needed(self, tmp_path: Path):
        """Test that settings without issues pass through unchanged."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            settings = Settings(
                cors_origins=["http://localhost:3000"],
                auth_cookie_samesite="lax",
            )

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                migrated = migrate_settings(settings_file, settings)

                # No warnings should be issued
                assert len(w) == 0
                assert migrated.cors_origins == settings.cors_origins


class TestGetSettings:
    """Test the get_settings function."""

    def test_uses_lru_cache(self, tmp_path: Path):
        """Test that get_settings uses LRU cache."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            with patch(
                "echoroo.system.settings.load_settings_from_file"
            ) as mock_load:
                settings = Settings()
                mock_load.return_value = settings

                # Clear cache first
                get_settings.cache_clear()

                # First call should load from file
                result1 = get_settings()
                cache_info1 = get_settings.cache_info()

                # Second call should use cache
                result2 = get_settings()
                cache_info2 = get_settings.cache_info()

                assert result1 == result2
                assert cache_info2.hits > cache_info1.hits

    def test_returns_settings_object(self, tmp_path: Path):
        """Test that get_settings returns Settings object."""
        with patch("echoroo.system.settings.get_echoroo_settings_file") as mock_file:
            settings_file = tmp_path / "settings.json"
            mock_file.return_value = settings_file

            with patch(
                "echoroo.system.settings.load_settings_from_file"
            ) as mock_load:
                settings = Settings()
                mock_load.return_value = settings

                get_settings.cache_clear()
                result = get_settings()
                assert isinstance(result, Settings)
