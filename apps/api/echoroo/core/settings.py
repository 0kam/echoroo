"""Application settings and configuration management."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance loaded from environment variables
    """
    return Settings()
