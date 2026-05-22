"""Application settings and configuration management."""

import re
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


# spec/011 NFR-011-010 — invitation token kid character class. The wire
# envelope ``{token}.{exp}.{kid}.{mac}`` is decoded via ``rsplit('.', 3)``
# so kids MUST NOT contain ``.``; we additionally restrict to URL-safe
# characters to keep operator pasting safe.
_INVITATION_TOKEN_KID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")


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
    # Test-mode 2FA shared-secret bypass for local/internal preview automation.
    # This MUST remain disabled in production.
    TEST_MODE: bool = Field(
        default=False,
        description=(
            "Enable test-only helpers, including the 2FA shared-secret "
            "bypass. MUST be false in production."
        ),
    )
    TEST_TOTP_SECRET_BASE32: str | None = Field(
        default=None,
        description=(
            "Base32 shared TOTP secret accepted only when TEST_MODE is enabled "
            "and a user's enrolled TOTP secret does not match."
        ),
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

    # Trusted devices (spec/010).
    # spec/011 §FR-011-006 / Step 10 (carry-over #4) — the
    # ``EMAIL_VERIFICATION_ENFORCEMENT_ENABLED`` (Step 3),
    # ``EMAIL_VERIFICATION_TOKEN_TTL_SECONDS``, and
    # ``EMAIL_VERIFICATION_RESEND_ACTIVE_TOKEN_CAP`` settings were
    # removed alongside the deleted email-verification subsystem.
    # ``ForcedPasswordChangeMiddleware`` (registered in ``main.py``)
    # is the replacement gate.
    TRUSTED_DEVICE_REGISTRATION_ENABLED: bool = False
    TRUSTED_DEVICE_BYPASS_ENABLED: bool = False
    TRUSTED_DEVICE_COOKIE_NAME: str = "echoroo_trusted_device"
    TRUSTED_DEVICE_COOKIE_TTL_SECONDS: int = 30 * 24 * 3600

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
    # CSRF token / cookie lifetime. Default 0 means "inherit
    # ``web_refresh_token_ttl_seconds``" (see ``_inherit_csrf_ttl_default``
    # below) so the double-submit cookie stays valid for as long as the
    # session itself. If these drift apart, the cookie or the middleware
    # TTL expires before the session does and unsafe requests start
    # failing 403 csrf_failed even though the session is alive (the
    # previous configuration pinned the cookie to the 15min access TTL
    # and the middleware to a hard-coded 24h default, neither matched
    # the 30d session window). Override (env: WEB_CSRF_TTL_SECONDS) only
    # if you need a strictly shorter CSRF rotation than refresh; the
    # token already rotates on every login / refresh, so the worst-case
    # reuse window in practice is one refresh cycle.
    web_csrf_ttl_seconds: int = 0
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

    # Phase 17 backlog A-4 — API key age-based scope degradation
    # (FR-083). Both knobs are consumed by:
    #   * :mod:`echoroo.workers.api_key_age_check` (daily sweep at
    #     01:15 UTC).
    #   * :class:`echoroo.services.api_key_verification.DbApiKeyVerifier`
    #     (lazy safety-net re-evaluation per request).
    # Keeping them as settings (not hard-coded constants) lets ops dial
    # the curve down for staging / load-test deployments without code
    # changes; production never overrides the spec defaults.
    API_KEY_SCOPE_DEGRADE_DAYS: int = Field(
        default=180,
        description=(
            "Age in days at which an API key's write scopes are stripped "
            "(FR-083). Read scopes survive until ``API_KEY_REVOKE_DAYS``."
        ),
    )
    API_KEY_REVOKE_DAYS: int = Field(
        default=270,
        description=(
            "Age in days at which an API key is fully revoked (FR-083). "
            "Defaults to 180 + 90 grace per the spec."
        ),
    )

    # Phase 17 backlog A-12 — dedicated HMAC for 2FA reset confirmation tokens.
    #
    # Decoupled from ``web_session_secret`` so a leak / compromise of the
    # generic session signing key does NOT also forge admin-reset
    # confirmation tokens (FR-091b / OWASP A02 Cryptographic Failures).
    # Tokens are signed with a ``kid`` claim ("v1" today) so future
    # rotation can ship a "v2" key alongside the previous one for a brief
    # grace window. See
    # ``docs/runbook/two_factor_confirmation_key_rotation.md`` for the
    # operational procedure.
    two_factor_reset_confirmation_hmac_key: str = Field(
        default="dev-two-factor-confirmation-hmac-change-in-production",
        validation_alias="TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY",
        description=(
            "HMAC-SHA256 signing key for two-factor reset confirmation tokens "
            "(FR-091b / OWASP A02). Decoupled from web_session_secret so a "
            "compromise of session signing does NOT also forge admin reset "
            "tokens. Required >= 32 chars in production / staging."
        ),
    )
    two_factor_reset_confirmation_hmac_key_old: str | None = Field(
        default=None,
        validation_alias="TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD",
        description=(
            "Optional previous HMAC key during the post-rotation grace "
            "window (default 24h, bounded by the 5 min token TTL). "
            "Operators set this when rotating the new key, then unset "
            "it after all in-flight tokens have expired. See "
            "docs/runbook/two_factor_confirmation_key_rotation.md."
        ),
    )
    # Phase 17 A-12 Round 2: kid identifiers are env-driven so a rotation
    # only needs env var changes — no source-code bump. The verifier
    # resolves the wire ``k`` claim against these two values:
    #
    #   * ``..._KID_NEW`` → maps to ``..._HMAC_KEY`` (always required)
    #   * ``..._KID_OLD`` → maps to ``..._HMAC_KEY_OLD`` (only valid when
    #     BOTH the kid AND the key are set; closing the grace window
    #     means unsetting both)
    #
    # See docs/runbook/two_factor_confirmation_key_rotation.md for the
    # operational rotation procedure (env-only, no source change).
    two_factor_reset_confirmation_hmac_kid_new: str = Field(
        default="v1",
        validation_alias="TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW",
        description=(
            "Kid string embedded in newly issued 2FA confirmation tokens. "
            "Bump on rotation (v1 -> v2 -> ...). The _OLD pair must use "
            "the prior _NEW value during the grace window."
        ),
    )
    two_factor_reset_confirmation_hmac_kid_old: str | None = Field(
        default=None,
        validation_alias="TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD",
        description=(
            "Kid string accepted from previously issued tokens during the "
            "rotation grace window. None when no rotation is in progress. "
            "MUST be paired with TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD."
        ),
    )

    # Phase 17 backlog A-8 — TOTP DEK CMK rotation (FR-091b).
    #
    # ``two_factor_dek_cmk_alias_new`` and ``two_factor_dek_kid_new`` are the
    # currently active CMK alias / DEK version stamped onto every newly
    # encrypted TOTP secret. ``..._alias_old`` and ``..._kid_old`` are
    # populated ONLY during a rotation grace window so that records still
    # carrying the previous DEK version can be decrypted (and rewrapped via
    # ``scripts/rewrap_dek.py``) before the old CMK is retired.
    #
    # Routing contract (see ``_resolve_dek_alias_for_version`` in
    # :mod:`echoroo.services.two_factor_service`):
    #   * ``users.two_factor_secret_dek_version == kid_new`` → alias_new
    #   * ``users.two_factor_secret_dek_version == kid_old`` (when set) → alias_old
    #   * otherwise → reject with ``TwoFactorError`` (operator must run
    #     ``scripts/rewrap_dek.py`` before deploying a configuration that
    #     drops the old version).
    #
    # See ``docs/runbook/dek_rewrap.md`` for the operational rotation
    # procedure (env-driven, no source code change required).
    two_factor_dek_cmk_alias_new: str = Field(
        default="alias/echoroo-totp-dek",
        validation_alias="AWS_KMS_CMK_2FA_DEK_ALIAS_NEW",
        description=(
            "Current CMK alias used to wrap newly encrypted TOTP DEKs. "
            "Maps to ``two_factor_dek_kid_new``. Bump this (and rotate "
            "``..._kid_new``) when starting a CMK rotation."
        ),
    )
    two_factor_dek_cmk_alias_old: str | None = Field(
        default=None,
        validation_alias="AWS_KMS_CMK_2FA_DEK_ALIAS_OLD",
        description=(
            "Previous CMK alias accepted for decrypting historical TOTP "
            "DEKs during the rotation grace window. MUST be paired with "
            "``two_factor_dek_kid_old``; both unset means no rotation in "
            "progress. See docs/runbook/dek_rewrap.md."
        ),
    )
    two_factor_dek_kid_new: int = Field(
        default=1,
        validation_alias="AWS_KMS_CMK_2FA_DEK_KID_NEW",
        description=(
            "DEK version stamped on newly encrypted TOTP secrets. Bump on "
            "rotation (1 → 2 → ...). Maps to ``two_factor_dek_cmk_alias_new``."
        ),
    )
    two_factor_dek_kid_old: int | None = Field(
        default=None,
        validation_alias="AWS_KMS_CMK_2FA_DEK_KID_OLD",
        description=(
            "Previous DEK version accepted from records still wrapped by "
            "``two_factor_dek_cmk_alias_old``. None when no rotation is in "
            "progress. MUST be paired with ``two_factor_dek_cmk_alias_old``."
        ),
    )

    # spec/011 NFR-011-010 — invitation token signing key + kid rotation.
    #
    # Mirrors the Phase 17 A-12 ``_NEW`` / ``_OLD`` env-driven rotation
    # pattern (see ``two_factor_reset_confirmation_hmac_*`` above) so a
    # rotation only needs env var changes — no source code bump.
    #
    # Wire envelope: the new invitation token format is
    # ``{token}.{exp}.{kid}.{mac}`` (4-part). Verification accepts:
    #
    #   * a 4-part envelope whose ``kid`` matches
    #     ``INVITATION_TOKEN_KID_NEW`` (preferred) or
    #     ``INVITATION_TOKEN_KID_OLD`` (during the grace window); or
    #   * a 3-part legacy envelope whose MAC verifies under
    #     ``INVITATION_TOKEN_HMAC_KEY_OLD`` (initial deploy / grace only).
    #
    # The two ``_OLD`` slots MUST be set together or both unset (see the
    # model validator below). Operators close a rotation by unsetting
    # both ``_OLD`` env vars once the grace window has elapsed.
    invitation_token_kid_new: str = Field(
        default="",
        validation_alias="INVITATION_TOKEN_KID_NEW",
        description=(
            "Active kid stamped on newly issued invitation tokens "
            "(NFR-011-010). Required at every boot in EVERY environment "
            "(dev / staging / production) — an empty value trips the "
            "model_validator non-empty guard regardless of ENVIRONMENT. "
            "The 32-char minimum strength bar on the companion "
            "INVITATION_TOKEN_HMAC_KEY is the only env-conditional check "
            "(prod / staging only)."
        ),
    )
    invitation_token_kid_old: str | None = Field(
        default=None,
        validation_alias="INVITATION_TOKEN_KID_OLD",
        description=(
            "Previous kid accepted during the rotation grace window. "
            "Required at the initial spec/011 deploy so 3-part legacy "
            "tokens in flight remain verifiable; optional after the "
            "grace window expires. MUST be paired with "
            "``INVITATION_TOKEN_HMAC_KEY_OLD``."
        ),
    )
    invitation_token_kid_grace_hours: int = Field(
        default=24,
        validation_alias="INVITATION_TOKEN_KID_GRACE_HOURS",
        description=(
            "Hours past the invitation TTL during which ``_OLD`` kid "
            "tokens (and 3-part legacy envelopes) remain verifiable. "
            "Default 24 (NFR-011-010)."
        ),
    )
    invitation_token_hmac_key: str = Field(
        default="",
        validation_alias="INVITATION_TOKEN_HMAC_KEY",
        description=(
            "HMAC-SHA256 signing key for the NEW invitation token kid "
            "(NFR-011-010). Required (non-empty) at every boot in EVERY "
            "environment (dev / staging / production). The 32-char "
            "minimum length is enforced only in production / staging — "
            "dev / test fixtures may use shorter values."
        ),
    )
    invitation_token_hmac_key_old: str | None = Field(
        default=None,
        validation_alias="INVITATION_TOKEN_HMAC_KEY_OLD",
        description=(
            "HMAC-SHA256 signing key for the OLD invitation token kid "
            "(NFR-011-010). MUST be paired with "
            "``INVITATION_TOKEN_KID_OLD``; both unset means no rotation "
            "in progress. Min 32 chars in production / staging."
        ),
    )

    @field_validator("webauthn_origins", mode="before")
    @classmethod
    def parse_webauthn_origins(cls, value: Any) -> Any:
        """Accept ECHOROO_WEBAUTHN_ORIGINS as a comma-separated list."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    # spec/011 NFR-011-010 — invitation token kid format guard.
    #
    # The wire envelope is the 4-part ``{token}.{exp}.{kid}.{mac}`` string;
    # any ``.`` (or other delimiter) inside the kid would silently break
    # ``str.rsplit('.', 3)`` decoding and route a token to the wrong key.
    # We therefore normalise whitespace and reject any kid that does not
    # match ``^[A-Za-z0-9_-]+$`` at parse time, before the env-aware
    # ``model_validator`` runs the co-presence / non-empty checks.
    #
    # ``KID_NEW`` retains an empty-string default purely as the
    # Pydantic "unset" sentinel — the env-agnostic non-empty guard in
    # ``validate_production_secrets`` (see below) rejects that default
    # at boot in EVERY environment (dev / staging / production), so no
    # ENVIRONMENT is allowed to boot without an explicit value. The
    # 32-char minimum strength bar on the companion HMAC key is the
    # only env-conditional check (prod / staging only). ``KID_OLD``
    # normalises empty / whitespace to ``None`` to match the
    # ``str | None`` semantics of its companion
    # ``INVITATION_TOKEN_HMAC_KEY_OLD`` slot.
    @field_validator(
        "invitation_token_kid_new",
        "invitation_token_kid_old",
        mode="before",
    )
    @classmethod
    def _normalise_invitation_token_kid(
        cls, value: Any, info: Any
    ) -> Any:
        is_old = info.field_name == "invitation_token_kid_old"
        if value is None:
            return None if is_old else ""
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped == "":
            return None if is_old else ""
        if not _INVITATION_TOKEN_KID_PATTERN.fullmatch(stripped):
            raise ValueError(
                "INVITATION_TOKEN_KID_{NEW,OLD} must match "
                "[A-Za-z0-9_-]+ — invitation token envelope is a 4-part "
                "`.`-separated string, dots and other delimiters in kid "
                "would break parsing"
            )
        return stripped

    # spec/011 NFR-011-010 — ``HMAC_KEY_OLD`` empty-string → None.
    # Pydantic Settings binds env vars as raw strings, so an operator
    # setting ``INVITATION_TOKEN_HMAC_KEY_OLD=`` (e.g. via .env) would
    # otherwise land as the empty string and trip the co-presence /
    # strength guards downstream. Normalising to ``None`` here matches
    # the ``str | None`` typing + the "unset" intent.
    @field_validator(
        "invitation_token_hmac_key_old",
        mode="before",
    )
    @classmethod
    def _normalise_invitation_token_hmac_key_old(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
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
    def _inherit_csrf_ttl_default(self) -> "Settings":
        """Default CSRF TTL inherits from the refresh-token window.

        The CSRF double-submit cookie and middleware verifier MUST NOT
        expire before the session does — otherwise unsafe requests start
        failing 403 csrf_failed mid-session. Keeping ``web_csrf_ttl_seconds``
        a sentinel (``0``) here means an operator who tunes
        ``WEB_REFRESH_TOKEN_TTL_SECONDS`` does not silently re-introduce
        the drift this hotfix exists to remove; the CSRF window follows.
        Setting ``WEB_CSRF_TTL_SECONDS`` to a positive value still works
        as an explicit override (e.g. for a shorter rotation policy).
        """
        if self.web_csrf_ttl_seconds <= 0:
            self.web_csrf_ttl_seconds = self.web_refresh_token_ttl_seconds
        return self

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
            # Phase 17 A-12: dedicated 2FA reset confirmation HMAC key.
            weak_defaults_2fa = {
                "dev-two-factor-confirmation-hmac-change-in-production",
            }
            if (
                self.two_factor_reset_confirmation_hmac_key in weak_defaults_2fa
                or len(self.two_factor_reset_confirmation_hmac_key) < 32
            ):
                raise ValueError(
                    "two_factor_reset_confirmation_hmac_key must be a strong "
                    "secret (min 32 chars) in production/staging — see "
                    "docs/runbook/two_factor_confirmation_key_rotation.md"
                )
            # Phase 17 A-12 Round 2 (Codex C2): the ``_OLD`` companion is
            # optional but, when set, becomes a live signing key the
            # verifier will accept during the grace window. If an operator
            # leaves a weak default in the ``_OLD`` slot during rotation
            # the attacker can forge tokens under that key — so guard it
            # to the same strength bar as ``_NEW``. An empty string is
            # treated as "unset" (Pydantic str | None semantics) so it
            # does not trip the guard.
            old_key = self.two_factor_reset_confirmation_hmac_key_old
            if (
                old_key is not None
                and old_key != ""
                and (old_key in weak_defaults_2fa or len(old_key) < 32)
            ):
                raise ValueError(
                    "two_factor_reset_confirmation_hmac_key_old, when "
                    "set during a rotation grace window, must be a "
                    "strong secret (min 32 chars) in production/staging "
                    "— see docs/runbook/two_factor_confirmation_key_rotation.md"
                )
            # Phase 17 A-8: TOTP DEK rotation grace window MUST configure
            # alias_old AND kid_old together (or both unset). A
            # half-configured pair would either leak un-rewrapped records
            # past the rotation cutover (alias only) or route every
            # historical record to the wrong CMK (kid only). Symmetric to
            # the A-12 ``..._OLD`` guard above.
            old_alias = self.two_factor_dek_cmk_alias_old
            old_kid = self.two_factor_dek_kid_old
            if (old_alias is None) != (old_kid is None) or (
                old_alias is not None and old_alias == ""
            ):
                raise ValueError(
                    "two_factor_dek_cmk_alias_old and two_factor_dek_kid_old "
                    "must be set together (or both unset) — see "
                    "docs/runbook/dek_rewrap.md"
                )
            if old_kid is not None and old_kid == self.two_factor_dek_kid_new:
                raise ValueError(
                    "two_factor_dek_kid_old must differ from "
                    "two_factor_dek_kid_new during a rotation grace window"
                )
            # spec/011 NFR-011-010 (prod / staging strength bar):
            # the 32-char minimum for HMAC keys only applies in
            # production / staging — dev / test workflows are allowed
            # weaker fixtures. Non-empty / co-presence / distinct-kid
            # guards live outside this branch and run in every
            # environment (see below).
            if len(self.invitation_token_hmac_key) < 32:
                raise ValueError(
                    "INVITATION_TOKEN_HMAC_KEY must be a strong "
                    "secret (min 32 chars) in production/staging — see "
                    "specs/011-zero-email-deployment/spec.md NFR-011-010"
                )
            old_hmac_prod = self.invitation_token_hmac_key_old
            if old_hmac_prod is not None and len(old_hmac_prod) < 32:
                raise ValueError(
                    "INVITATION_TOKEN_HMAC_KEY_OLD, when set during a "
                    "rotation grace window, must be a strong secret "
                    "(min 32 chars) in production/staging — see "
                    "specs/011-zero-email-deployment/spec.md NFR-011-010"
                )
        # spec/011 NFR-011-010 — non-empty + co-presence + distinct-kid
        # guards run in EVERY environment (dev / staging / production).
        # The spec is explicit that ``KID_NEW`` + ``HMAC_KEY`` are
        # "required at every boot"; the only env-conditional bar is the
        # 32-char minimum strength check in the prod / staging block
        # above. This keeps dev fixtures from drifting into a state that
        # would silently 500 on first invitation token issue / verify.
        if not self.invitation_token_kid_new:
            raise ValueError(
                "INVITATION_TOKEN_KID_NEW must be set at every boot "
                "— see specs/011-zero-email-deployment/spec.md "
                "NFR-011-010"
            )
        if not self.invitation_token_hmac_key:
            raise ValueError(
                "INVITATION_TOKEN_HMAC_KEY must be set at every boot "
                "— see specs/011-zero-email-deployment/spec.md "
                "NFR-011-010"
            )
        # Co-presence guard for invitation token ``_OLD`` slot — always
        # enforced (dev / staging / production) so a half-configured
        # rotation never silently routes legacy tokens to the wrong key.
        # Both ``_OLD`` slots normalise empty / whitespace → ``None`` at
        # parse time (see the ``mode="before"`` validators above), so a
        # simple ``is None`` test here is exact.
        old_kid_str = self.invitation_token_kid_old
        old_hmac_key = self.invitation_token_hmac_key_old
        kid_set = old_kid_str is not None
        hmac_set = old_hmac_key is not None
        if kid_set != hmac_set:
            raise ValueError(
                "INVITATION_TOKEN_KID_OLD and INVITATION_TOKEN_HMAC_KEY_OLD "
                "must be set together (or both unset) — see "
                "specs/011-zero-email-deployment/spec.md NFR-011-010"
            )
        if kid_set and old_kid_str == self.invitation_token_kid_new:
            raise ValueError(
                "INVITATION_TOKEN_KID_OLD must differ from "
                "INVITATION_TOKEN_KID_NEW during a rotation grace "
                "window — see "
                "specs/011-zero-email-deployment/spec.md NFR-011-010"
            )
        if self.TEST_MODE and self.ENVIRONMENT == "production":
            raise ValueError(
                "TEST_MODE must not be True in production "
                "(2FA shared-secret bypass would be ACTIVE)."
            )
        if self.TEST_MODE and not self.TEST_TOTP_SECRET_BASE32:
            raise ValueError("TEST_MODE=True requires TEST_TOTP_SECRET_BASE32 to be set.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance loaded from environment variables
    """
    return Settings()
