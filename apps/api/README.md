# Echoroo API

Backend API for Echoroo - Bird sound recognition and analysis platform.

## Technology Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL with pgvector extension
- **ORM**: SQLAlchemy 2.0
- **Task Queue**: Celery + Redis
- **Authentication**: JWT with Argon2 password hashing
- **Validation**: Pydantic v2

## Project Structure

```
apps/api/
├── echoroo/              # Main application package
│   ├── models/           # SQLAlchemy database models
│   ├── schemas/          # Pydantic schemas for validation
│   ├── services/         # Business logic services
│   ├── repositories/     # Data access layer
│   ├── api/              # API route handlers
│   │   └── v1/           # API version 1 endpoints
│   ├── core/             # Core configuration and utilities
│   └── middleware/       # Custom middleware components
├── tests/                # Test suite
│   ├── contract/         # Contract tests (OpenAPI compliance)
│   ├── integration/      # Integration tests
│   └── unit/             # Unit tests
├── alembic/              # Database migrations
│   └── versions/         # Migration scripts
├── pyproject.toml        # Project dependencies and configuration
└── README.md             # This file
```

## Development Setup

### Prerequisites

- Python 3.11+
- PostgreSQL 15+ with pgvector extension
- Redis 7+

### Installation

```bash
# Install dependencies using uv (recommended)
uv sync

# Or using pip
pip install -e ".[dev]"
```

### Running the Development Server

```bash
# Using uv
uv run uvicorn echoroo.main:app --reload

# Or using uvicorn directly
uvicorn echoroo.main:app --reload --host 0.0.0.0 --port 8000
```

### Database Migrations

```bash
# Create a new migration
uv run alembic revision --autogenerate -m "Description of changes"

# Apply migrations
uv run alembic upgrade head

# Rollback migration
uv run alembic downgrade -1
```

### Browser E2E Fixtures

Seed permission fixtures into a local development database without wiping existing data:

```bash
uv run python -m echoroo.scripts.seed_e2e_permissions --confirm
```

The command writes a JSON payload to stdout with user emails, IDs, password, TOTP secrets, project IDs, site IDs, dataset IDs, recording IDs, clip IDs, detection IDs, annotation IDs, search session IDs, trusted overlay IDs, API keys, and an `env` object containing representative `E2E_*` environment variables. It also creates deterministic WAV fixtures for the seeded recording paths in local object storage, falling back to `AUDIO_ROOT` when object storage is unavailable. Treat this output as sensitive test-only material because it includes active TOTP secrets and raw API keys. Re-running it updates only rows using the selected fixture prefix.

The flat `env` payload includes public and restricted fixture object IDs for browser specs:

- `E2E_PUBLIC_SITE_ID`
- `E2E_PUBLIC_DATASET_ID`
- `E2E_PUBLIC_RECORDING_ID`
- `E2E_PUBLIC_CLIP_ID`
- `E2E_PUBLIC_DETECTION_ID`
- `E2E_PUBLIC_ANNOTATION_ID`
- `E2E_PUBLIC_SEARCH_SESSION_ID`
- `E2E_PUBLIC_EXPORTABLE_SEARCH_SESSION_ID`
- `E2E_RESTRICTED_SITE_ID`
- `E2E_RESTRICTED_DATASET_ID`
- `E2E_RESTRICTED_RECORDING_ID`
- `E2E_RESTRICTED_CLIP_ID`
- `E2E_RESTRICTED_DETECTION_ID`
- `E2E_RESTRICTED_ANNOTATION_ID`
- `E2E_RESTRICTED_SEARCH_SESSION_ID`
- `E2E_RESTRICTED_EXPORTABLE_SEARCH_SESSION_ID`
- `E2E_TRUSTED_LIFECYCLE_USER_ID`
- `E2E_RESTRICTED_TRUSTED_LIFECYCLE_OVERLAY_ID`
- `E2E_RESTRICTED_TRUSTED_EXPIRED_OVERLAY_ID`

To run the seeded permissions matrix spec against a local API, export the `env` payload and enable the suite:

```bash
uv run python -m echoroo.scripts.seed_e2e_permissions --confirm > /tmp/echoroo-e2e-permissions.json
set -a
source <(jq -r '.env | to_entries[] | "\(.key)=\(.value|@sh)"' /tmp/echoroo-e2e-permissions.json)
set +a

cd ../web
E2E_PERMISSIONS_MATRIX_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
npm run test:e2e -- tests/e2e/permissions/seeded-permissions-matrix.spec.ts
```

To run the feature-level permission spec, use the same exported `env` payload and enable its suite:

```bash
E2E_FEATURE_PERMISSIONS_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
npm run test:e2e -- tests/e2e/permissions/seeded-feature-permissions.spec.ts
```

To run the media permission spec, use the latest exported `env` payload and enable its suite:

