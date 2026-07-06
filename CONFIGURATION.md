# Echoroo Configuration Guide

This guide explains how to configure Echoroo for different deployment scenarios.

The **source of truth** for every setting is the code:

- `apps/api/echoroo/core/settings.py` — the pydantic `Settings` model (most
  vars). Note the naming convention mix documented below.
- `apps/api/echoroo/core/kms.py` — KMS / envelope-encryption vars, read
  **directly from the environment** (not through `Settings`).
- `compose.dev.yaml` — the dev Docker stack (derives many browser-facing
  values from `ECHOROO_PUBLIC_HOST` and builds `DATABASE_URL` / `REDIS_URL`).

> **Env-var naming convention (IMPORTANT).** `Settings` is loaded with
> `case_sensitive=True`, so the env-var name that actually works depends on
> how each field is declared:
>
> - **UPPERCASE fields** (`JWT_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`,
>   `S3_*`, `TEST_MODE`, `RATE_LIMIT_*`, …) are set with that exact
>   UPPERCASE name.
> - **Fields with a `validation_alias`** are set with the alias exactly as
>   written — almost always UPPERCASE and usually `ECHOROO_*`-prefixed
>   (`ECHOROO_PUBLIC_HOST`, `ECHOROO_WEBAUTHN_RP_ID`,
>   `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY`, `AWS_KMS_CMK_2FA_DEK_ALIAS_NEW`, …).
> - **Bare lowercase fields with NO alias** (`web_session_secret`,
>   `web_csrf_ttl_seconds`, `web_app_base_url`, the `web_*_cookie_name`
>   family, …) are set with their **exact lowercase field name**. The
>   UPPERCASE form is silently ignored. These are advanced knobs; the one
>   that matters in production is **`web_session_secret`** (see Web
>   Session / BFF below).

## Quick Start

1. **Copy the environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and set the required values:**
   ```bash
   # Required: Database password
   POSTGRES_PASSWORD=your_secure_password

   # Required at every boot: invitation-token signing key + kid
   # Generate the key with: openssl rand -hex 32
   INVITATION_TOKEN_KID_NEW=your-kid
   INVITATION_TOKEN_HMAC_KEY=your_generated_hex_key

   # Required: path to your audio files on the host (bind-mounted)
   ECHOROO_AUDIO_DIR=/path/to/your/audio/files
   ```

3. **Validate and start Echoroo:**
   ```bash
   ./echoroo.sh checkenv
   ./echoroo.sh start
   ```

Access the application at http://localhost:5173.

## Environment Variables

### Required for a fresh deployment

| Variable | Description |
|----------|-------------|
| `POSTGRES_PASSWORD` | Database password (choose a secure password) |
| `INVITATION_TOKEN_KID_NEW` | Active kid stamped on new invitation tokens. Required at **every** boot in every environment. |
| `INVITATION_TOKEN_HMAC_KEY` | HMAC key for invitation tokens. Required at **every** boot. Generate with `openssl rand -hex 32` (≥32 chars enforced in production/staging). |
| `ECHOROO_AUDIO_DIR` | Path on the HOST where audio files are stored (bind-mounted into the containers). |

The dev Docker stack (`compose.dev.yaml`) supplies working defaults for
everything else. Production/staging additionally require strong values for the
secrets marked **prod-guarded** below.

### Core / Application

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `ENVIRONMENT` | `development` | optional | `development` \| `staging` \| `production`. Turns on the production secret-strength guards in `settings.py`. |
| `DEBUG` | `false` | optional | Verbose/debug behaviour (compose sets `true` in dev). |
| `APP_NAME` | `Echoroo API` | optional | Display name. |
| `APP_VERSION` | `2.0.0` | optional | Also used as the Sentry release when `SENTRY_RELEASE` is unset. |
| `APP_URL` | `http://localhost:5173` | optional | Public frontend URL. Compose derives it from `ECHOROO_PUBLIC_HOST` + `ECHOROO_FRONTEND_PORT`. |

