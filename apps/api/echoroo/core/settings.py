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

    # Trusted reverse-proxy CIDRs (Phase 17 A-3 Codex Major 1).
    #
    # Only ``X-Forwarded-For`` headers received from a socket peer that
    # falls inside one of these CIDRs are trusted. Untrusted peers have
    # their XFF ignored entirely so that an attacker who can reach the
    # API directly cannot spoof an allowlisted source IP by setting
    # ``X-Forwarded-For: 10.0.0.55``. An empty list (the default) means
    # XFF is NEVER trusted — the socket peer is always used as the
    # caller IP. Operators running behind a real reverse proxy (nginx,
    # ALB, Cloudflare) MUST set this to the proxy CIDRs.
    TRUSTED_PROXY_CIDRS: Annotated[list[str], NoDecode] = Field(
        default=[],
        validation_alias="ECHOROO_TRUSTED_PROXY_CIDRS",
        description=(
            "Comma-separated CIDR list of trusted reverse-proxy peers. "
            "X-Forwarded-For is only honoured when the socket peer matches "
            "one of these CIDRs."
        ),
    )

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
    web_session_cookie_name: str = "echoroo_session"
    web_refresh_cookie_name: str = "echoroo_refresh"
    web_csrf_cookie_name: str = "echoroo_csrf"
    # Non-sensitive marker cookie set on Path=/ so SvelteKit hooks.server.ts
    # can detect logged-in state for page-route auth guards. Carries no
    # sensitive content (literal value "1"); the real session/refresh/csrf
    # cookies remain scoped to /web-api/v1/* per spec FR-021.
    web_logged_in_cookie_name: str = "echoroo_logged_in"
    web_session_secret: str = Field(
        default="dev-web-session-secret-change-in-production",
        description="First-party web session HMAC/JWT secret",
    )
    web_access_token_ttl_seconds: int = 900
    web_refresh_token_ttl_seconds: int = 30 * 24 * 3600
    web_interim_token_ttl_seconds: int = 900
    webauthn_interim_token_ttl_seconds: int = 300
    web_app_base_url: str = "https://echoroo.app"

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
    # Phase 5 polish round 3 (重要1): make the S3 audio cache directory
    # configurable so tests (and CI runners that cannot write to /data) can
    # point this at a tmp_path. Production keeps the historical /data
    # default — overriding it through the environment is a no-op for the
    # running deployment.
    S3_AUDIO_CACHE_DIR: str = Field(
        default="/data/s3_audio_cache",
        description="Directory used by AudioService to cache files downloaded from S3",
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

    # Phase 17 backlog A-2 — PII hash CMK rotation (FR-091b dual-write).
    #
    # ``AWS_KMS_CMK_PII_HASH_ALIAS_V2`` is opt-in: when unset the system
    # runs in single-key mode against ``AWS_KMS_CMK_PII_HASH_ALIAS`` and
    # behaves identically to pre-rotation deployments. When set, every
    # new audit row + invitation row is hashed under BOTH v1 and v2;
    # historical rows remain searchable via the v1 fallback path in
    # :func:`echoroo.core.kms.verify_pii_hash`. Operators set this env
    # var at the moment they want rotation to begin and unset it (along
    # with re-pointing ``AWS_KMS_CMK_PII_HASH_ALIAS`` at the v2 CMK)
    # once the backfill has caught up. There is intentionally no
    # production-secret guard here: the variable is *operationally*
    # transient, not a baseline requirement.
    AWS_KMS_CMK_PII_HASH_ALIAS_V2: str | None = Field(
        default=None,
        description=(
            "Optional v2 PII hash CMK alias. Setting this enables dual-write "
            "rotation per FR-091b; leave unset for single-key deployments."
        ),
    )

    # Informational: the FR-091b rotation contract pegs the dual-write
    # window at 90 days. No code path consumes this setting today —
    # the daily backfill worker is unconditional, and the eventual
    # "rotation stale" dashboard signal will compute its threshold
    # from this knob (Phase 17 backlog A-2 Round 2 R1-M1). Keeping
    # the value here documents the operational contract in one place
    # and leaves the env var wired for the dashboard task that lands
    # in a follow-up.
    PII_HASH_ROTATION_GRACE_DAYS: int = Field(
        default=90,
        description=(
            "Informational. Documents the FR-091b 90-day rotation window. "
            "Reserved for the upcoming staleness-dashboard signal; not "
            "consumed by the runtime today."
        ),
    )

    @field_validator("webauthn_origins", mode="before")
    @classmethod
    def parse_webauthn_origins(cls, value: Any) -> Any:
        """Accept ECHOROO_WEBAUTHN_ORIGINS as a comma-separated list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("TRUSTED_PROXY_CIDRS", mode="before")
    @classmethod
    def parse_trusted_proxy_cidrs(cls, value: Any) -> Any:
        """Accept ECHOROO_TRUSTED_PROXY_CIDRS as a comma-separated list.

        Empty/whitespace-only entries are filtered out; the env var may
        therefore be set to ``""`` to mean "no trusted proxies" without
        producing a single empty-string CIDR.
        """
        if isinstance(value, str):
            return [cidr.strip() for cidr in value.split(",") if cidr.strip()]
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
            if (
                self.web_session_secret == "dev-web-session-secret-change-in-production"
                or len(self.web_session_secret) < 32
            ):
                raise ValueError(
                    "web_session_secret must be a strong secret (min 32 chars) in production/staging"
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
