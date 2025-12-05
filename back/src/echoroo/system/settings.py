"""Settings for echoroo.

We are using pydantic to define our settings.
"""

import os
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Literal, Tuple, Type

from pydantic import Field, ValidationError, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from echoroo.system.data import (
    get_app_data_dir,
    get_echoroo_db_file,
    get_echoroo_settings_file,
)

__all__ = [
    "get_settings",
    "Settings",
]


def get_default_cors_origins() -> list[str]:
    """Generate default CORS origins based on environment configuration.

    This function creates CORS origins for:
    - localhost (always included for local development)
    - The configured domain (if different from localhost)
    - Common frontend ports (3000, 3001)
    """
    # Get configuration from environment
    domain = os.getenv("ECHOROO_DOMAIN", "localhost")
    protocol = os.getenv("ECHOROO_PROTOCOL", "http")
    frontend_port = os.getenv("ECHOROO_FRONTEND_PORT", "3000")

    origins = set()

    # Always include localhost for development
    origins.add(f"http://localhost:{frontend_port}")
    origins.add(f"http://127.0.0.1:{frontend_port}")

    # Include the configured domain if it's not localhost
    if domain not in ("localhost", "127.0.0.1"):
        origins.add(f"{protocol}://{domain}:{frontend_port}")
        # Also add common variations
        origins.add(f"http://{domain}:{frontend_port}")
        if protocol == "https":
            origins.add(f"https://{domain}:{frontend_port}")

    return sorted(list(origins))


DEFAULT_CORS_ORIGINS: Tuple[str, ...] = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


class Settings(BaseSettings):
    """Settings for echoroo."""

    model_config = SettingsConfigDict(
        env_prefix="ECHOROO_",
    )

    dev: bool = False
    """True if the application is running in development mode.

    When running in development mode, the application will log to stdout
    use a SQLite database in the project root and reload the application
    when changes are made to the source code.
    """

    debug: bool = False
    """True if application is running in debug mode.

    In debug mode logging will be printed to the console instead of the
    log files.
    """

    db_dialect: str = "sqlite"
    """Database dialect."""

    db_username: str | None = None

    db_password: str | None = None

    db_host: str | None = None

    db_port: int | None = None

    db_name: str = "echoroo.db"
    """Name of the database where all data is stored.

    In case of SQLite, this is the path to the database file relative
    to the project root.
    """

    db_url: str | None = None
    """Database URL.

    If this is set, it will override all other database settings.
    Only use this if you know what you are doing.
    """

    audio_dir: Path = Path.home()
    """Directory where the all audio files are stored.

    It is assumed that all audio files are stored within this directory.
    They can be stored in subdirectories in any structure, however any
    files outside of this directory will not be accessible.

    This is a security measure to prevent users from accessing files
    outside of the audio directory.
    """

    host: str = "localhost"
    """Host on which the backend is running."""

    port: int = 5000
    """Port on which the backend is running."""

    domain: str = "localhost"
    """Domain on which the backend is running."""

    log_config: Path = Path("logging.conf")
    """Path to the logging configuration file relative to the project root."""

    log_to_file: bool = True
    """Log to a file."""

    log_to_stdout: bool = False
    """Log to stdout."""

    log_dir: Path = Path("logs")
    """Path to the directory where log files are stored relative to the project root."""

    log_level: str = "info"
    """Log level for the application.

    Should be set to INFO in production.
    """

    cors_origins: list[str] | None = None
    """Allowed origins for CORS.

    If not specified, will be automatically generated based on domain and frontend port.
    """

    open_on_startup: bool = True
    """Open the application in the browser on startup."""

    auth_cookie_secure: bool = False
    """Whether the auth cookie requires HTTPS."""

    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    """SameSite attribute for the auth cookie."""

    metadata_dir: Path = Field(
        default_factory=lambda: get_app_data_dir() / "metadata",
    )
    """Root directory where metadata assets (e.g., site images) are stored."""

    @model_validator(mode="after")
    def set_default_cors_origins(self) -> "Settings":
        """Set default CORS origins if not explicitly configured."""
        if self.cors_origins is None:
            self.cors_origins = get_default_cors_origins()
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            env_settings,
            dotenv_settings,
            file_secret_settings,
            init_settings,
        )


@lru_cache()
def get_settings() -> Settings:
    """Get the application settings."""
    return load_settings_from_file()


def load_settings_from_file() -> Settings:
    """Load the application settings from a file."""
    settings_file = get_echoroo_settings_file()

    if not settings_file.exists():
        store_default_settings()

    try:
        settings = Settings.model_validate_json(settings_file.read_text())
    except ValidationError:
        # NOTE: This should only happen if the user has manually edited
        # the settings file and made a mistake, or if the settings schema
        # has changed. In both cases, we want to store the default settings
        # to the file.
        warnings.warn(
            f"Settings file {settings_file} is invalid. "
            "Storing default settings to file.",
            stacklevel=2,
        )
        store_default_settings()
        settings = Settings.model_validate_json(settings_file.read_text())

    return migrate_settings(settings_file, settings)


def store_default_settings() -> None:
    """Store the default settings to a file."""
    default_settings = Settings(db_name=str(get_echoroo_db_file()))
    write_settings_to_file(default_settings)


def write_settings_to_file(settings: Settings) -> None:
    """Write the application settings to a file."""
    settings_file = get_echoroo_settings_file()

    if not settings_file.parent.exists():
        settings_file.parent.mkdir(parents=True)

    settings_file.write_text(settings.model_dump_json())
    get_settings.cache_clear()


def migrate_settings(settings_file: Path, settings: Settings) -> Settings:
    """Update settings that use legacy defaults incompatible with the current app."""

    if settings.cors_origins == ["*"]:
        warnings.warn(
            "Detected legacy '*' CORS origin configuration. "
            "Updating to a localhost allowlist to enable credentialed requests.",
            stacklevel=2,
        )
        settings = settings.model_copy(
            update={"cors_origins": list(DEFAULT_CORS_ORIGINS)}
        )
        settings_file.write_text(settings.model_dump_json())

    # Revert SameSite=None/Secure=True if detected, as it breaks HTTP
    if settings.auth_cookie_samesite == "none" and settings.auth_cookie_secure:
        warnings.warn(
            "Detected SameSite=None and Secure=True configuration. "
            "Reverting to SameSite=Lax and Secure=False to support HTTP environments.",
            stacklevel=2,
        )
        settings = settings.model_copy(
            update={"auth_cookie_samesite": "lax", "auth_cookie_secure": False}
        )
        settings_file.write_text(settings.model_dump_json())

    return settings