### Database

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo` | required | SQLAlchemy async connection string. Compose **builds** it from the `POSTGRES_*` vars below. |
| `POSTGRES_DB` | `echoroo` | optional | Database name (compose). |
| `POSTGRES_USER` | `postgres` | optional | Database user (compose). |
| `POSTGRES_PASSWORD` | *required* | **required** | Database password (compose refuses to start without it). |
| `POSTGRES_PORT` | `5432` | optional | Host-exposed port (dev only). |

### Redis / Celery

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | required | Rate-limit, cache, session, and token-revocation store. Compose builds a `rediss://` TLS URL from the vars below. |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | optional | Celery broker (compose points at the TLS Redis). |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | optional | Celery result backend. |
| `REDIS_PORT` | `6379` | optional | Host-exposed port (dev). |
| `REDIS_USERNAME` | `echoroo` | optional | ACL username used to build the compose `rediss://` URL. |
| `REDIS_PASSWORD` | `echoroo-dev-redis-password` | optional | ACL password used to build the compose `rediss://` URL. Change in production. |
| `REDIS_TLS_CA_FILE` | `/etc/redis/tls/ca.crt` | optional | CA bundle for the Redis TLS handshake (compose / container path). |

### S3 / Object Storage

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `S3_ENDPOINT_URL` | `http://localhost:9000` | optional | Object-store endpoint (compose → `http://localstack:4566`). |
| `S3_PUBLIC_ENDPOINT_URL` | *(unset)* | optional | Browser-facing base for presigned URLs (routed through the Vite `/s3-proxy` in dev). |
| `S3_ACCESS_KEY` | `echoroo` | optional | Access key ID. |
| `S3_SECRET_KEY` | `echoroo-dev` | **prod-guarded** | Secret access key. Must be changed away from `echoroo-dev` in production/staging. |
| `S3_BUCKET` | `echoroo` | optional | Bucket name. |
| `S3_REGION` | `us-east-1` | optional | Bucket region. |
| `S3_PRESIGNED_URL_EXPIRY` | `900` | optional | Presigned URL lifetime (seconds). |
| `AUDIO_ROOT` | `/data/audio` | optional | In-container root for audio files. |
| `AUDIO_CACHE_DIR` | *(unset)* | optional | Optional spectrogram cache directory. |
| `S3_AUDIO_CACHE_DIR` | `/data/s3_audio_cache` | optional | Local cache dir `AudioService` downloads S3 objects into. |
| `ECHOROO_AUDIO_DIR` | *required* | **required** | HOST path bind-mounted to `AUDIO_ROOT` (compose). |
| `ECHOROO_LOCALSTACK_DATA` | `./.data/localstack` | optional | Host path for LocalStack S3/KMS persistence (compose bind-mount). |

### Uploads / Quota / Janitor

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `UPLOAD_MAX_FILE_SIZE` | `1073741824` (1 GB) | optional | Max bytes per uploaded file. |
| `UPLOAD_MAX_SESSION_FILES` | `500` | optional | Max files per upload session. |
| `UPLOAD_SESSION_TTL` | `3600` | optional | TTL (seconds) for ISSUED upload sessions. |
| `UPLOAD_ALLOWED_EXTENSIONS` | `.wav,.flac,.mp3,.ogg,.opus` | optional | Allowed audio extensions (JSON list). |
| `DEFAULT_STORAGE_QUOTA` | `107374182400` (100 GB) | optional | Default per-project storage quota (bytes). |
| `JANITOR_DRY_RUN` | `true` | optional | Orphan-S3 cleanup dry-run switch; flip to `false` after prod monitoring. |
| `JANITOR_AGE_HOURS` | `24` | optional | Orphan age threshold (hours). |

### JWT / API Tokens (legacy Bearer auth)

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `JWT_SECRET_KEY` | `your-secret-key-change-in-production` | **prod-guarded** | HS256 signing key. ≥32 chars & non-default enforced in production/staging. |
| `JWT_ALGORITHM` | `HS256` | optional | JWT signing algorithm. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | optional | Access-token lifetime. |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `14` | optional | Refresh-token lifetime. |
| `API_TOKEN_PREFIX` | `ecr_` | optional | Personal API-token prefix. |
| `API_TOKEN_LENGTH` | `32` | optional | Personal API-token random length. |

### Web Session / BFF (spec/009, spec/011)

Cookie-based first-party session used by the SvelteKit BFF. **These fields have
no alias — set them with their exact lowercase names** (see the naming note at
the top). The only one that matters operationally is `web_session_secret`.

