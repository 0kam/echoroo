# Runbook: Trusted Devices

This runbook covers operation of first-party trusted devices for routine
non-privileged login. Trusted devices reduce repeated TOTP prompts only
after a successful second-factor challenge. They do not replace WebAuthn,
admin elevation, or recent step-up for high-risk actions.

## Controls

- `TRUSTED_DEVICE_REGISTRATION_ENABLED`: allows new trusted-device cookies
  to be issued after successful TOTP, backup-code, or stronger 2FA.
- `TRUSTED_DEVICE_BYPASS_ENABLED`: allows a valid trusted-device cookie to
  complete routine non-privileged login after password verification.
- `TRUSTED_DEVICE_COOKIE_NAME`: defaults to `echoroo_trusted_device`.
- `TRUSTED_DEVICE_COOKIE_TTL_SECONDS`: defaults to 30 days.

Trusted-device secrets are generated as 43-character base64url values and
stored only as HMAC hashes in `trusted_devices.device_secret_hash`. The
browser cookie must be `HttpOnly`, `SameSite=Strict`, and `Secure` outside
local test overrides.

## Normal Operations

Before enabling registration:

1. Confirm focused tests cover cookie attributes, hash-only storage,
   five-device cap eviction, list, revoke, and revoke-all behavior.
2. Confirm the account UI can list active trusted devices without exposing
   raw secrets, IP addresses, or User-Agent strings.
3. Confirm support can direct users to revoke one device or all devices
   from account security.

Before enabling bypass:

1. Confirm missing, malformed, expired, revoked, user-mismatched,
   security-stamp-mismatched, and recent-password-failure devices fall
   back to 2FA.
2. Confirm superuser/admin accounts and high-risk actions still require
   WebAuthn or recent step-up.
3. Confirm password reset/change, email change, 2FA reset, account
   deletion, and security-stamp rotation revoke or invalidate trusted
   devices.

## Monitoring

Track counts by normalized reason only:

- trusted-device created
- trusted-device revoked
- trusted-device bypass accepted
- trusted-device bypass rejected, grouped by reason
- recent-step-up denials where `trusted_device_used=true`

Do not log raw cookie values, raw IP addresses, or raw User-Agent strings.
Use hashes or normalized reason codes only.

## Incident Response

If users unexpectedly skip 2FA, set `TRUSTED_DEVICE_BYPASS_ENABLED=false`
first. Existing trusted-device records remain available, but every routine
login falls back to 2FA.

If new cookies should stop being issued, set
`TRUSTED_DEVICE_REGISTRATION_ENABLED=false`. Existing records remain until
they expire, are revoked by the user, or are invalidated by security-stamp
changes.

If a user's device may be compromised, revoke the individual device from
the account security UI. If account compromise is suspected, revoke all
trusted devices and rotate the user's security stamp through the existing
password reset/change or 2FA reset flow.

If bypass rejection spikes, inspect the normalized reason distribution:

- `malformed` or `not_found`: likely stale/corrupt cookies or deployment
  cookie-name mismatch.
- `security_stamp_mismatch`: expected after password, 2FA, email, or
  account-security changes.
- `privileged_user`: expected for superuser/admin-capable accounts.
- `recent_password_failure`: expected after failed password attempts.

## Rollback

Trusted-device rollback is flag-only. Disable bypass first, then disable
registration if new device issuance should stop. Do not revert the
`trusted_devices` migration during an incident; keeping the table lets
users and operators inspect and revoke existing records.

