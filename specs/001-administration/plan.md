# Implementation Plan: System Administration

**Branch**: `001-administration` | **Date**: 2026-01-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-administration/spec.md`

## Summary

This plan covers the implementation of the core system administration features for Echoroo v2, including user authentication, project management, role-based access control, system settings, and master data management (recorders and licenses). The implementation follows a TDD approach with FastAPI backend and SvelteKit frontend, using JWT-based authentication and PostgreSQL storage.

## Technical Context

**Language/Version**: Python 3.11 (Backend), TypeScript 5.x (Frontend)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0, Pydantic, SvelteKit, Svelte 5, TanStack Query, Tailwind CSS
**Storage**: PostgreSQL with pgvector extension
**Testing**: pytest (backend), vitest (frontend), Playwright (e2e)
**Target Platform**: Linux server (Docker), Modern browsers
**Project Type**: Web application (frontend + backend)
**Performance Goals**: Login < 1s, List views < 1s, 100 concurrent users
**Constraints**: Session timeout configurable (default 2h), Rate limiting required
**Scale/Scope**: Initial deployment ~100 users, ~50 projects

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Clean Architecture ✅ PASS
- **API Layer**: FastAPI routers in `apps/api/echoroo/api/v1/`
- **Service Layer**: Business logic in `apps/api/echoroo/services/`
- **Repository Layer**: Data access in `apps/api/echoroo/repositories/`
- **Domain Models**: SQLAlchemy models in `apps/api/echoroo/models/`
- Dependency injection via FastAPI's `Depends()`

### II. Test-Driven Development ✅ PASS
- Contract tests for all API endpoints (pytest)
- Integration tests for service layer
- Unit tests for complex business logic
- Frontend component tests (vitest)
- E2E tests (Playwright)

### III. Type Safety ✅ PASS
- **Backend**: Pydantic schemas for request/response, SQLAlchemy 2.0 mapped_column types, mypy strict mode
- **Frontend**: TypeScript strict mode, OpenAPI-generated types, no `any` types

### IV. ML Pipeline Architecture ⬜ N/A
- This feature does not involve ML operations

### V. API Versioning ✅ PASS
- All endpoints under `/api/v1/`
- Breaking changes require version increment
- Backward compatibility within major version

### Security Requirements ✅ PASS
- JWT token validation for authenticated endpoints
- Role-based access control at service layer
- Configurable session timeout (FR-004)
- Password hashing with bcrypt (FR-005)
- Pydantic validation for all inputs
- Rate limiting for login endpoint (FR-005b, FR-005c)

## Project Structure

### Documentation (this feature)

```text
specs/001-administration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (OpenAPI specs)
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
apps/api/                           # FastAPI backend
├── echoroo/
│   ├── api/v1/                     # API routers
│   │   ├── auth.py                 # Authentication endpoints
│   │   ├── users.py                # User management endpoints
│   │   ├── projects.py             # Project management endpoints
│   │   ├── admin.py                # Admin panel endpoints
│   │   ├── setup.py                # Initial setup endpoints
│   │   ├── recorders.py            # Recorder CRUD (NEW)
│   │   └── licenses.py             # License CRUD (NEW)
│   ├── models/                     # SQLAlchemy models
│   │   ├── user.py                 # User, APIToken, LoginAttempt
│   │   ├── project.py              # Project, ProjectMember, ProjectInvitation
│   │   ├── system.py               # SystemSetting
│   │   ├── recorder.py             # Recorder (NEW)
│   │   └── license.py              # License (NEW)
│   ├── schemas/                    # Pydantic schemas
│   ├── services/                   # Business logic
│   ├── repositories/               # Data access layer
│   ├── core/                       # Configuration, security, exceptions
│   └── middleware/                 # Auth, rate limiting, logging
├── tests/
│   ├── contract/                   # API contract tests
│   ├── integration/                # Service integration tests
│   └── unit/                       # Unit tests
└── alembic/                        # Database migrations

apps/web/                           # SvelteKit frontend
├── src/
│   ├── routes/                     # SvelteKit routes/pages
│   │   ├── (auth)/                 # Auth pages (login, register, reset)
│   │   ├── (app)/                  # Authenticated app pages
│   │   │   ├── dashboard/          # User dashboard
│   │   │   ├── projects/           # Project management
│   │   │   ├── profile/            # User profile
│   │   │   └── admin/              # Admin panel (superuser only)
│   │   └── setup/                  # Initial setup wizard
│   ├── lib/
│   │   ├── api/                    # API client, TanStack Query hooks
│   │   ├── components/             # Reusable UI components
│   │   ├── stores/                 # Svelte stores (auth state)
│   │   └── types/                  # TypeScript types (generated)
│   └── app.html
├── tests/
│   ├── unit/                       # Component unit tests
│   └── e2e/                        # Playwright e2e tests
└── static/
```

**Structure Decision**: Web application structure with separate `apps/api` (FastAPI backend) and `apps/web` (SvelteKit frontend). This aligns with the existing repository structure and allows parallel development of backend and frontend.

## Complexity Tracking

> No violations requiring justification. Architecture follows constitution principles.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| None | - | - |
