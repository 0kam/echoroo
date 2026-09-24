# Echoroo Configuration Guide

This guide explains how to configure Echoroo for different deployment scenarios.

The **source of truth** for every setting is the code:

- `apps/api/echoroo/core/settings.py` — the pydantic `Settings` model (most
  vars). Note the naming convention mix documented below.
- `apps/api/echoroo/core/keyring.py` — validates the `KEYRING_*` selectors
  against the keyring file (see `docs/runbook/keyring.md`).
- `compose.dev.yaml` — the dev Docker stack (derives many browser-facing
  values from `ECHOROO_PUBLIC_HOST` and builds `DATABASE_URL` / `REDIS_URL`).

> **Env-var naming convention (IMPORTANT).** `Settings` is loaded with
> `case_sensitive=True`, so the env-var name that actually works depends on
> how each field is declared:
>
> - **UPPERCASE fields** (`JWT_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`,
>   `TEST_MODE`, `RATE_LIMIT_*`, …) are set with that exact
>   UPPERCASE name.
> - **Fields with a `validation_alias`** are set with the alias exactly as
>   written — almost always UPPERCASE and usually `ECHOROO_*`-prefixed
>   (`ECHOROO_PUBLIC_HOST`, `ECHOROO_WEBAUTHN_RP_ID`,
>   `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY`, …).
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

   # Container path for the POSIX storage root
   STORAGE_ROOT=/data/storage

   # Host directory containing the local keyring file
   ECHOROO_KEYRING_DIR=/etc/echoroo
   ```

3. **Provision and validate the local keyring:**
   ```bash
   sudo install -d -o 1000 -g 1000 -m 0750 /etc/echoroo
   docker compose -f compose.dev.yaml run --rm keyring-admin \
     create /keyring/echoroo-keyring.json --prefix 2026-01
   docker compose -f compose.dev.yaml run --rm keyring-admin \
     check /keyring/echoroo-keyring.json
   ```

   Add the IDs created by that command to `.env`:
   ```dotenv
   KEYRING_TOTP_KEY=totp-wrap-2026-01
   KEYRING_TOTP_KEY_VERSION=1
   KEYRING_PII_KEY=pii-hmac-2026-01
   KEYRING_AUDIT_KEY=audit-hmac-2026-01
   ```

4. **Validate and start Echoroo:**
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
| `ECHOROO_KEYRING_DIR` | Host directory containing the provisioned `echoroo-keyring.json` bind source (default `/etc/echoroo`). |
| `KEYRING_TOTP_KEY`, `KEYRING_TOTP_KEY_VERSION` | Selected `totp-wrap` key ID and positive version for new TOTP DEKs. |
| `KEYRING_PII_KEY` | Selected `pii-hmac` key ID for PII hashes. |
| `KEYRING_AUDIT_KEY` | Selected `audit-hmac` key ID for audit-chain MACs. |

The dev Docker stack (`compose.dev.yaml`) supplies working defaults for the
remaining non-keyring settings. It does not create the keyring or choose its
selectors. Production/staging additionally require strong values for the
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

### POSIX storage (Lustre in production)

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `STORAGE_ROOT` | `/data/storage` | optional | Provisioned POSIX root for recordings, model artifacts, search reference audio, and audit archives. Bind-mount the same path in the API and every worker. In production, `/lustre/echoroo/storage` is the documented example host directory bound to this container path. |
| `COMPRESSED_CACHE_DIR` | `/data/audio_compressed` | optional | Lustre directory for generated OGG playback files. The cache is disposable. |
| `COMPRESSED_CACHE_MAX_AGE_DAYS` | `30` | optional | Maximum age for generated compressed playback files before the scheduled sweep removes them. |

`STORAGE_ROOT` must be provisioned before the API or workers start. In the dev
stack, `/data/storage` is inside the `backend-data` named volume. From the
Docker host, run the provisioner inside the backend container so it runs as
UID/GID 1000 against that mounted path:

```bash
docker compose -f compose.dev.yaml run --rm backend uv run python -m \
  echoroo.scripts.provision_storage /data/storage
