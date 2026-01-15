<!--
Sync Impact Report
==================
Version change: NEW (1.0.0)
Modified principles: N/A (initial creation)
Added sections:
  - Core Principles (5 principles)
  - Security Requirements
  - Review Process
  - Governance
Removed sections: N/A
Templates requiring updates:
  - .specify/templates/plan-template.md: ✅ compatible (Constitution Check section exists)
  - .specify/templates/spec-template.md: ✅ compatible (no direct constitution references)
  - .specify/templates/tasks-template.md: ✅ compatible (test-first workflow aligned)
Follow-up TODOs: None
-->

# Echoroo Constitution

## Core Principles

### I. Clean Architecture

Echoroo MUST follow a layered architecture pattern:

- **API Layer**: HTTP handling, request validation, authentication
- **Service Layer**: Business logic, orchestration, transaction management
- **Repository Layer**: Data access abstraction, query encapsulation
- **Domain Models**: Pure business entities, independent of frameworks

Each layer MUST only depend on layers below it. Dependencies MUST be injected,
never instantiated directly. Cross-cutting concerns (logging, auth) MUST be
handled via middleware or decorators.

### II. Test-Driven Development (NON-NEGOTIABLE)

All feature implementations MUST follow TDD:

1. Write failing tests first
2. Implement minimum code to pass tests
3. Refactor while keeping tests green

Test requirements:
- Contract tests MUST exist for all API endpoints
- Integration tests MUST cover service layer interactions
- Unit tests SHOULD cover complex business logic
- Tests MUST fail before implementation begins

No pull request will be merged without corresponding tests.

### III. Type Safety

Both frontend and backend MUST maintain strict type safety:

- **Backend**: Pydantic schemas for all request/response validation,
  SQLAlchemy 2.0 type hints for all models, mypy MUST pass with strict mode
- **Frontend**: TypeScript strict mode enabled, no `any` types except in
  exceptional documented cases, API responses MUST be typed via generated
  OpenAPI types

Runtime type validation is required at system boundaries (API inputs,
external service responses).

### IV. ML Pipeline Architecture

Machine learning operations MUST be handled through the task queue:

- Species detection runs → Celery task
- Embedding generation → Celery task
- Model training → Celery task
- Batch inference → Celery task

Heavy ML operations MUST NOT block the API server. Progress updates MUST be
provided via WebSocket for long-running tasks. GPU resources MUST be managed
to prevent memory exhaustion.

### V. API Versioning

All API endpoints MUST follow versioning conventions:

- Format: `/api/v{major}/...` (e.g., `/api/v1/recordings`)
- Breaking changes MUST increment major version
- New endpoints MUST be added to current version first
- Deprecated endpoints MUST be documented with sunset timeline
- Backward compatibility MUST be maintained within major version

## Security Requirements

Echoroo MUST adhere to secure development practices:

### Authentication & Authorization
- All authenticated endpoints MUST validate JWT tokens
- Role-based access control MUST be enforced at service layer
- Session tokens MUST expire within configurable timeout
- Password storage MUST use bcrypt or argon2

### Input Validation
- All user inputs MUST be validated via Pydantic schemas
- File uploads MUST be validated for type and size
- SQL injection prevention via parameterized queries (SQLAlchemy)
- XSS prevention via proper output encoding

### Data Protection
- Sensitive data MUST NOT be logged
- Database credentials MUST be stored in environment variables
- API keys MUST NOT be committed to repository
- HTTPS MUST be enforced in production

### OWASP Compliance
- Regular dependency updates for security patches
- Security headers MUST be configured (CORS, CSP, etc.)
- Rate limiting MUST be implemented for public endpoints

## Review Process

All code changes MUST follow this review workflow:

### Pull Request Requirements
- PRs MUST target the main branch from feature branches
- PRs MUST pass all CI checks before review
- PRs MUST have at least one approval before merge
- PRs MUST include tests for new functionality

### Code Quality Gates
- Linting MUST pass (ruff for Python, ESLint for TypeScript)
- Type checking MUST pass (mypy, tsc)
- Test coverage MUST NOT decrease
- No unresolved TODO items in new code

### Review Checklist
- Architecture alignment with constitution principles
- Security considerations addressed
- Performance impact evaluated for data-heavy operations
- API changes are backward compatible

### Merge Strategy
- Squash merge for feature branches
- Conventional commit messages required
- Branch deletion after successful merge

## Governance

This constitution represents the foundational principles for Echoroo
development. All contributors, code reviews, and architectural decisions
MUST verify compliance with these principles.

### Amendment Process
1. Propose changes via pull request to this document
2. Justify the need for amendment with rationale
3. Impact analysis on existing codebase required
4. Migration plan for breaking changes
5. Approval from project maintainers required

### Version Policy
- MAJOR: Principle removal or incompatible redefinition
- MINOR: New principle added or materially expanded guidance
- PATCH: Clarifications, wording improvements

### Compliance
- All PRs MUST pass constitution check in plan phase
- Violations MUST be documented with justification
- Regular audits against constitution principles recommended

**Version**: 1.0.0 | **Ratified**: 2026-01-15 | **Last Amended**: 2026-01-15
