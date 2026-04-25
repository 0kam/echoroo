"""Application settings and configuration management."""

from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Echoroo API"
    APP_VERSION: str = "2.0.0"
    APP_URL: str = "http://localhost:5173"
    DEBUG: bool = False
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo",
        description="PostgreSQL connection string with asyncpg driver",
    )

    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string for rate limiting and caching",
    )

    # JWT
    JWT_SECRET_KEY: str = Field(
        default="your-secret-key-change-in-production",
        description="Secret key for JWT token signing",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # Security
    ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="CORS allowed origins",
    )
    webauthn_rp_id: str = Field(
        default="localhost",
        validation_alias="ECHOROO_WEBAUTHN_RP_ID",
        description="WebAuthn relying party ID",
    )
    webauthn_rp_name: str = Field(
        default="Echoroo",
        validation_alias="ECHOROO_WEBAUTHN_RP_NAME",
        description="WebAuthn relying party display name",
    )
    webauthn_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000"],
        validation_alias="ECHOROO_WEBAUTHN_ORIGINS",
        description="Allowed WebAuthn browser origins",
    )
    webauthn_challenge_ttl_seconds: int = Field(
        default=300,
        validation_alias="ECHOROO_WEBAUTHN_CHALLENGE_TTL_SECONDS",
        description="WebAuthn Redis challenge TTL in seconds",
    )

    # Password Hashing (Argon2id OWASP configuration)
    ARGON2_MEMORY_COST: int = 19456  # 19 MiB
    ARGON2_TIME_COST: int = 2
    ARGON2_PARALLELISM: int = 1

    # Rate Limiting
    RATE_LIMIT_LOGIN_ATTEMPTS: int = 5
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 60
    RATE_LIMIT_REGISTER_ATTEMPTS: int = 3
    RATE_LIMIT_REGISTER_WINDOW_SECONDS: int = 3600
    RATE_LIMIT_PASSWORD_RESET_ATTEMPTS: int = 3
    RATE_LIMIT_PASSWORD_RESET_WINDOW_SECONDS: int = 3600
    RATE_LIMIT_UPLOAD_SESSION_CREATE_ATTEMPTS: int = 10
    RATE_LIMIT_UPLOAD_SESSION_CREATE_WINDOW_SECONDS: int = 3600
    RATE_LIMIT_UPLOAD_SESSION_COMPLETE_ATTEMPTS: int = 20
    RATE_LIMIT_UPLOAD_SESSION_COMPLETE_WINDOW_SECONDS: int = 3600

    # Email (Resend)
    RESEND_API_KEY: str = Field(
        default="",
        description="Resend API key for transactional emails",
    )
    EMAIL_FROM: str = "noreply@echoroo.app"

    # CAPTCHA (Cloudflare Turnstile)
    TURNSTILE_SECRET_KEY: str = Field(
        default="",
        description="Cloudflare Turnstile secret key",
    )
    TURNSTILE_SITE_KEY: str = Field(
        default="",
        description="Cloudflare Turnstile site key (public)",
    )

    # Session
    SESSION_TIMEOUT_MINUTES: int = 120  # 2 hours

    # API Tokens
    API_TOKEN_PREFIX: str = "ecr_"
    API_TOKEN_LENGTH: int = 32

    # Audio Files
    AUDIO_ROOT: str = Field(
        default="/data/audio",
        description="Root directory for audio files",
    )
    AUDIO_CACHE_DIR: str | None = Field(
        default=None,
        description="Directory for caching spectrograms (optional)",
    )

    # S3 / Object Storage
    S3_ENDPOINT_URL: str = "http://localhost:9000"
    S3_PUBLIC_ENDPOINT_URL: str | None = None  # Public URL for presigned URLs (browser access)
    S3_ACCESS_KEY: str = "echoroo"
    S3_SECRET_KEY: str = "echoroo-dev"
    S3_BUCKET: str = "echoroo"
    S3_REGION: str = "us-east-1"
    S3_PRESIGNED_URL_EXPIRY: int = 900  # 15 minutes

    # Upload limits
    UPLOAD_MAX_FILE_SIZE: int = 1 * 1024 * 1024 * 1024  # 1GB per file
    UPLOAD_MAX_SESSION_FILES: int = 500  # max files per upload session
    UPLOAD_SESSION_TTL: int = 3600  # 1 hour TTL for ISSUED sessions
    UPLOAD_ALLOWED_EXTENSIONS: list[str] = [".wav", ".flac", ".mp3", ".ogg", ".opus"]

    # Project storage quota
    DEFAULT_STORAGE_QUOTA: int = 100 * 1024 * 1024 * 1024  # 100GB default

    # Janitor (orphan S3 cleanup)
    JANITOR_DRY_RUN: bool = True  # default True; flip to False after prod monitoring
    JANITOR_AGE_HOURS: int = 24  # orphan age threshold (hours)

    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    @field_validator("webauthn_origins", mode="before")
    @classmethod
    def parse_webauthn_origins(cls, value: Any) -> Any:
        """Accept ECHOROO_WEBAUTHN_ORIGINS as a comma-separated list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """Ensure sensitive secrets are not left at insecure default values in production/staging."""
        if self.ENVIRONMENT in ("production", "staging"):
            weak_defaults = [
                "your-secret-key-change-in-production",
                "dev-secret-key-change-in-production",
            ]
            if self.JWT_SECRET_KEY in weak_defaults or len(self.JWT_SECRET_KEY) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be a strong secret (min 32 chars) in production/staging"
                )
            if self.S3_SECRET_KEY == "echoroo-dev":
                raise ValueError(
                    "S3_SECRET_KEY must be set to a secure value in production/staging"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance loaded from environment variables
    """
    return Settings()