```

For production, bind the example host directory `/lustre/echoroo/storage` to
`/data/storage` in the API and every worker before running the same command.

The provisioner creates the root with mode `0750`, writes the
`.echoroo-storage` marker, and runs the full filesystem probe. A missing or
unprovisioned root is an infrastructure error, not an empty store. The health
and readiness component is named `storage`.

### Uploads / Quota / Janitor

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `UPLOAD_MAX_FILE_SIZE` | `1073741824` (1 GB) | optional | Max bytes per uploaded file. |
| `UPLOAD_MAX_SESSION_FILES` | `500` | optional | Max files per upload session. |
| `UPLOAD_SESSION_TTL` | `3600` | optional | TTL (seconds) for ISSUED upload sessions. |
| `UPLOAD_ALLOWED_EXTENSIONS` | `.wav,.flac,.mp3,.ogg,.opus` | optional | Allowed audio extensions (JSON list). |
| `UPLOAD_STAGING_DIR` | `/data/upload_staging` | optional | Directory for staged upload chunks. |
| `UPLOAD_CHUNK_SIZE` | `8388608` | optional | Maximum upload chunk request size (bytes). |
| `UPLOAD_MAX_CONCURRENT_CHUNKS_PER_USER` | `6` | optional | Maximum chunk requests one user may have in flight at once. |
| `UPLOAD_RETENTION_SECONDS` | `86400` | optional | Inactivity window before unfinished uploads are removed (seconds). |
| `DEFAULT_STORAGE_QUOTA` | `107374182400` (100 GB) | optional | Default per-project storage quota (bytes). |
| `JANITOR_DRY_RUN` | `true` | optional | Orphan-storage cleanup dry-run switch; flip to `false` after prod monitoring. |
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
`PUBLIC_API_URL`, the CORS allowlist, the Vite `allowedHosts`, and the
WebAuthn relying-party ID + origins. Ports keep
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
| `RATE_LIMIT_UPLOAD_CHUNK_ATTEMPTS` | `600` | optional | Upload chunk attempts per window. |
| `RATE_LIMIT_UPLOAD_CHUNK_WINDOW_SECONDS` | `60` | optional | Upload chunk rate-limit window. |
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

### Local keyring (TOTP envelope encryption, PII hashing, audit chain)

TOTP secret DEKs are wrapped, and PII hashes and audit-chain MACs computed, with
keys from a local keyring file (`docs/architecture/kms-local-keyring.md`). The
file is created with the `keyring-admin` compose service and mounted read-only
into `backend`, `worker` and `worker-cpu`; operations are in
`docs/runbook/keyring.md`. The selectors below are read via `Settings` and
validated against the file at boot and on first use; an empty value means unset.

| Variable | Default | Req | Description |
|----------|---------|-----|-------------|
| `KEYRING_FILE` | `/run/secrets/echoroo-keyring.json` | required | Path of the keyring inside the container (compose sets it). |
| `ECHOROO_KEYRING_DIR` | `/etc/echoroo` | optional | Host directory holding `echoroo-keyring.json` (compose bind source). |
| `KEYRING_TOTP_KEY` | *(none)* | required | Key id (purpose `totp-wrap`) wrapping new TOTP DEKs. |
| `KEYRING_TOTP_KEY_VERSION` | `1` | required | DEK version stamped on new TOTP secrets. |
| `KEYRING_TOTP_KEY_OLD` / `KEYRING_TOTP_KEY_VERSION_OLD` | *(unset)* | optional | Previous TOTP key and version during a rewrap window; set together. |
| `KEYRING_PII_KEY` | *(none)* | required | Key id (purpose `pii-hmac`) for v1 PII hashes; stays selected indefinitely. |
| `KEYRING_PII_KEY_V2` | *(unset)* | optional | Second PII key; setting it enables v1+v2 dual-write. |
| `KEYRING_AUDIT_KEY` | *(none)* | required | Key id (purpose `audit-hmac`) for the audit chain; pinned for the data's lifetime. |

Legacy cloud key-selector variables and `ECHOROO_PII_HASH_ROTATION_COMPLETE`
are rejected at startup if still present.

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
| `ECHOROO_WORKER_SHM_SIZE` | `2gb` | optional | Compose-level `/dev/shm` size for the worker container. BirdNET/Perch stage audio in shared memory; Docker's 64 MB default makes detection hang. See **Shared memory** below. |

**Performance Tuning:**

- **GPU_BATCH_SIZE:** Higher values improve throughput but require more GPU memory. Reduce if you get `CUDA_ERROR_OUT_OF_MEMORY`.
- **FEEDERS / WORKERS:** Must be `>= 1`; setting `0` fails at startup with an opaque pydantic validation error. To effectively disable ML work, scale the worker container down (e.g. `replicas: 0`) instead of zeroing these.
- **CPU mode:** When `ECHOROO_ML_USE_GPU=false`, inference threads are capped to `ECHOROO_ML_CPU_NUM_THREADS` and the Perch warmup shrinks to `ECHOROO_ML_CPU_WARMUP_BATCHES`; pair with `ECHOROO_WORKER_MEM_LIMIT` to bound RAM.
- **Shared memory (`/dev/shm`):** the `birdnet` library stages audio for every inference call in a shared-memory ring of `2 × n_workers × batch_size` float32 segments (BirdNET 576 KB, Perch 640 KB each). `n_workers` is `ECHOROO_ML_WORKERS` in GPU mode but the **physical core count** in CPU mode, so a 12-core CPU box needs ~221 MB (BirdNET) / ~246 MB (Perch) at the default batch size of 16. If the ring does not fit, detection and embedding runs hang forever (joblib `No space left on device` warnings, worker idle at 0% CPU) instead of failing. The compose file therefore sets `shm_size: ${ECHOROO_WORKER_SHM_SIZE:-2gb}` on the `worker` service, which covers up to ~100 physical cores; tmpfs pages are only charged (against `ECHOROO_WORKER_MEM_LIMIT`) when written. Any other container that consumes the `gpu` queue needs the same `shm_size`. A gpu-queue worker logs a `/dev/shm is N MiB but BirdNET/Perch inference needs at least M MiB` warning at startup when it is too small.

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
| Storage `ensure_ready()` | 5s | Log error and continue | Hard fail |
| Keyring load and selector validation | — | Hard fail | Hard fail |

| Variable | Description | Default |
|----------|-------------|---------|
| `ECHOROO_SKIP_BOOT_CHECKS` | Skip all boot probes (Redis ping, storage readiness). Intended for offline tooling / tests. | `0` |

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
STORAGE_ROOT=/data/storage
ECHOROO_PUBLIC_HOST=localhost
```

