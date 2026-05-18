# Rollout Go/No-Go Checklist

**Date**: 2026-05-18
**Feature**: 010 Email Verification and Trusted Devices

## Feature Flags

| Flag | Default | Go condition | Rollback |
|------|---------|--------------|----------|
| `EMAIL_VERIFICATION_ENFORCEMENT_ENABLED` | `false` | Token issue/consume/resend are stable, delivery monitoring is active, and support has user-facing recovery guidance. | Set `false` to stop protected-action blocking while keeping verification state. |
| `TRUSTED_DEVICE_REGISTRATION_ENABLED` | `false` | Cookie attributes, hash-only storage, list/revoke, and five-device cap pass focused tests. | Set `false` to stop issuing new trusted-device cookies. |
| `TRUSTED_DEVICE_BYPASS_ENABLED` | `false` | Non-privileged bypass, fallback reasons, admin no-bypass, revocation events, and E2E same-browser/new-browser tests pass. | Set `false` to require 2FA on all routine logins while preserving existing device records. |

## Email Verification Go/No-Go

- Registration creates an unverified user and enqueues exactly one verification email outbox event.
- The verification-email outbox event type has a registered worker handler and does not dead-letter in local and staging smoke tests.
- Resend returns generic 202 for unknown and known addresses.
- Per-IP, per-normalized-email, and per-user resend caps are tested.
- Token consume is single-use, atomic, email-bound, purpose-bound, and expiry-aware.
- Existing controlled seed/test/admin users have an audited bootstrap verification path.
- Non-controlled existing users remain unverified until they complete verification or the migration campaign explicitly handles them.

## Trusted Device Go/No-Go

- Trusted-device secrets are 43-character base64url values and are stored only as HMAC hashes.
- Trusted-device cookie attributes are `HttpOnly`, `SameSite=Strict`, scoped to the first-party auth surface, and `Secure` outside local test overrides.
- Device trust can be created only after successful second-factor verification and explicit user choice.
- Device trust is scoped by password-authenticated `user_id` during login lookup.
- Missing, malformed, expired, revoked, user-mismatched, stamp-mismatched, and recent-failure devices fall back to 2FA.
- Superuser/admin/elevated contexts never bypass required WebAuthn or recent step-up.
- Password reset/change, email change, 2FA reset, account deletion, and security-stamp rotation revoke or invalidate trusted devices.

## Operational Monitoring

- Alert on verification email outbox dead-letter count above zero.
- Alert on provider bounce rate or delivery failure rate above the release threshold defined by ops.
- Verify the dead-letter alert fires in staging by forcing one
  `auth.email_verification.requested` row to `dead_letter` or using the
  monitoring rule's test-notification path; record the alert ID in the
  release ticket.
- Verify the bounce/delivery-failure alert fires from a provider test event
  or dashboard rule dry run; record the alert ID in the release ticket.
- Track resend rate-limit denials by normalized reason without logging raw email addresses.
- Track trusted-device accepted/rejected counts by reason without logging raw cookie secrets, IP addresses, or User-Agent strings.
- Confirm logs redact verification tokens, full verification URLs, trusted-device secrets, raw IPs, and raw User-Agent strings.

## Release Sequence

1. Deploy schema, services, contracts, and UI with all three flags disabled.
2. Enable verification token issuance and resend behavior.
3. Validate registration-to-verification flow in staging and production smoke accounts.
4. Enable `EMAIL_VERIFICATION_ENFORCEMENT_ENABLED` only after delivery and support gates pass.
5. Enable `TRUSTED_DEVICE_REGISTRATION_ENABLED` and observe cookie issuance/list/revoke.
6. Enable `TRUSTED_DEVICE_BYPASS_ENABLED` for a limited cohort after US5 no-bypass security tests pass.

## Rollback Notes

Disabling enforcement or bypass flags must not require reverting migrations. If provider delivery is degraded, disable email enforcement first; if trusted-device rejection or session anomalies occur, disable trusted-device bypass first, then registration if new cookie issuance should stop.
