# Test Inventory — Email Verification and Trusted Devices

**Date**: 2026-05-18
**Feature**: 010 Email Verification and Trusted Devices
**Purpose**: Record current auth assumptions that must be updated or guarded while implementing this feature.

## Current Behaviors To Replace

| Area | Current file(s) | Current assumption | Follow-up task |
|------|-----------------|--------------------|----------------|
| BFF verify-email route | `apps/api/tests/integration/api/web_v1/test_auth_verify_email.py` | `/web-api/v1/auth/verify-email` exists but reaches `AuthService.verify_email()` stub and expects 501 behavior for well-formed tokens. | T018, T026, T027 |
| Legacy verify-email model | `apps/api/tests/contract/test_auth.py`, `apps/api/tests/integration/test_auth_flow.py` | Skipped/stale coverage still references dropped `is_verified`, `email_verification_token`, and `email_verification_expires_at` user columns. | T005, T008, T018, T019 |
| Register/login state | `apps/api/tests/integration/api/web_v1/test_auth.py`, `apps/api/tests/unit/api/web_v1/test_auth_coverage_uplift.py` | Password login with correct credentials always returns `2fa_required` or `2fa_setup_required`; no complete trusted-device login branch exists. | T067, T068, T072, T074 |
| Frontend verify page | `apps/web/src/routes/(auth)/verify-email/+page.svelte`, `apps/web/tests/e2e/auth.spec.ts` | Verify and resend UI exists, but resend calls a BFF route that is documented as currently missing. | T022, T030, T035, T042 |
| Frontend user verification type | `apps/web/src/lib/types/index.ts`, dashboard/profile/admin user views | `User.is_verified` is the UI source of truth. | T004, T036, T039, T046, T047 |
| Programmatic/BFF separation | `apps/api/tests/contract/test_auth_separation.py`, `apps/api/tests/integration/middleware/test_two_factor_enforcement.py`, `apps/api/tests/integration/middleware/test_two_factor_enforcement_real_chain.py` | `/api/v1/*` remains API-key/programmatic and must not inherit first-party email/trusted-device behavior. | T008, T016, T102 |
| Two-factor enforcement inventory | `apps/api/tests/integration/middleware/test_two_factor_enforcement.py` | Existing protected-path style can seed the email-verification protected-action inventory. | T034, T043, T044 |
| Email provider wrapper | `apps/api/tests/unit/services/test_email.py`, `apps/api/tests/unit/services/test_email_service_coverage_uplift.py` | Direct Resend wrappers exist; registration must instead enqueue verification email through outbox. | T021, T028, T029, T094, T095 |

## Existing Tests That Should Continue Passing

- Programmatic `/api/v1/*` auth-router and API-key separation tests.
- Existing TOTP setup/challenge tests for unknown or untrusted devices.
- Existing WebAuthn/admin step-up tests and middleware tests.
- Existing password reset and 2FA reset tests, with added trusted-device revocation assertions.

## New Focused Coverage Required

- Migration/schema coverage for `users.email_verified_at`, `email_verification_tokens`, and `trusted_devices`.
- HMAC-only token/device secret storage and fixed 43-character base64url secret generation.
- Atomic email-token consume, expiry, reuse, supersession, tampering, and concurrent-submit behavior.
- Resend abuse controls with generic 202 anti-enumeration responses.
- Trusted-device issue/list/revoke, cookie attributes, hash-only storage, five-device cap, and absolute expiry.
- Trusted-device bypass fallback reasons: missing, malformed, revoked, expired, user mismatch, security-stamp mismatch, recent failures, privileged/admin contexts.
- Audit/log redaction for raw tokens, full verification URLs, trusted-device secrets, raw IP addresses, and raw User-Agent strings.

## Verification Gates

Phase-specific test tasks in `tasks.md` are the authoritative gates. Do not mark a user-story phase complete until its run task passes or the blocker is documented in the task notes.
