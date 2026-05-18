# Quickstart — Email Verification and Trusted Devices

**Date**: 2026-05-18
**Spec**: [spec.md](spec.md)
**Plan**: [plan.md](plan.md)

This quickstart describes the implementation verification flow. Exact commands may be adjusted by `/speckit-tasks` once task ownership is split.

## Prerequisites

1. Start the local stack with PostgreSQL, Redis, API, web, and the email/outbox worker enabled.
2. Configure local email capture or provider sandbox credentials.
3. Ensure feature flags are explicit:
   - `EMAIL_VERIFICATION_ENFORCEMENT_ENABLED=false` for initial token-flow testing.
   - `TRUSTED_DEVICE_REGISTRATION_ENABLED=false` for initial trusted-device service testing.
   - `TRUSTED_DEVICE_BYPASS_ENABLED=false` for initial cookie issuance testing.
   - Enable each flag only in the relevant test phase.

## Backend Verification

### 1. Email verification token flow

1. Register a user through `POST /web-api/v1/auth/register`.
2. Confirm `users.email_verified_at IS NULL`.
3. Confirm one verification email outbox event was created and that a registered worker handler can process it.
4. Extract the test verification token from the local mail sink.
5. Submit `POST /web-api/v1/auth/verify-email`.
6. Confirm `users.email_verified_at IS NOT NULL`.
7. Submit the same token again and confirm it is rejected.

Expected tests:

```bash
cd apps/api
uv run pytest tests/integration/api/web_v1/test_auth_verify_email.py
uv run pytest tests/security/authentication/test_email_verification.py
```

### 2. Unverified protected-action enforcement

1. Create or register an unverified user.
2. Complete the existing login + 2FA flow.
3. Enable email-verification enforcement.
4. Attempt a protected action such as project creation or API key creation.
5. Confirm 403 `ERR_EMAIL_VERIFICATION_REQUIRED`.
6. Verify the email and retry the action.
7. Confirm `EMAIL_VERIFICATION_ENFORCEMENT_ENABLED=false` allows the same action while still exposing `email_verified_at = null`.

Expected tests:

```bash
cd apps/api
uv run pytest tests/security/authentication/test_email_verification.py -k protected
```

### 3. Trusted-device issuance

1. Log in from a new browser/client.
2. Complete TOTP challenge with `trust_device=true`.
3. Confirm the response sets a trusted-device cookie:
   - `HttpOnly`
   - `Secure` outside local test overrides
   - `SameSite=Strict`
   - absolute expiry no more than 30 days
4. Confirm `trusted_devices.device_secret_hash` exists and no raw cookie value is stored.

Expected tests:

```bash
cd apps/api
uv run pytest tests/integration/api/web_v1/test_auth_trusted_device.py
uv run pytest tests/unit/services/test_trusted_device_service.py
```

### 4. Trusted-device login bypass

1. Enable trusted-device bypass.
2. Log out while preserving the trusted-device cookie.
3. Log in again with the same browser/client.
4. Confirm login returns the explicit complete state and issues the normal session without calling `/auth/2fa/challenge`.
5. Repeat without the cookie and confirm `2fa_required`.
6. Revoke the device and confirm the old cookie no longer bypasses 2FA.
7. Disable `TRUSTED_DEVICE_BYPASS_ENABLED` and confirm a valid trusted-device cookie still requires 2FA.
8. Disable `TRUSTED_DEVICE_REGISTRATION_ENABLED` and confirm 2FA success does not create a new trusted-device cookie.

Expected tests:

```bash
cd apps/api
uv run pytest tests/security/authentication/test_trusted_device_bypass.py
```

### 5. Admin and high-risk no-bypass

1. Create a trusted device for an admin/superuser-capable account.
2. Attempt admin or destructive operation without recent step-up.
3. Confirm existing WebAuthn/step-up requirements still apply.

Expected tests:

```bash
cd apps/api
uv run pytest tests/security/authentication/test_admin_step_up_required.py
uv run pytest tests/integration/api/web_v1/test_auth_webauthn.py
```

## Frontend Verification

1. Register a new user.
2. Visit the verify-email page with a valid token and confirm the success state.
3. Log in as an unverified user and confirm the account state/resend affordance renders.
4. Complete 2FA with "trust this device" selected.
5. Log out and log back in from the same browser; confirm no TOTP screen appears.
6. Open a fresh browser context; confirm TOTP is still required.
7. Revoke the device from account security and confirm the original browser requires TOTP next time.

Expected tests:

```bash
cd apps/web
npm run test -- auth
npm run test:e2e -- auth.spec.ts
```

## Security Checks

Run focused log/storage checks before claiming completion:

```bash
cd apps/api
uv run pytest tests/security/authentication/test_email_verification.py
uv run pytest tests/security/authentication/test_trusted_device_bypass.py
uv run pytest tests/security/input_validation/test_mass_assignment_and_open_redirect.py
```

Manual inspection checklist:

- No raw verification token in DB.
- No full verification URL in audit logs.
- Verification email outbox event type has a registered handler and does not dead-letter.
- Verification email bounce/dead-letter alerting is visible before enforcement is enabled.
- No raw trusted-device cookie secret in DB/audit/logs.
- Existing `/api/v1/*` API-key auth behavior unchanged.
- Feature flags can disable enforcement and bypass independently.
- Day-0 deployment behavior: existing TOTP-enrolled users have no trusted devices and still receive `2fa_required` until they opt in on their next successful 2FA challenge.