| Variable (exact case) | Default | Req | Description |
|-----------------------|---------|-----|-------------|
| `web_session_secret` | `dev-web-session-secret-change-in-production` | **prod-guarded** | First-party web-session HMAC/JWT secret. ≥32 chars & non-default enforced in production/staging. **Not set by compose** — you must add it for a non-dev deployment. |
| `SESSION_TIMEOUT_MINUTES` | `120` | optional | Legacy session timeout (minutes). |
| `web_session_cookie_name` | `echoroo_session` | optional | Session cookie name. |
| `web_refresh_cookie_name` | `echoroo_refresh` | optional | Refresh cookie name. |
| `web_csrf_cookie_name` | `echoroo_csrf` | optional | CSRF double-submit cookie name. |
| `web_logged_in_cookie_name` | `echoroo_logged_in` | optional | Non-sensitive `Path=/` marker cookie for SvelteKit route guards. |
| `web_access_token_ttl_seconds` | `900` | optional | Access-token TTL (seconds). |
| `web_refresh_token_ttl_seconds` | `2592000` (30 d) | optional | Refresh-token TTL (seconds). |
| `web_csrf_ttl_seconds` | `0` | optional | CSRF cookie/verifier TTL. `0` = inherit `web_refresh_token_ttl_seconds`. |
| `web_interim_token_ttl_seconds` | `900` | optional | Interim (pre-2FA) token TTL. |
| `webauthn_interim_token_ttl_seconds` | `300` | optional | WebAuthn interim token TTL. |
| `web_app_base_url` | `https://echoroo.app` | optional | Absolute base URL used when building links in the BFF. |

