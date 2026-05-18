# Implementation Plan: Email Verification and Trusted Devices

**Branch**: `010-email-verification-trusted-devices` | **Date**: 2026-05-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/010-email-verification-trusted-devices/spec.md`

## Summary

Implement real email-address verification and a revocable trusted-device mechanism for the first-party browser auth surface. The work keeps the existing TOTP/WebAuthn security posture for unknown devices, superusers, and high-risk operations, but lets non-privileged users skip routine TOTP on browsers that were explicitly trusted after a successful 2FA event.

The technical approach is intentionally layered:

1. Add canonical email verification state and token persistence.
2. Replace the current `/web-api/v1/auth/verify-email` stub with a real service path and resend flow.
3. Add an email-verification enforcement guard for protected actions.
4. Add trusted-device persistence, device-cookie issuance after successful 2FA, self-service listing/revocation, and login recognition.
5. Keep rollout flags around email enforcement, trusted-device registration, and trusted-device 2FA bypass so the auth posture can be staged safely.

## Technical Context

**Language/Version**: Python 3.11 (FastAPI backend), TypeScript 5.x (SvelteKit 2 / Svelte 5 frontend)  
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, Redis, transactional outbox + registered worker email dispatch, pyotp/WebAuthn, SvelteKit, TanStack Query, Playwright  
**Storage**: PostgreSQL 16+ for users/tokens/trusted devices; Redis for rate limits and replay/lockout counters; secure browser cookies for first-party session and trusted-device secrets  
**Testing**: pytest + pytest-asyncio (unit, integration, security), OpenAPI contract tests, Vitest, Playwright E2E  
**Target Platform**: Linux server in Docker; modern browsers using the first-party `/web-api/v1/*` BFF surface  
**Project Type**: Web monorepo (`apps/api`, `apps/web`)  
**Performance Goals**: Login and verification paths remain bounded by existing auth latency; trusted-device lookup is one indexed database query after password verification; no additional DB query on unrelated authenticated requests except email-verification enforcement on protected actions.  
**Constraints**: No raw verification tokens, full verification URLs, trusted-device secrets, raw IPs, or raw user-agent strings in persistent storage or audit logs. `/api/v1/*` programmatic auth remains unchanged. Superuser WebAuthn and destructive step-up remain authoritative.  
**Scale/Scope**: Three new/changed persistence areas (`users.email_verified_at`, email-verification token table, trusted-device table), auth router/service changes, account security UI, protected-action enforcement, integration/security/E2E coverage, and a test-inventory pass for existing "password login always returns 2FA state" assumptions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Compliance | Evidence |
|-----------|------------|----------|
| **I. Clean Architecture** | Pass | HTTP handlers remain thin. Email verification and trusted-device logic land in services/repositories, with route handlers delegating to those services. Enforcement is middleware/dependency based rather than duplicated per route. |
| **II. TDD (NON-NEGOTIABLE)** | Pass | Every phase starts with failing contract/integration/security tests: verify-email token success/failure, unverified protected-action 403, trusted-device create/revoke, trusted-device login bypass, and admin/high-risk no-bypass. |
| **III. Type Safety** | Pass | New request/response surfaces use Pydantic v2 schemas and SQLAlchemy typed models; frontend state/types are updated through explicit TypeScript interfaces and no untyped `any` additions. |
| **IV. ML Pipeline Architecture** | Not applicable | Auth/account work does not touch ML/Celery detection pipelines. Email dispatch can reuse existing outbox/worker patterns but is not an ML workload. |
| **V. API Versioning** | Pass (with established BFF note) | Browser-facing changes are additive under `/web-api/v1/*`; existing `/api/v1/*` API-key behavior is unchanged. The `/web-api/v1` prefix is the versioned first-party BFF surface established by spec/006 and reused by spec/009 to preserve actor/audit/rate-limit isolation from the programmatic `/api/v1` API-key surface. This feature does not introduce a new unversioned API namespace. |
| **Security: Auth & RBAC** | Pass | Trusted devices only skip routine TOTP after password verification and only for non-privileged users. Unknown devices, revoked devices, high-risk actions, and admin/superuser flows still require 2FA/WebAuthn/step-up. |
| **Security: Input Validation** | Pass | Email normalization follows existing auth router patterns (`email_validator`, NFKC, control-character rejection). Tokens are opaque, length-checked, purpose-scoped, and stored hashed. |
| **Security: Data Protection** | Pass | Token and device secrets are write-only to the client and hash-only server-side. Audit details use hashes/redaction for email/IP/UA data. |
| **Security: OWASP / CSRF / Rate Limit** | Pass | Public auth endpoints remain rate-limited and anti-enumeration safe. Account security mutations and trusted-device revocation remain CSRF protected on the BFF surface. |

**Result**: PASS. No Complexity Tracking entries required.

## Project Structure

### Documentation (this feature)

```text
specs/010-email-verification-trusted-devices/
├── spec.md              # Feature specification
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 decisions
├── data-model.md        # Phase 1 entity/state design
├── quickstart.md        # Phase 1 verification recipe
├── contracts/
│   ├── auth.yaml        # Auth contract deltas
│   └── trusted-devices.yaml
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
apps/api/echoroo/
├── api/
│   └── web_v1/
│       ├── auth.py                      # register, verify-email, resend, login, 2FA trust_device handling
│       └── account_trusted_devices.py   # user self-service trusted-device list/revoke (new or account package)
├── core/
│   ├── settings.py                      # rollout flags, cookie names, TTLs, rate-limit settings
│   └── auth_paths.py                    # public auth path allowlist adds verify-email/resend exact paths
├── middleware/
│   └── email_verification_enforcement.py # protected-action guard (new)
├── models/
│   ├── user.py                          # email_verified_at
│   ├── email_verification_token.py      # new
│   └── trusted_device.py                # new
├── repositories/
│   ├── email_verification_token.py      # new
│   └── trusted_device.py                # new
├── schemas/
│   └── web_v1/
│       ├── auth.py                      # verify/resend/trust_device/login response updates
│       └── trusted_device.py            # list/revoke response schemas
├── services/
│   ├── email_verification_service.py    # token issue/consume/resend
│   ├── trusted_device_service.py        # issue/verify/revoke/risk decision
│   ├── auth.py                          # legacy verify_email stub removed or delegated
│   └── auth_service.py                  # existing password auth unchanged
└── workers/
    └── email dispatch/outbox integration # add registered verification-email handler, avoid dead-letter events

apps/api/alembic/versions/
└── 00xx_email_verification_trusted_devices.py

apps/api/tests/
├── integration/api/web_v1/
│   ├── test_auth_verify_email.py
│   ├── test_auth_trusted_device.py
│   └── test_account_trusted_devices.py
├── security/authentication/
│   ├── test_email_verification.py
│   └── test_trusted_device_bypass.py
└── unit/services/
    ├── test_email_verification_service.py
    └── test_trusted_device_service.py

apps/web/src/
├── lib/api/
│   ├── auth.ts                          # verify/resend/login complete/trust_device response handling
│   └── trusted-devices.ts               # account security API client
├── lib/stores/auth.svelte.ts            # email_verified_at + trusted-device login state
└── routes/
    ├── (auth)/verify-email/+page.svelte
    ├── (auth)/login/+page.svelte        # trust-device checkbox and complete state
    ├── (auth)/2fa-setup/+page.svelte    # trust-device checkbox after setup
    └── (app)/profile/+page.svelte       # account security/trusted devices section or linked subview
```

**Structure Decision**: Use the existing monorepo layout. Add small backend services/repositories and BFF routes; do not add a new auth subsystem or top-level package. Keep contracts and planning artifacts under `specs/010-email-verification-trusted-devices/`.

## Delivery Sequence

| Phase | Scope | Backend | Frontend | Primary Tests |
|-------|-------|---------|----------|---------------|
| **0** | Test and contract inventory | Inventory existing login/verify-email tests that assume 501 stubs, old `is_verified`, or password-login-always-2FA; decide exact spec/006 contract reconciliation edits | None | inventory notes, no code behavior change |
| **A** | Email verification persistence | `users.email_verified_at`, `email_verification_tokens`, service/repository, real verify endpoint; update existing BFF verify-email tests away from 501 stub; merge contract deltas into canonical contract set used by OpenAPI diff tests | Existing verify page wired to real outcomes | unit + integration token success/failure/reuse/expiry/concurrent consume |
| **B** | Registration/resend/email state | enqueue verification email on register via transactional outbox, registered worker handler, resend with anti-enumeration/rate limit, current-user state | unverified account state + resend UI, frontend `User` type moves from old `is_verified` assumptions to `email_verified_at` | integration + frontend unit |
| **C** | Email enforcement | protected-action middleware/dependency, rollout flag | UI messaging for blocked actions | security tests for `ERR_EMAIL_VERIFICATION_REQUIRED` |
| **D** | Trusted-device persistence/revoke | `trusted_devices`, service/repository, account list/revoke endpoints | account security trusted devices list | unit + integration + CSRF |
| **E** | Trust device after 2FA | `trust_device` request fields, secure cookie issuance after 2FA/setup confirm | checkbox on login 2FA/setup flows | integration cookie/security assertions |
| **F** | Trusted-device login bypass | login recognizes valid device after password verification, non-privileged only, enumerated risk/admin guards, no user mismatch | login handles `complete` state | integration + Playwright same-browser and new-browser flows |
| **G** | Hardening/rollout | revocation hooks, three kill switches, audit/log redaction, delivery readiness docs, bounce/dead-letter alerting Go/No-Go | final copy polish | security regression and E2E smoke |

## Complexity Tracking

No constitution violations. Section intentionally left empty.
