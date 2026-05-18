# Phase 1 — Data Model

**Date**: 2026-05-18
**Spec**: [spec.md](spec.md)
**Plan**: [plan.md](plan.md)

## Scope

This feature adds account-authentication state. It introduces two new persistence entities and one new field on `users`.

## Entities

### User (existing)

**Owner**: `apps/api/echoroo/models/user.py`

**New field**:

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `email_verified_at` | `DateTime(timezone=True)` | yes | Null means the current account email has not been verified. Set once a valid verification token or same-email invitation acceptance proves mailbox reachability. Cleared on email change. |

**Existing fields used by this feature**:

| Field | Use |
|-------|-----|
| `email` | Normalized email bound into verification tokens. |
| `security_stamp` | Used to invalidate sessions and trusted-device trust after material account-security events. |
| `two_factor_enabled` | Determines first-login TOTP setup vs challenge path. |
| `two_factor_reset_cooldown_until` | Existing cooldown remains authoritative. |
| `deleted_at` | Deleted users cannot verify email or use trusted devices. |

**State transitions**:

```text
registered/unverified
  ├─ valid email verification token consumed -> verified
  ├─ same-email invitation accepted -> verified
  └─ email changed -> unverified for new address

verified
  ├─ email changed -> unverified
  └─ account deleted -> deleted, no further verification
```

### EmailVerificationToken (new)

**Purpose**: Verify that the user can receive mail at the normalized email currently associated with the account.

**Proposed table**: `email_verification_tokens`

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | UUID | no | Primary key. |
| `user_id` | UUID FK users.id | no | Cascade delete with user. |
| `email_normalized` | String(255) | no | Lowercase normalized email bound to token. |
| `token_hash` | String(64 or 128) | no | Hash of opaque random token. Raw token is never stored. |
| `purpose` | String(64) | no | Initial value: `verify_email`. Allows future email-change confirmation variants without table redesign. |
| `expires_at` | DateTime(timezone=True) | no | Initial TTL: 24 hours. |
| `consumed_at` | DateTime(timezone=True) | yes | Set atomically when token is used. |
| `superseded_at` | DateTime(timezone=True) | yes | Set when resend invalidates previous unconsumed token. |
| `created_ip_hash` | String(64) | yes | HMAC/hash of requesting IP when available. |
| `created_user_agent_hash` | String(64) | yes | HMAC/hash of requesting User-Agent when available. |
| `created_at` | DateTime(timezone=True) | no | Server timestamp. |
| `updated_at` | DateTime(timezone=True) | no | Server timestamp. |

**Indexes/constraints**:

- Unique active token hash.
- Index on `(user_id, purpose, consumed_at, superseded_at, expires_at)`.
- Index on `expires_at` for cleanup.

**Validation rules**:

- Raw token must be high entropy and URL-safe.
- Token consume requires `consumed_at IS NULL`, `superseded_at IS NULL`, `expires_at > now()`, matching purpose, matching user, matching normalized email, and non-deleted user.
- Token consume additionally requires `users.email == email_verification_tokens.email_normalized` at consume time.
- Token consume must be atomic: exactly one concurrent submit can set `consumed_at`.
- Resend supersedes previous unconsumed tokens for `(user_id, purpose, email_normalized)`.
- Email change supersedes all unconsumed `verify_email` tokens for the user.
- Partial unique index: at most one active token per `(user_id, purpose, email_normalized)` where `consumed_at IS NULL AND superseded_at IS NULL`.

### TrustedDevice (new)

**Purpose**: Remember that a specific browser completed 2FA, so routine future password logins from that browser can skip TOTP for non-privileged users.

**Proposed table**: `trusted_devices`

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `id` | UUID | no | Primary key. |
| `user_id` | UUID FK users.id | no | Cascade delete with user. |
| `device_secret_hash` | String(64 or 128) | no | Hash of random cookie secret. Raw cookie value is never stored. |
| `security_stamp` | String(64) | no | Value copy of `users.security_stamp` at time of issuance; mismatch invalidates trust. Length must match the canonical user model. |
| `label` | String(100) | yes | User-editable or server-derived display label. |
| `created_at` | DateTime(timezone=True) | no | Trust creation time. |
| `last_used_at` | DateTime(timezone=True) | yes | Updated on accepted trusted-device login. |
| `expires_at` | DateTime(timezone=True) | no | Absolute expiry, no more than 30 days after creation. |
| `revoked_at` | DateTime(timezone=True) | yes | Set by user or security event. |
| `last_ip_hash` | String(64) | yes | Risk/display signal only. |
| `last_user_agent_hash` | String(64) | yes | Risk/display signal only. |
| `created_ip_hash` | String(64) | yes | Audit/display signal only. |
| `created_user_agent_hash` | String(64) | yes | Audit/display signal only. |

**Indexes/constraints**:

- Unique active `device_secret_hash`.
- Index on `(user_id, revoked_at, expires_at)`.
- Active trusted devices per user limited to 5 by service logic inside the transaction that creates a new device.
- On the 6th device, auto-revoke the oldest active device by `COALESCE(last_used_at, created_at)` and write an audit event.

**State transitions**:

```text
issued
  ├─ accepted login -> last_used_at updated (expires_at unchanged)
  ├─ user revoke -> revoked
  ├─ security event bulk revoke -> revoked
  ├─ expires_at <= now -> expired
  └─ security_stamp mismatch -> invalid
```

**Validation rules**:

- Device can be issued only after successful TOTP, backup-code, or WebAuthn verification.
- Password-only login can verify an existing device but cannot create a new one.
- Valid trusted-device login requires non-deleted user, matching current `security_stamp`, `revoked_at IS NULL`, `expires_at > now()`, and no elevated-risk/admin requirement.
- Trusted-device lookup during login must be scoped by the password-authenticated user: `WHERE user_id = :user_id AND device_secret_hash = :hash`.
- User mismatch is treated the same as a missing device and silently falls back to 2FA.

## Relationships

```text
User 1 ── * EmailVerificationToken
User 1 ── * TrustedDevice
```

`EmailVerificationToken` and `TrustedDevice` are account-security records, not project-scoped entities. They do not interact with `ProjectTrustedUser`, which remains the spec/006 project permission overlay.

## Cleanup

- Expired email verification tokens may be deleted after audit retention needs are satisfied.
- Expired/revoked trusted devices may be deleted or archived after a bounded retention period; raw secrets are never available either way.

## Migration Policy

Controlled seed/test/admin accounts are marked verified through audited bootstrap data. Other existing users start with `email_verified_at = null` and receive a grace-period verification campaign before enforcement is enabled.

No implementation task may silently mark arbitrary production users verified outside the controlled bootstrap set.

## Audit Events

The implementation must define and test audit-safe event payloads for:

- `auth.email_verification_token_issued`
- `auth.email_verification_succeeded`
- `auth.email_verification_failed`
- `auth.email_verification_resend_requested`
- `auth.trusted_device_created`
- `auth.trusted_device_used`
- `auth.trusted_device_revoked`
- `auth.trusted_device_auto_revoked_for_limit`
- `auth.trusted_device_rejected`

Event payloads must not contain raw verification tokens, full verification URLs, raw trusted-device secrets, raw IP addresses, or raw User-Agent strings.
