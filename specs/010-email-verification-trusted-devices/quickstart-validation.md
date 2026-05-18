# Quickstart Validation - Email Verification and Trusted Devices

**Date**: 2026-05-18
**Scope**: Phase 8 validation for `quickstart.md`

This file records the automated quickstart validation completed for the email verification and trusted-device feature. Manual mail-sink/browser inspection items remain noted separately because the Playwright E2E spec is currently environment-gated and skipped in this workspace.

## Result Summary

| Area | Status | Evidence |
| --- | --- | --- |
| Email verification token flow | Passed | Backend focused suite: 16 passed. |
| Unverified protected-action enforcement | Passed | Covered by `test_email_verification.py` in the backend focused suite. |
| Trusted-device issuance/list/revoke | Passed | Earlier US3 focused suite passed; README/runbook validation now points to the exact commands. |
| Trusted-device login bypass | Passed | US4 backend/frontend focused suites passed; Playwright spec was invoked and skipped by test preconditions. |
| Admin/high-risk no-bypass | Passed | US5 security suite: 15 passed. Admin step-up: 19 passed. WebAuthn: 11 passed. |
| Phase 8 backend focused suite | Passed | T098 command: 16 passed. |
| Phase 8 frontend focused suite | Passed with skipped E2E | Vitest: 7 passed. Playwright trusted-device spec: 2 skipped. |
| Phase 8 contract and migration checks | Passed | T100 command: 24 passed. |
| API-key/programmatic auth regression | Passed with known skip | T102 command: 7 passed, 1 skipped for an existing asyncpg teardown race. |
| Full manual browser quickstart | Not run | Manual mail-sink/browser inspection remains a rollout smoke item. |

## Commands and Results

### Foundational checks

```bash
cd apps/api
uv run pytest tests/integration/migrations/test_email_verification_trusted_devices_schema.py
uv run pytest tests/unit/services/test_account_security_token_hashing.py
uv run pytest tests/unit/core/test_auth_settings_010.py
uv run pytest tests/contract/test_auth_010_contract.py
```

Result: previously recorded as complete by T017.

### Email verification token flow

```bash
cd apps/api
uv run pytest tests/integration/api/web_v1/test_auth_verify_email.py
uv run pytest tests/security/authentication/test_email_verification.py
```

Result: covered again by the Phase 8 backend focused suite: 16 passed.

### Verify-email frontend state coverage

```bash
cd apps/web
npm run test -- src/routes/\(auth\)/verify-email/verify-email.spec.ts
```

Result: covered again by the Phase 8 frontend focused suite: 7 Vitest tests passed across verify-email and login trusted-device specs.

### Unverified protected-action enforcement and resend

```bash
cd apps/api
uv run pytest tests/security/authentication/test_email_verification_required.py
uv run pytest tests/security/rate_limiting/test_email_verification_resend.py
```

Result: previously recorded as complete by T048; `test_email_verification.py` was also included in the Phase 8 backend focused suite.

### Frontend email verification auth-store coverage

```bash
cd apps/web
npm run test -- src/lib/stores/auth.email-verification.test.ts
```

Result: previously recorded as complete by T048.

### Trusted-device issuance, list, revoke, and service behavior

```bash
cd apps/api
uv run pytest tests/integration/api/web_v1/test_auth_trusted_device.py
uv run pytest tests/integration/api/web_v1/test_account_trusted_devices.py
uv run pytest tests/unit/services/test_trusted_device_service.py
```

Result: previously recorded as complete by T066.

### Frontend trusted-devices API coverage

```bash
cd apps/web
npm run test -- src/lib/api/trusted-devices.test.ts
```

Result: previously recorded as complete by T066.

### Trusted-device login bypass

```bash
cd apps/api
uv run pytest tests/security/authentication/test_trusted_device_bypass.py
uv run pytest tests/integration/api/web_v1/test_auth_trusted_device_login.py
```

Result: previously recorded as complete by T079; `test_trusted_device_bypass.py` was also included in the Phase 8 backend focused suite.

### Trusted-device browser E2E

```bash
cd apps/web
npm run test:e2e -- tests/e2e/auth-trusted-device.spec.ts
```

Result: `npx playwright test tests/e2e/auth-trusted-device.spec.ts` was invoked and collected the expected 2 tests, both skipped by test preconditions in this workspace.

### Admin/high-risk no-bypass and revocation safety

```bash
cd apps/api
uv run pytest tests/security/authentication/test_trusted_device_admin_no_bypass.py
uv run pytest tests/security/authentication/test_trusted_device_revocation_events.py
uv run pytest tests/security/authentication/test_trusted_device_high_risk_step_up.py
```

Result: US5 security suite passed with 15 tests.

### Phase 8 focused backend suite

```bash
cd apps/api
uv run pytest tests/integration/api/web_v1/test_auth_verify_email.py \
  tests/security/authentication/test_email_verification.py \
  tests/security/authentication/test_trusted_device_bypass.py \
  tests/security/authentication/test_auth_event_redaction_010.py -q --no-cov
```

Result: 16 passed.

### Phase 8 focused frontend suite

```bash
cd apps/web
npm run test -- 'src/routes/(auth)/verify-email/verify-email.spec.ts' \
  'src/routes/(auth)/login/login-trusted-device.spec.ts' --run
npx playwright test tests/e2e/auth-trusted-device.spec.ts
```

Result: Vitest 7 passed. Playwright collected 2 trusted-device E2E tests and skipped both under the current workspace preconditions.

### Contract, migration, and auth separation

```bash
cd apps/api
uv run pytest tests/contract/test_openapi_diff.py \
  tests/integration/migrations/test_email_verification_trusted_devices_schema.py -q --no-cov
uv run pytest tests/contract/test_auth_separation.py -q --no-cov
```

Result: contract/migration 24 passed. Auth separation 7 passed, 1 skipped for the existing asyncpg teardown race documented in the test.

### Additional quickstart security checks

```bash
cd apps/api
uv run pytest tests/security/authentication/test_admin_step_up_required.py -q --no-cov
uv run pytest tests/integration/api/web_v1/test_auth_webauthn.py -q --no-cov
uv run pytest tests/security/input_validation/test_mass_assignment_and_open_redirect.py \
  tests/security/authentication/test_auth_event_redaction_010.py -q --no-cov
```

Result: admin step-up 19 passed. WebAuthn 11 passed. Input validation + auth redaction 15 passed.

## Quickstart Gaps and Not-Run Items

The following quickstart manual checks were not run in this workspace:

- Start a full local stack with PostgreSQL, Redis, API, web, and the email/outbox worker.
- Capture a real verification message from the local mail sink or provider sandbox.
- Manually register a user, consume the verification token, and inspect `users.email_verified_at`.
- Manually inspect local audit logs for raw verification URLs or raw trusted-device cookie secrets.
- Manually inspect `trusted_devices.device_secret_hash` after browser cookie issuance.
- Manually test same-browser trusted-device login bypass and new-browser TOTP requirement.
- Manually revoke a trusted device from the browser UI and confirm the original browser requires TOTP.

## Documentation Updates

- `apps/api/README.md` now includes local verification email and trusted-device backend test instructions.
- `apps/web/README.md` now includes local trusted-device browser testing notes.