```bash
E2E_MEDIA_ENABLED=1 \
ECHOROO_API_URL=http://localhost:8002 \
PUBLIC_API_URL=http://localhost:8002 \
npm run test:e2e -- tests/e2e/permissions/seeded-media.spec.ts
```

Use `--prefix` to isolate multiple fixture sets and `--password` to assign a different test password:

```bash
uv run python -m echoroo.scripts.seed_e2e_permissions --confirm --prefix e2e-local --password 'E2E-Test-Password-123!'
```

The seeder refuses staging/production environments and non-local database hosts by default. For CI or development containers with a non-local `DATABASE_URL` host, pass `--allow-non-local-database`; this escape hatch does not override the staging/production environment guard.

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=echoroo --cov-report=html

# Run specific test type
uv run pytest tests/unit/
uv run pytest tests/integration/
uv run pytest tests/contract/
```

### Local Email Verification and Trusted-Device Checks

Use these focused checks when changing email verification, 2FA, or trusted-device behavior. Run commands from `apps/api`.

Keep rollout flags explicit during local testing:

```bash
export EMAIL_VERIFICATION_ENFORCEMENT_ENABLED=false
export TRUSTED_DEVICE_REGISTRATION_ENABLED=false
export TRUSTED_DEVICE_BYPASS_ENABLED=false
```

Email verification token flow:

```bash
uv run pytest tests/integration/api/web_v1/test_auth_verify_email.py
uv run pytest tests/security/authentication/test_email_verification.py
uv run pytest tests/security/rate_limiting/test_email_verification_resend.py
uv run pytest tests/unit/services/test_email_verification_service.py
uv run pytest tests/unit/workers/test_email_verification_dispatcher.py
```

For manual local verification, register through `POST /web-api/v1/auth/register`, confirm the user starts with `email_verified_at IS NULL`, inspect the local mail sink or email outbox event for the verification token, then submit it to `POST /web-api/v1/auth/verify-email`. Reusing the same token should fail, and the database should store only the token hash.

Protected-action enforcement:

```bash
EMAIL_VERIFICATION_ENFORCEMENT_ENABLED=true \
  uv run pytest tests/security/authentication/test_email_verification_required.py
```

Trusted-device registration and cookie behavior:

```bash
uv run pytest tests/integration/api/web_v1/test_auth_trusted_device.py
uv run pytest tests/integration/api/web_v1/test_account_trusted_devices.py
uv run pytest tests/security/authentication/test_trusted_device_cookie.py
uv run pytest tests/unit/services/test_trusted_device_service.py
```

For manual local verification, enable `TRUSTED_DEVICE_REGISTRATION_ENABLED=true`, complete a successful second-factor flow with `trust_device=true`, and confirm the `echoroo_trusted_device` cookie is set with `HttpOnly`, `SameSite=Strict`, and the configured max age. The `trusted_devices` table must contain only `device_secret_hash`, never the raw cookie secret.

Trusted-device login bypass and no-bypass safety:

```bash
TRUSTED_DEVICE_BYPASS_ENABLED=true \
  uv run pytest tests/security/authentication/test_trusted_device_bypass.py
uv run pytest tests/integration/api/web_v1/test_auth_trusted_device_login.py
uv run pytest tests/security/authentication/test_trusted_device_admin_no_bypass.py
uv run pytest tests/security/authentication/test_trusted_device_revocation_events.py
uv run pytest tests/security/authentication/test_trusted_device_high_risk_step_up.py
uv run pytest tests/security/authentication/test_auth_event_redaction_010.py
```

When `TRUSTED_DEVICE_BYPASS_ENABLED=true`, a valid trusted-device cookie for a non-privileged user should return `login_state="complete"` from `POST /web-api/v1/auth/login`. Missing, malformed, revoked, expired, user-mismatched, or admin/superuser trusted-device cookies must still require 2FA or stronger step-up.

## Code Quality

```bash
# Lint with ruff
uv run ruff check .

# Format with ruff
uv run ruff format .

# Type check with mypy
uv run mypy .
```

## API Documentation

Once the server is running, access the interactive API documentation at:

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

## Architecture

This API follows a layered architecture:

1. **API Layer** (`api/`): HTTP request handling and route definitions
2. **Service Layer** (`services/`): Business logic and orchestration
3. **Repository Layer** (`repositories/`): Data access and persistence
4. **Model Layer** (`models/`): Database models and relationships
5. **Schema Layer** (`schemas/`): Request/response validation

## Key Features

- **Authentication**: JWT-based authentication with refresh tokens
- **Rate Limiting**: Redis-backed rate limiting for API endpoints
- **Email Notifications**: Using Resend for transactional emails
- **CAPTCHA Verification**: Server-side CAPTCHA validation
- **Async Support**: Fully async/await for high performance
- **Type Safety**: Strict type checking with mypy and Pydantic
- **Test Coverage**: >80% test coverage requirement

## Environment Variables

See `.env.example` in the project root for required environment variables.

## License

See LICENSE file in the project root.