Provision the keyring and add its selectors as shown in the Quick Start before
running the commands below.

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
# KEYRING_FILE and the KEYRING_* selectors for a keyring created with
# `python -m echoroo.scripts.keyring create` (see docs/runbook/keyring.md).
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
STORAGE_ROOT=/data/storage
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
(`JWT_SECRET_KEY`, `web_session_secret`,
`TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY`, `INVITATION_TOKEN_HMAC_KEY` ≥32
chars), and provision a keyring (`docs/runbook/keyring.md`).

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

### Storage files not accessible

1. **Verify `STORAGE_ROOT` is the provisioned path:**
   ```bash
   ls -la $STORAGE_ROOT
   test -f "$STORAGE_ROOT/.echoroo-storage"
   ```

2. **Check the path is absolute, not relative:**
   ```bash
   # Correct
   STORAGE_ROOT=/data/storage

   # Wrong
   STORAGE_ROOT=./storage
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
- `STORAGE_ROOT` (provisioned Lustre/POSIX storage tree; `/data/storage` by default)

**Additionally for production/staging (`ENVIRONMENT`):**
- Strong `JWT_SECRET_KEY`, `web_session_secret`,
  `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY` (≥32 chars)
- A provisioned keyring and its `KEYRING_*` selectors, backed up offline

**What the dev Docker stack configures automatically:**
- `DATABASE_URL` / `REDIS_URL` (from `POSTGRES_*` / `REDIS_*`)
- Browser-facing URLs, CORS, WebAuthn (from `ECHOROO_PUBLIC_HOST`)
- The keyring mount (the keyring itself is created once with `keyring-admin`)
- Health checks and boot probes

Run `./echoroo.sh checkenv` to validate your `.env` before starting.
