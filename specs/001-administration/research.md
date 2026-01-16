# Research: System Administration

**Date**: 2026-01-16 | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

## Executive Summary

This document captures technical decisions and research findings for the System Administration feature of Echoroo v2. The implementation follows a clean architecture pattern with FastAPI backend and SvelteKit frontend, using JWT-based authentication stored in HTTP-only cookies.

## Technical Decisions

### TD-001: Authentication Token Strategy

**Decision**: JWT tokens stored in HTTP-only cookies with CSRF protection

**Options Considered**:
1. JWT in HTTP-only cookies (selected)
2. JWT in localStorage with Authorization header
3. Session-based authentication with server-side storage

**Rationale**:
- HTTP-only cookies prevent XSS attacks from accessing tokens
- CSRF protection via SameSite=Strict and optional CSRF tokens
- Stateless verification reduces database load
- Refresh token pattern enables secure long-lived sessions

**Implementation**:
- Access token: 15-minute expiry, stored in HTTP-only cookie
- Refresh token: 7-day expiry, stored in HTTP-only cookie with `/api/v1/auth/refresh` path
- CSRF: SameSite=Strict cookie attribute

### TD-002: Password Security

**Decision**: bcrypt with cost factor 12

**Options Considered**:
1. bcrypt (selected)
2. Argon2id
3. PBKDF2

**Rationale**:
- bcrypt is well-tested and widely supported
- Cost factor 12 provides ~250ms hash time, balancing security and UX
- passlib library provides secure implementation
- Argon2id considered but bcrypt has broader library support

**Implementation**:
```python
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

### TD-003: Rate Limiting Strategy

**Decision**: Redis-based sliding window rate limiting

**Options Considered**:
1. Redis sliding window (selected)
2. In-memory token bucket
3. Fixed window with Redis

**Rationale**:
- Sliding window prevents burst attacks at window boundaries
- Redis enables distributed rate limiting across multiple API instances
- Configurable limits per endpoint and per user

**Implementation**:
- Login endpoint: 5 attempts per 15 minutes per IP
- After 5 failed attempts: 15-minute lockout per email
- General API: 100 requests per minute per authenticated user

### TD-004: Email Verification Strategy

**Decision**: Deferred - not required for MVP

**Rationale**:
- Spec FR-001 does not explicitly require email verification
- Initial deployment is internal (~100 users)
- Can be added in future iteration if needed

**Implementation**: None for v1

### TD-005: Project Role Hierarchy

**Decision**: Three-tier role system (Admin/Member/Viewer)

**Options Considered**:
1. Three roles: Admin/Member/Viewer (selected)
2. Two roles: Manager/Member (old implementation)
3. Custom permission-based system

**Rationale**:
- Clear separation of responsibilities
- Viewer role enables read-only access for stakeholders
- Simpler than custom permissions while meeting requirements
- Aligned with user clarification session (2026-01-16)

**Implementation**:
```python
class ProjectRole(str, Enum):
    ADMIN = "admin"      # Full project management
    MEMBER = "member"    # Read/write access
    VIEWER = "viewer"    # Read-only access
```

### TD-006: Master Data Management Strategy

**Decision**: Database-stored with seed data migration

**Options Considered**:
1. Database with seed migration (selected)
2. Hardcoded enums
3. External configuration file

**Rationale**:
- Allows admin modification without code changes
- Seed data provides sensible defaults
- Migration ensures consistent initial state
- Matches existing pattern in old/ implementation

**Implementation**:
- Recorder seed data: AudioMoth, Song Meter series (Micro2, Mini2, SM4, SM5)
- License seed data: Xeno-canto compatible (BY-NC-ND, BY-NC-SA, BY-SA)

### TD-007: CAPTCHA for Registration

**Decision**: Not implemented for MVP

**Rationale**:
- Internal deployment with limited user base
- Rate limiting provides basic protection
- Can be added if spam becomes an issue

### TD-008: Initial Setup Wizard

**Decision**: One-time setup endpoint with system setting flag

**Implementation**:
- `GET /api/v1/setup/status` - Returns whether setup is complete
- `POST /api/v1/setup/complete` - Creates superuser and marks setup complete
- `SystemSetting(key="setup_completed", value="true")` prevents re-running

### TD-009: Frontend State Management

**Decision**: TanStack Query for server state, Svelte stores for auth state

**Rationale**:
- TanStack Query handles caching, revalidation, and loading states
- Svelte stores provide reactive auth state across components
- Minimal client-side state reduces complexity

**Implementation**:
```typescript
// Auth store (reactive)
export const authStore = writable<AuthState>({ user: null, isLoading: true });

// Server state (TanStack Query)
const projects = createQuery({ queryKey: ['projects'], queryFn: fetchProjects });
```

### TD-010: API Contract Generation

**Decision**: OpenAPI 3.1 specs with TypeScript type generation

**Implementation**:
- FastAPI auto-generates OpenAPI schema at `/api/v1/openapi.json`
- `openapi-typescript` generates TypeScript types for frontend
- Contract tests validate implementation matches spec

## Existing Implementation Analysis

### Current State (apps/api/echoroo/)

**Implemented**:
- Base model with UUID and timestamp mixins
- User, APIToken, LoginAttempt models
- Project, ProjectMember, ProjectInvitation models
- SystemSetting model
- Enum definitions (ProjectRole, ProjectVisibility, SettingType)

**Not Implemented**:
- Recorder model
- License model
- API routers
- Service layer
- Repository layer
- Authentication middleware

### Migration from old/ Implementation

**Patterns to Preserve**:
- Recorder seed data structure
- JWT token validation logic
- Password hashing approach

**Patterns to Improve**:
- Three-tier role system (was two-tier)
- Clean architecture separation (was mixed)
- Type safety with Pydantic v2

## Security Considerations

### Authentication
- JWT tokens with short expiry (15 min)
- Refresh token rotation on use
- Secure cookie attributes (HttpOnly, Secure, SameSite)

### Rate Limiting
- Per-IP and per-email tracking for login
- Sliding window algorithm
- Redis for distributed state

### Input Validation
- Pydantic schemas for all API inputs
- Email format validation
- Password strength requirements (8+ chars, mixed case, numbers)

### Session Management
- Configurable session timeout (default 2h, FR-004)
- Token revocation on logout
- Force logout capability for superusers

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Login | < 1s | Including bcrypt hash |
| Project list | < 1s | Paginated, 20 items |
| User list | < 1s | Paginated, 20 items |
| Token validation | < 50ms | JWT verify only |

## Open Questions (Resolved)

1. ~~Role hierarchy~~ → Resolved: 3 roles (Admin/Member/Viewer)
2. ~~Email verification~~ → Deferred to future iteration
3. ~~CAPTCHA~~ → Not needed for MVP

## References

- [Spec](./spec.md) - Feature specification
- [Constitution](../../.specify/memory/constitution.md) - Project principles
- [Old Implementation](../../old/) - Reference for patterns