### Network / Browser-facing

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `ECHOROO_PUBLIC_HOST` | `localhost` | optional | Bare browser-facing hostname or IP (no scheme/port). The single knob from which all browser-facing URLs, CORS origins and WebAuthn defaults derive. See [LAN / remote-host deployment](#lan--remote-host-deployment). |
| `ECHOROO_API_PORT` | `8002` | optional | Host-exposed backend API port. |
| `ECHOROO_FRONTEND_PORT` | `5173` | optional | Host-exposed frontend port (dev). |
| `ALLOWED_ORIGINS` | derived | optional | CORS allowlist (JSON list). Compose derives it from `ECHOROO_PUBLIC_HOST`; explicit value always wins. |
| `PUBLIC_API_URL` | derived | optional | **Frontend** — browser-facing API base. Compose derives from `ECHOROO_PUBLIC_HOST` + `ECHOROO_API_PORT`. |
| `ECHOROO_API_URL` | `http://backend:8000` | optional | **Frontend** — server-side (SSR/BFF) API base inside the Docker network. |
| `S3_PROXY_TARGET` | *(vite)* | optional | **Frontend** — LocalStack target the Vite `/s3-proxy` forwards to. |

#### LAN / remote-host deployment

To serve Echoroo over a LAN IP, a GPU server, or a domain name, set **one
variable** and restart — no tracked file needs editing:

```bash
# .env
ECHOROO_PUBLIC_HOST=192.168.1.100   # your server's IP or FQDN
```

```bash
./echoroo.sh dev restart
```

`ECHOROO_PUBLIC_HOST` is a **bare hostname or IP** — no `http://`, no port.
Everything browser-facing derives from it: the frontend `APP_URL`, the
`PUBLIC_API_URL`, the S3 presigned-URL proxy base, the CORS allowlist, the
Vite `allowedHosts`, and the WebAuthn relying-party ID + origins. Ports keep
their own knobs (`ECHOROO_FRONTEND_PORT` / `ECHOROO_API_PORT`); the scheme
stays `http` in the dev stack (front it with a reverse proxy for TLS in
production).

**Dual-origin (important):** setting a non-localhost host does **not** drop
`localhost` from the CORS / WebAuthn allowlists. Both the public-host origin
**and** the localhost origin stay enabled at the same time, so users who
reach the app over an SSH port-forward (arriving as `localhost`) keep working
alongside LAN clients. Leaving `ECHOROO_PUBLIC_HOST=localhost` is
byte-identical to the previous setup.

Make sure the host firewall allows the frontend + API ports (e.g. `sudo ufw
allow 5173` and `sudo ufw allow 8002`).

### WebAuthn (hardware-key 2FA, FR-111a)

> The env names are **`ECHOROO_`-prefixed** (`validation_alias`). Bare
> `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGIN` are **not** read by the code.

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `ECHOROO_WEBAUTHN_RP_ID` | `localhost` (or `ECHOROO_PUBLIC_HOST`) | optional | Relying Party ID; bare host, must match the browser hostname. |
| `ECHOROO_WEBAUTHN_RP_NAME` | `Echoroo` | optional | Relying Party display name. |
| `ECHOROO_WEBAUTHN_ORIGINS` | `http://localhost:3000` (+ public host) | optional | Comma-separated allowed WebAuthn origins. |
| `ECHOROO_WEBAUTHN_CHALLENGE_TTL_SECONDS` | `300` | optional | WebAuthn challenge TTL in Redis. |

### Security / Rate-limiting / Password Hashing

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `ECHOROO_TRUSTED_PROXY_CIDRS` | *(empty)* | optional | Comma-separated CIDRs of trusted reverse proxies. `X-Forwarded-For` is honoured **only** from a socket peer inside one of these CIDRs. Empty = never trust XFF. Set to your proxy CIDRs behind nginx/ALB/Cloudflare. |
| `ARGON2_MEMORY_COST` | `19456` | optional | Argon2id memory cost (KiB). |
| `ARGON2_TIME_COST` | `2` | optional | Argon2id time cost. |
| `ARGON2_PARALLELISM` | `1` | optional | Argon2id parallelism. |
| `RATE_LIMIT_LOGIN_ATTEMPTS` | `5` | optional | Login attempts per window. |
| `RATE_LIMIT_LOGIN_WINDOW_SECONDS` | `60` | optional | Login rate-limit window. |
| `RATE_LIMIT_REGISTER_ATTEMPTS` | `3` | optional | Register attempts per window. |
| `RATE_LIMIT_REGISTER_WINDOW_SECONDS` | `3600` | optional | Register rate-limit window. |
| `RATE_LIMIT_UPLOAD_SESSION_CREATE_ATTEMPTS` | `10` | optional | Upload-session create attempts per window. |
| `RATE_LIMIT_UPLOAD_SESSION_CREATE_WINDOW_SECONDS` | `3600` | optional | Upload-session create window. |
| `RATE_LIMIT_UPLOAD_SESSION_COMPLETE_ATTEMPTS` | `20` | optional | Upload-session complete attempts per window. |
| `RATE_LIMIT_UPLOAD_SESSION_COMPLETE_WINDOW_SECONDS` | `3600` | optional | Upload-session complete window. |
| `TRUSTED_DEVICE_REGISTRATION_ENABLED` | `false` | optional | Enable trusted-device registration (spec/010). |
| `TRUSTED_DEVICE_BYPASS_ENABLED` | `false` | optional | Allow trusted-device 2FA bypass. |
| `TRUSTED_DEVICE_COOKIE_NAME` | `echoroo_trusted_device` | optional | Trusted-device cookie name. |
| `TRUSTED_DEVICE_COOKIE_TTL_SECONDS` | `2592000` (30 d) | optional | Trusted-device cookie TTL. |

#### Test-mode 2FA bypass — **dev-only, refused in production**

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `TEST_MODE` | `false` | dev-only | Enables test helpers incl. the 2FA shared-secret bypass. `TEST_MODE=true` in `production` **fails startup**. |
| `TEST_TOTP_SECRET_BASE32` | *(unset)* | dev-only | Shared Base32 TOTP secret. **Required** when `TEST_MODE=true`. |

### Invitation Token Signing (spec/011 NFR-011-010)

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `INVITATION_TOKEN_KID_NEW` | *(empty)* | **required every boot** | Active kid stamped on new tokens. Empty value fails startup in every environment. |
| `INVITATION_TOKEN_HMAC_KEY` | *(empty)* | **required every boot** | HMAC key for the active kid. ≥32 chars enforced in production/staging. |
| `INVITATION_TOKEN_KID_OLD` | *(unset)* | optional | Previous kid accepted during a rotation grace window. Must be paired with `_HMAC_KEY_OLD`. |
| `INVITATION_TOKEN_HMAC_KEY_OLD` | *(unset)* | optional | HMAC key for the previous kid. Must be paired with `_KID_OLD`. |
| `INVITATION_TOKEN_KID_GRACE_HOURS` | `24` | optional | Hours past the invitation TTL that `_OLD`/legacy tokens stay verifiable. |

### 2FA Reset-Confirmation HMAC (Phase 17 A-12)

Env-driven key rotation; see `docs/runbook/two_factor_confirmation_key_rotation.md`.

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY` | `dev-two-factor-confirmation-hmac-change-in-production` | **prod-guarded** | Dedicated HMAC key for 2FA reset-confirmation tokens. ≥32 chars & non-default in production/staging. |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD` | *(unset)* | optional | Previous key during a rotation grace window. ≥32 chars if set (prod/staging). |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW` | `v1` | optional | Kid stamped on newly issued tokens. |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD` | *(unset)* | optional | Kid accepted from prior tokens; pair with `_HMAC_KEY_OLD`. |

### KMS / Envelope Encryption (spec/006 permissions redesign)

Envelope encryption (TOTP DEK), PII hashing, audit-chain HMAC, and invitation
signing are backed by KMS (LocalStack in dev, AWS KMS in staging/prod). The
alias defaults match `scripts/init-localstack.sh` so dev works out of the box.

**Read directly from the environment in `core/kms.py`:**

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `AWS_KMS_ENDPOINT` / `AWS_ENDPOINT_URL_KMS` | *(none → real AWS)* | optional | KMS service endpoint (`http://localstack:4566` in dev). Either name is accepted. |
| `AWS_KMS_REGION` | `us-east-1` (falls back to `AWS_DEFAULT_REGION`) | optional | Region for all CMK operations. |
| `AWS_KMS_CMK_2FA_ALIAS` | `alias/echoroo-totp-dek` | optional | CMK alias for TOTP-secret envelope encryption (FR-051). |
| `AWS_KMS_CMK_PII_HASH_ALIAS` | `alias/echoroo-pii-hash-hmac` | optional | CMK alias for audit PII hashing via `GenerateMac` (FR-091b, v1). |
| `AWS_KMS_CMK_PII_HASH_ALIAS_V2` | *(unset)* | optional | v2 PII-hash alias; setting it enables FR-091b dual-write rotation. Unset = single-key mode. |
| `AWS_KMS_CMK_AUDIT_CHAIN_ALIAS` | `alias/echoroo-audit-chain-hmac` | optional | CMK alias for audit-log chain HMAC (FR-093). |
| `AWS_KMS_CMK_INVITATION_HMAC_ALIAS` | `alias/echoroo-invitation-hmac` | optional | Legacy single-key invitation-signing alias; used as the `_NEW` fallback. |
| `AWS_KMS_CMK_INVITATION_HMAC_ALIAS_NEW` | *(falls back to legacy)* | optional | Current invitation-signing CMK during a rotation. |
| `AWS_KMS_CMK_INVITATION_HMAC_ALIAS_OLD` | *(unset)* | optional | Previous invitation-signing CMK (grace window only). |
| `ECHOROO_PII_HASH_ROTATION_COMPLETE` | *(unset)* | optional | Operator flag driving the FR-091b rotation phase machine in `kms.py`. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `test` (dev) | optional | boto3 credentials (LocalStack accepts any non-empty value). |

**TOTP-DEK CMK rotation, read via `Settings` (`validation_alias`, Phase 17 A-8)** —
see `docs/runbook/dek_rewrap.md`:

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `AWS_KMS_CMK_2FA_DEK_ALIAS_NEW` | `alias/echoroo-totp-dek` | optional | CMK alias that wraps newly encrypted TOTP DEKs. |
| `AWS_KMS_CMK_2FA_DEK_ALIAS_OLD` | *(unset)* | optional | Previous alias for decrypting historical DEKs; pair with `_KID_OLD`. |
| `AWS_KMS_CMK_2FA_DEK_KID_NEW` | `1` | optional | DEK version stamped on new TOTP secrets. |
| `AWS_KMS_CMK_2FA_DEK_KID_OLD` | *(unset)* | optional | Previous DEK version accepted during the grace window; pair with `_ALIAS_OLD`. |

> KMS is intentionally **not** probed at boot (production IAM may deny
> `kms:DescribeKey`); first-use KMS errors are surfaced with an actionable
> message instead.

### PII-hash / API-key lifecycle (Phase 17 backlog)

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `PII_HASH_ROTATION_GRACE_DAYS` | `90` | optional | Informational — documents the FR-091b 90-day rotation window. Not consumed by the runtime today. |
| `API_KEY_SCOPE_DEGRADE_DAYS` | `180` | optional | Age (days) at which an API key's **write** scopes are stripped (FR-083). |
| `API_KEY_REVOKE_DAYS` | `270` | optional | Age (days) at which an API key is fully revoked (FR-083). |

### Machine Learning Settings

Echoroo uses machine-learning models (BirdNET, Perch — both on TensorFlow) for
species detection. The defaults preserve GPU behaviour, so a host with a
working GPU needs none of these set.

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `ECHOROO_ML_USE_GPU` | `true` | optional | Use the GPU for inference. `false` forces CPU (`CUDA_VISIBLE_DEVICES=-1`) for both BirdNET and Perch. |
| `ECHOROO_ML_GPU_BATCH_SIZE` | `16` | optional | Segments processed in parallel per inference batch. |
| `ECHOROO_ML_FEEDERS` | `1` | optional | File-feeder processes for audio loading (minimum `1`). |
| `ECHOROO_ML_WORKERS` | `1` | optional | Inference worker processes (minimum `1`). |
| `ECHOROO_ML_CPU_NUM_THREADS` | `8` | optional | Thread cap applied **only** in CPU mode (bounds TF/OpenMP/BLAS pools). |
| `ECHOROO_ML_CPU_WARMUP_BATCHES` | `1` | optional | Comma-separated Perch warmup batch sizes used **only** in CPU mode (empty = skip warmup). GPU mode always warms up `1,6,10,16`. |
| `ECHOROO_ML_GPU_ALLOW_GROWTH` | `true` | optional | In GPU mode, set `TF_FORCE_GPU_ALLOW_GROWTH=true` so TF grows GPU memory on demand. |
| `ECHOROO_WORKER_MEM_LIMIT` | `0` | optional | Compose-level RAM cap for the worker container (`0` = unlimited). Set e.g. `24g` on a CPU/Blackwell box. |

**Performance Tuning:**

- **GPU_BATCH_SIZE:** Higher values improve throughput but require more GPU memory. Reduce if you get `CUDA_ERROR_OUT_OF_MEMORY`.
- **FEEDERS / WORKERS:** Must be `>= 1`; setting `0` fails at startup with an opaque pydantic validation error. To effectively disable ML work, scale the worker container down (e.g. `replicas: 0`) instead of zeroing these.
- **CPU mode:** When `ECHOROO_ML_USE_GPU=false`, inference threads are capped to `ECHOROO_ML_CPU_NUM_THREADS` and the Perch warmup shrinks to `ECHOROO_ML_CPU_WARMUP_BATCHES`; pair with `ECHOROO_WORKER_MEM_LIMIT` to bound RAM.

### External Integrations

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `XENO_CANTO_API_KEY` | *(unset)* | optional | API key for the [Xeno-canto](https://xeno-canto.org/) recording archive. Required by the "From Xeno-canto" search/import feature. Unset or `demo` disables the integration. |
| `IUCN_API_TOKEN` | *(unset)* | optional | IUCN Red List API token. Required by the IUCN threat-status sync worker/script; unset skips the sync. |
| `IUCN_API_BASE_URL` | `https://apiv3.iucnredlist.org/api/v3` | optional | IUCN Red List API base URL. |

**Xeno-canto setup:**

1. Register a free account at <https://xeno-canto.org/> (or sign in).
2. Copy the value under **Account → API key**.
3. Set `XENO_CANTO_API_KEY=<your key>` in `.env` and restart the API + worker.

When the key is unset (or left at the placeholder `demo`, which the Xeno-canto v3 API rejects):

- The "From Xeno-canto" tab on the search screen is **disabled** with an explanatory message.
- The Xeno-canto search endpoint returns HTTP **409** `{ "error": "xeno_canto_not_configured" }` rather than failing with a confusing upstream error.

### Observability

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `SENTRY_DSN` | *(unset)* | optional | Sentry DSN. Unset/empty = Sentry telemetry disabled (spec/011 default). |
| `SENTRY_RELEASE` | *(falls back to `APP_VERSION`)* | optional | Release tag reported to Sentry. |

### Boot Probes (fail-fast on missing infrastructure)

At startup the API (FastAPI lifespan) and each Celery worker run lightweight probes so a misconfigured deployment crashes loudly before serving traffic, instead of surfacing a generic 500 deep inside a user flow.

| Probe | Timeout | Development | Staging / Production |
|-------|---------|-------------|----------------------|
| Redis `ping()` | 2s | Hard fail | Hard fail |
| S3 `head_bucket` | 5s | Log ERROR, continue | Hard fail |

KMS is intentionally **not** probed at boot (production IAM may deny `kms:DescribeKey`); first-use KMS errors are surfaced with an actionable message instead.

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_SKIP_BOOT_CHECKS` | Skip all boot probes (Redis ping, S3 head_bucket). Intended for offline tooling / tests. | `0` |

### Security Fail-Closed Switches (W4-2)

Two legacy code paths historically **failed open** on an infrastructure outage. They now fail **closed** by default; the switches below exist only as dev / offline escape hatches and are **refused when `ENVIRONMENT=production`**.

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_AUTH_REVOCATION_FAIL_CLOSED` | Legacy Bearer/JWT token-revocation check (`services/auth.py`). When `true` a Redis outage returns HTTP **503** instead of silently accepting a revoked token (and a logout that cannot persist its revocation marker fails rather than reporting success). Set `false` only in dev to restore fail-open. Refused in production. | `true` |
| `ECHOROO_HIBP_FAIL_OPEN` | HaveIBeenPwned breach check during password enforcement (register / change-password / invitation accept). When `false` an HIBP outage returns HTTP **503** ("verification service unavailable") instead of silently accepting a possibly-breached password. Set `true` (or enable `TEST_MODE`) only in dev to restore fail-open. Refused in production. | `false` |

### Dev / Test-only helpers

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `WIPE_TEST_SIGNERS` | *(unset)* | dev-only | Comma-separated confirmation signers required by `scripts/wipe_database.py`. |
| `ECHOROO_REPO_ROOT` | *(repo root)* | tooling | Repo-root override consumed by some helper scripts. |

## Deployment Scenarios

### 1. Local Development with Docker

Perfect for development on your laptop/desktop using Docker.

```bash
# .env
POSTGRES_PASSWORD=dev_password
INVITATION_TOKEN_KID_NEW=dev-kid-001
INVITATION_TOKEN_HMAC_KEY=replace_with_openssl_rand_hex_32_output
ECHOROO_AUDIO_DIR=/home/user/audio
ECHOROO_PUBLIC_HOST=localhost
```

```bash
./echoroo.sh checkenv
./echoroo.sh start
```

**Access:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8002
- API Docs: http://localhost:8002/docs
- Database: localhost:5432

### 2. Local Development Without Docker

For development without Docker containers.

**Requirements:**
- Python 3.11+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 20+
- npm
- PostgreSQL 16+ with pgvector
- Redis

**Database Setup (PostgreSQL + pgvector):**

```bash
docker run -d \
  --name echoroo-postgres \
  -e POSTGRES_PASSWORD=your_password \
  -e POSTGRES_DB=echoroo \
  -p 5432:5432 \
  pgvector/pgvector:pg17
```

**Configure `.env`** — the backend consumes a single `DATABASE_URL` (there is
no `ECHOROO_DB_*` split); Redis uses `REDIS_URL`:

```bash
DATABASE_URL=postgresql+asyncpg://postgres:your_password@localhost:5432/echoroo
REDIS_URL=redis://localhost:6379/0
INVITATION_TOKEN_KID_NEW=dev-kid-001
INVITATION_TOKEN_HMAC_KEY=replace_with_openssl_rand_hex_32_output
# KMS aliases + endpoint if you run LocalStack; otherwise the defaults
# resolve against real AWS KMS.
```

**Start servers:**

```bash
# Terminal 1: Backend
cd apps/api && uv run uvicorn echoroo.main:app --reload

# Terminal 2: Frontend
cd apps/web && npm run dev
```

**Access:**
- Frontend: http://localhost:5173
- Backend API: http://localhost:8000

### 3. Remote Server (IP Address)

For deployment on a remote server accessed by IP address.

```bash
# .env
POSTGRES_PASSWORD=secure_password
INVITATION_TOKEN_KID_NEW=prod-kid-001
INVITATION_TOKEN_HMAC_KEY=$(openssl rand -hex 32)
ECHOROO_AUDIO_DIR=/data/audio
ECHOROO_PUBLIC_HOST=192.168.1.100
```

**Access:**
- Frontend: http://192.168.1.100:5173
- Backend: http://192.168.1.100:8002

**Important:** Make sure the firewall allows ports 5173 and 8002. See
[LAN / remote-host deployment](#lan--remote-host-deployment) for the
dual-origin behaviour (localhost stays enabled alongside the IP).

### 4. Production with Domain

A production compose file is not currently present in this repository.
`./echoroo.sh prod ...` exits with an unsupported-environment error until a
production stack is added. When you build one, set `ENVIRONMENT=production` and
provide strong values for every **prod-guarded** secret above
(`JWT_SECRET_KEY`, `web_session_secret`, `S3_SECRET_KEY`,
`TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY`, `INVITATION_TOKEN_HMAC_KEY` ≥32
chars), and point the `AWS_KMS_*` aliases at real AWS KMS CMKs.

## Architecture

### Development Mode (`./echoroo.sh start`)

```
┌─────────────────────────────────────────────────────┐
│                    Host Machine                      │
├─────────────────────────────────────────────────────┤
│  Port 5173 ─────► Frontend (SvelteKit)              │
│  Port 8002 ─────► Backend (FastAPI)                 │
│  Port 5432 ─────► PostgreSQL + pgvector             │
└─────────────────────────────────────────────────────┘
```

- All services have ports exposed to host
- Hot reload enabled for both frontend and backend
- Database accessible from host for development tools

### Production Mode

Not currently defined in this repository. Add a production stack before documenting or using `./echoroo.sh prod ...`.

## Troubleshooting

### Cannot access from remote machine

1. **Check `ECHOROO_PUBLIC_HOST`:**
   ```bash
   # Should be your server's IP or domain, not localhost
   ECHOROO_PUBLIC_HOST=192.168.1.100
   ```
   Then restart (`./echoroo.sh dev restart`). localhost stays enabled too,
   so SSH port-forward access keeps working — see
   [LAN / remote-host deployment](#lan--remote-host-deployment).

2. **Check firewall:**
   ```bash
   sudo ufw allow 5173
   sudo ufw allow 8002
   ```

### Database connection issues

1. **Check PostgreSQL is running:**
   ```bash
   ./echoroo.sh status
   ```

2. **Check database logs:**
   ```bash
   ./echoroo.sh logs db
   ```

3. **Connect to database directly:**
   ```bash
   ./echoroo.sh db
   ```

### Audio files not accessible

1. **Verify `ECHOROO_AUDIO_DIR` path exists:**
   ```bash
   ls -la $ECHOROO_AUDIO_DIR
   ```

2. **Check the path is absolute, not relative:**
   ```bash
   # Correct
   ECHOROO_AUDIO_DIR=/home/user/audio

   # Wrong
   ECHOROO_AUDIO_DIR=./audio
   ```

### Container build fails

1. **Clean and rebuild:**
   ```bash
   ./echoroo.sh build --no-cache
   ```

2. **Remove all containers and volumes (DATA LOSS!):**
   ```bash
   ./echoroo.sh clean-all
   ```

## Summary

**What you must configure for a fresh deployment:**
- `POSTGRES_PASSWORD` (database password)
- `INVITATION_TOKEN_KID_NEW` + `INVITATION_TOKEN_HMAC_KEY` (required at every boot)
- `ECHOROO_AUDIO_DIR` (path to audio files)

**Additionally for production/staging (`ENVIRONMENT`):**
- Strong `JWT_SECRET_KEY`, `web_session_secret`, `S3_SECRET_KEY`,
  `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY` (≥32 chars)
- Real `AWS_KMS_*` CMK aliases pointing at AWS KMS

**What the dev Docker stack configures automatically:**
- `DATABASE_URL` / `REDIS_URL` (from `POSTGRES_*` / `REDIS_*`)
- Browser-facing URLs, CORS, WebAuthn (from `ECHOROO_PUBLIC_HOST`)
- KMS CMK aliases (LocalStack bootstrap in `scripts/init-localstack.sh`)
- Health checks and boot probes

Run `./echoroo.sh checkenv` to validate your `.env` before starting.
