# Quickstart Guide: System Administration

**Date**: 2026-01-16 | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## Overview

This guide provides quick reference for implementing the System Administration feature. Follow the TDD approach outlined in the constitution.

## Prerequisites

- Docker and Docker Compose installed
- Node.js 20+ (for frontend)
- Python 3.11+ with uv (for backend)
- PostgreSQL 16 with pgvector extension

## Development Setup

### Start Development Environment

```bash
# Start all services
./scripts/docker.sh dev

# Or restart specific services
./scripts/docker.sh dev restart api
./scripts/docker.sh dev restart web
```

### Backend Setup (apps/api)

```bash
cd apps/api

# Install dependencies
uv sync

# Run migrations
uv run alembic upgrade head

# Start development server
uv run uvicorn echoroo.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend Setup (apps/web)

```bash
cd apps/web

# Install dependencies
npm install

# Start development server
npm run dev
```

## Implementation Order

### Phase 1: Core Backend

1. **Models** (if not already done)
   - `Recorder` model
   - `License` model
   - Add to `models/__init__.py`

2. **Repositories**
   - `UserRepository`
   - `ProjectRepository`
   - `RecorderRepository`
   - `LicenseRepository`
   - `SystemSettingRepository`

3. **Services**
   - `AuthService` (login, register, tokens)
   - `UserService` (CRUD, profile)
   - `ProjectService` (CRUD, members)
   - `RecorderService` (CRUD)
   - `LicenseService` (CRUD)
   - `SettingsService` (system config)

4. **API Routes**
   - `auth.py` - Authentication endpoints
   - `users.py` - User management
   - `projects.py` - Project management
   - `admin.py` - Admin panel (recorders, licenses, settings)
   - `setup.py` - Initial setup wizard

### Phase 2: Core Frontend

1. **Auth Flow**
   - Login page
   - Register page (conditional)
   - Password reset flow
   - Auth store (Svelte)

2. **Dashboard**
   - Project list
   - Quick actions

3. **Projects**
   - Project list/detail
   - Create/edit project
   - Member management

4. **Admin Panel**
   - User management
   - System settings
   - Recorder management
   - License management

5. **Profile**
   - View/edit profile
   - Change password
   - API tokens

### Phase 3: Setup Wizard

1. **Backend** - Setup status and completion endpoints
2. **Frontend** - Setup wizard UI

## Key Files to Create/Modify

### Backend

```
apps/api/echoroo/
├── models/
│   ├── recorder.py      # NEW
│   └── license.py       # NEW
├── schemas/
│   ├── auth.py          # NEW
│   ├── user.py          # NEW
│   ├── project.py       # NEW
│   ├── recorder.py      # NEW
│   ├── license.py       # NEW
│   └── settings.py      # NEW
├── repositories/
│   ├── user.py          # NEW
│   ├── project.py       # NEW
│   ├── recorder.py      # NEW
│   ├── license.py       # NEW
│   └── settings.py      # NEW
├── services/
│   ├── auth.py          # NEW
│   ├── user.py          # NEW
│   ├── project.py       # NEW
│   ├── recorder.py      # NEW
│   ├── license.py       # NEW
│   └── settings.py      # NEW
├── api/v1/
│   ├── auth.py          # NEW
│   ├── users.py         # NEW
│   ├── projects.py      # NEW
│   ├── admin.py         # NEW
│   └── setup.py         # NEW
└── middleware/
    ├── auth.py          # NEW (JWT validation)
    └── rate_limit.py    # NEW (Redis-based)
```

### Frontend

```
apps/web/src/
├── routes/
│   ├── (auth)/
│   │   ├── login/+page.svelte
│   │   ├── register/+page.svelte
│   │   └── reset-password/+page.svelte
│   ├── (app)/
│   │   ├── +layout.svelte          # Auth guard
│   │   ├── dashboard/+page.svelte
│   │   ├── projects/
│   │   │   ├── +page.svelte        # List
│   │   │   ├── new/+page.svelte    # Create
│   │   │   └── [id]/+page.svelte   # Detail
│   │   ├── profile/+page.svelte
│   │   └── admin/
│   │       ├── +page.svelte        # Dashboard
│   │       ├── users/+page.svelte
│   │       ├── settings/+page.svelte
│   │       ├── recorders/+page.svelte
│   │       └── licenses/+page.svelte
│   └── setup/+page.svelte
├── lib/
│   ├── api/
│   │   ├── client.ts              # Fetch wrapper
│   │   └── queries/               # TanStack Query hooks
│   ├── components/
│   │   ├── forms/
│   │   └── layout/
│   └── stores/
│       └── auth.ts                # Auth state
└── app.d.ts                       # Global types
```

## Testing

### Backend Tests

```bash
cd apps/api

# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/contract/test_auth.py

# Run with coverage
uv run pytest --cov=echoroo
```

### Frontend Tests

```bash
cd apps/web

# Run unit tests
npm run test

# Run e2e tests
npm run test:e2e
```

## Type Checking

```bash
# Backend
cd apps/api && uv run mypy .

# Frontend
cd apps/web && npm run check
```

## API Documentation

After starting the backend, API docs are available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Common Tasks

### Add New Recorder (Seed Data)

```python
# In migration file
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.execute("""
        INSERT INTO recorders (id, manufacturer, recorder_name, version, created_at, updated_at)
        VALUES ('new_id', 'Manufacturer', 'Model Name', NULL, NOW(), NOW())
    """)
```

### Add New License (Seed Data)

```python
# In migration file
def upgrade():
    op.execute("""
        INSERT INTO licenses (id, name, short_name, url, created_at, updated_at)
        VALUES ('NEW-ID', 'Full License Name', 'Short Name', 'https://...', NOW(), NOW())
    """)
```

## Troubleshooting

### Database Connection Issues

```bash
# Check PostgreSQL logs
docker logs echoroo-db --tail 100

# Reset database
docker compose down -v
./scripts/docker.sh dev
```

### JWT Token Issues

- Check `JWT_SECRET` environment variable
- Verify cookie settings (SameSite, Secure flags)
- Clear browser cookies and retry

### Rate Limiting Issues

- Check Redis connection
- Verify rate limit settings in `SystemSetting` table
- Use `/api/v1/admin/settings` to adjust limits

## References

- [Spec](./spec.md) - Feature specification
- [Plan](./plan.md) - Implementation plan
- [Research](./research.md) - Technical decisions
- [Data Model](./data-model.md) - Database schema
- [API Contracts](./contracts/) - OpenAPI specs
