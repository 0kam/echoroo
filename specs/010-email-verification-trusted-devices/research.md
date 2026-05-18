# Phase 0 Research — Email Verification and Trusted Devices

**Date**: 2026-05-18
**Spec**: [spec.md](spec.md)
**Plan**: [plan.md](plan.md)

This document records the design decisions for implementing email verification and trusted devices without weakening Echoroo's existing 2FA, WebAuthn, audit, and BFF/API-key separation guarantees.

## D-1. Email verification state belongs on `users.email_verified_at`

**Decision**: Add `users.email_verified_at TIMESTAMPTZ NULL` as the canonical verification state. Do not revive legacy `is_verified` or `email_verification_token` columns.

**Rationale**:
- The current `User` model has no email-verification state, while frontend types still carry old `is_verified` vocabulary in some places. A timestamp is more useful than a boolean because it supports audit, migration, support diagnostics, and future re-verification policy.
- Keeping tokens in a separate table avoids long-lived token material on the user row and allows single-use, purpose-scoped lifecycle transitions.
- `email_verified_at = null` is explicit and maps cleanly to frontend account state.

**Alternatives considered**:
- Boolean `email_verified`. Rejected because it loses timing and migration context.
- Reintroducing `is_verified` and token columns from older tests. Rejected because spec/006 intentionally rebuilt the user model and dropped those legacy assumptions.

## D-2. Verification tokens use a dedicated table and hash-only storage

**Decision**: Add an `email_verification_tokens` table with hashed token storage, user binding, normalized email binding, purpose, expiry, consumed timestamp, and audit-safe request metadata.

**Rationale**:
- Tokens must be single-use and purpose-scoped. A table supports atomic consume (`WHERE consumed_at IS NULL AND expires_at > now()`), resend supersession, and audit.
- Binding the token to normalized email prevents a stale token from verifying a later changed address.
- Hash-only storage keeps a database leak from turning into valid verification links.

**Alternatives considered**:
- JWT-only verification link with no DB row. Rejected because server-side revocation/supersession and single-use semantics become awkward.
- Reusing password-reset token storage. Rejected for planning: password reset has similar mechanics, but verification needs distinct purpose, email binding, and resend behavior. Implementation can share helpers if the codebase already has a generic token primitive.

## D-3. Registration sends verification email but does not issue a session

**Decision**: Keep the current registration posture: account creation succeeds, no first-party session is issued, and the user proceeds to login/2FA. Registration also enqueues a verification email through the transactional outbox, not by direct provider call inside the request transaction.

**Rationale**:
- This preserves current auth surface shape while adding email assurance.
- It avoids creating a session for an account that may have an undeliverable or mistyped email.
- The existing verify-email UI can remain the user-facing completion path.
- The codebase has direct `send_verification_email()` helpers, but registration should keep user creation, token creation, and email enqueue in one database transaction. A registered outbox handler avoids orphaned users/tokens and avoids dead-lettering a new event type.

**Alternatives considered**:
- Auto-login after registration. Rejected because it changes more auth behavior than needed for this feature.
- Require email verification before any login. Rejected because it can create support-heavy lockout if mail delivery is delayed; the spec instead allows login but limits protected actions.

## D-4. Unverified accounts are authenticated but capability-limited

**Decision**: Allow unverified users to authenticate and complete 2FA, but block protected actions with 403 `ERR_EMAIL_VERIFICATION_REQUIRED`.

**Rationale**:
- Authentication proves password/2FA possession; email verification proves reachability of the account identifier. These are different checks.
- Allowing login gives users a path to resend verification and understand the account state.
- Blocking project creation, uploads/imports, invitations, API key creation, destructive mutations, ownership transfer, and restricted-data export reduces abuse and recovery risk.

**Alternatives considered**:
- Full lockout until verified. Rejected because it increases support burden and makes resend flows harder.
- No restrictions for unverified users. Rejected because email deliverability is a core account safety assumption.

## D-4a. Public auth paths and frontend types must be updated together

**Decision**: Treat `/web-api/v1/auth/verify-email` and `/web-api/v1/auth/verify-email/resend` as exact public auth paths, and update backend/frontend user schemas to expose `email_verified_at`.

**Rationale**:
- The auth router and CSRF/public-path handling are exact-path based. Adding resend without updating `PUBLIC_AUTH_PATHS` would produce confusing 401/403 behavior before the service is reached.
- The current frontend still has legacy `is_verified` vocabulary in places. This feature standardizes on `email_verified_at: string | null`.
- Existing BFF verify-email tests currently assert the 501 stub behavior; implementation tasks must convert them to real invalid-token and success-path assertions.

**Alternatives considered**:
- Keep old `is_verified` in frontend and map it server-side. Rejected because it preserves vocabulary drift and hides the timestamp needed for account UI.

## D-5. Invitation acceptance can verify email only under strict binding

**Decision**: A valid invitation token may satisfy email verification only if it is unexpired, single-use, and bound to the same normalized email as the account.

**Rationale**:
- Invitation email delivery is proof that the user controlled the invited mailbox at acceptance time.
- The same-email binding prevents cross-account verification via a token forwarded to a different address.
- This reduces duplicate "verify email" friction for invited users without making invitations a weaker channel.

**Alternatives considered**:
- Always require a separate verification email after invitation acceptance. Safe but unnecessarily redundant.
- Treat any accepted invitation as verification. Rejected because forwarded links and email changes would create ambiguity.

## D-6. Trusted device authority is a cookie secret plus server record, not IP/UA

**Decision**: Trusted devices use a high-entropy random secret in a secure cookie and a server-side `trusted_devices` row containing only a hash of that secret. IP and User-Agent hashes remain risk/notification signals only.

**Rationale**:
- IP addresses change frequently and can be shared; User-Agent is easy to spoof. They are not sufficient trust anchors.
- A server-side row allows revocation, max-device limits, expiration, and audit.
- Hash-only storage mirrors password/token safety: cookie theft remains dangerous, but DB leakage does not produce usable device cookies.

**Alternatives considered**:
- Reusing `user_login_notifications_seen`. Rejected because that model was designed for notification suppression, not authentication risk decisions.
- Client-side signed cookie with no DB row. Rejected because individual revocation and max-device limits are required.

## D-7. Trusted-device registration happens only after successful 2FA

**Decision**: `trust_device=true` is accepted only on successful TOTP, backup-code, or stronger WebAuthn verification paths. Password-only login never creates a trusted device.

**Rationale**:
- Device trust is a memory of a completed second-factor event. Creating trust after password-only login would turn stolen credentials into persistent bypass.
- The current two success paths are `/auth/2fa/challenge` and `/auth/2fa/setup/totp/confirm`; both already issue real sessions and are the right place to attach device trust.

**Alternatives considered**:
- Trust device during password login before 2FA. Rejected as a security regression.
- Trust device automatically after every 2FA. Rejected because shared/public computers need an explicit user choice.

## D-8. Login bypass is non-privileged, post-password, and revocation-aware

**Decision**: Password login checks trusted-device validity only after password verification. A valid trusted device may return a complete session for non-privileged users. Missing, expired, revoked, malformed, risk-elevated, or privileged/admin cases return the existing 2FA challenge state.

**Rationale**:
- Password remains the first factor and rate-limit/backoff remains unchanged.
- Post-password lookup avoids account enumeration and avoids spending trusted-device checks for invalid credentials.
- The current `LoginResponse` must gain an explicit complete state so frontend code can distinguish "password accepted and session issued" from "interim token for 2FA".

**Alternatives considered**:
- Check trusted device before password. Rejected because it leaks device/account relationships and bypasses existing login-attempt accounting.
- Use trusted device for admin login. Rejected; admin and superuser flows remain stricter.

### D-8a. Initial risk-elevated signals are explicit and fail to step-up

**Decision**: The initial trusted-device bypass checks only this enumerated risk set:

- Trusted-device row belongs to the password-authenticated `user_id`; lookup is `WHERE user_id = :user_id AND device_secret_hash = :hash`.
- Device row is active, unexpired, not revoked, and bound to the current `security_stamp`.
- User is not a superuser and is not entering an admin elevation flow.
- User has not had recent failed login/2FA attempts crossing the existing backoff/lockout thresholds.
- Optional IP/User-Agent risk signals are observe-only for the first rollout unless `TRUSTED_DEVICE_CONTEXT_RISK_ENFORCEMENT_ENABLED` is introduced in a later feature.

Anything outside this explicit list is a no-op for bypass decisions in spec/010. When a listed risk condition fails, login returns the existing 2FA challenge state and records the reason in audit-safe detail.

**Rationale**:
- Avoids ad-hoc "risk-elevated" logic that changes by implementation site.
- Keeps the first rollout simple and testable: user mismatch, revoked/expired/stamp mismatch, privileged user, and recent failure state are deterministic.
- IP and User-Agent are useful signals but not reliable enough to block routine login in the first iteration.

### D-8b. Recent step-up uses existing step-up-token semantics

**Decision**: For high-risk operations, "recent step-up" means an existing step-up token or equivalent session-bound proof accepted by `middleware/step_up.py`, bound to current user and current `security_stamp`, within the existing short TTL (10 minutes maximum for this feature). Trusted-device login does not mint or replace a step-up token.

**Rationale**:
- The codebase already has WebAuthn/step-up infrastructure for destructive admin actions.
- Adding a global `users.last_step_up_at` would be weaker because one browser could satisfy step-up for another browser.
- This keeps high-risk operation protection independent from trusted-device login convenience.

## D-9. Device expiry is absolute, with no sliding extension

**Decision**: Initial trusted-device lifetime is no more than 30 days absolute. `last_used_at` is updated on use, but `expires_at` is not extended.

**Rationale**:
- Sliding windows can silently turn a one-time trust decision into indefinite bypass.
- Absolute expiry is simpler to reason about, easier to explain in audits, and aligns with the spec's "routine login convenience" goal.
- `last_used_at` still supports account UI recognition and suspicious-use investigation.

**Alternatives considered**:
- 30-day sliding expiry. Rejected because it can persist forever on active devices.
- 7-day default for all users. Safer but less useful for reducing routine friction; admin/high-risk flows already remain stricter.

## D-10. Security-stamp and account-security events invalidate device trust

**Decision**: Password reset, password change, email change, 2FA reset, account deletion, and explicit `security_stamp` rotation revoke or invalidate all trusted devices for that user. Spec/010 assumes `security_stamp` does not rotate on routine refresh/access-token rotation; if that assumption changes, trusted-device lifetime must be revisited.

**Rationale**:
- These events indicate a material account-security boundary change.
- The existing `security_stamp` is already central to session invalidation; trusted-device verification should bind to the current stamp or be bulk-revoked by the same code paths.

**Alternatives considered**:
- Leave trusted devices intact after password changes. Rejected because a user changing credentials after suspected compromise expects old devices to stop working.

## D-10a. Token and device secret format

**Decision**: Verification tokens and trusted-device secrets use 32 random bytes from a CSPRNG, encoded as 43-character unpadded base64url strings. Server storage uses HMAC-SHA-256 over the raw encoded token/secret with a KMS-backed application pepper/key. Dual-read key rotation follows the existing two-key pattern used elsewhere in the auth/security code.

**Rationale**:
- Fixed-length tokens simplify validation and fuzz testing.
- HMAC with a non-database key prevents offline guessing if the database is leaked.
- The dual-read key approach matches existing security-key rotation patterns in the repo.

## D-11. Contracts are spec-local deltas, not replacement for spec/006 contracts

**Decision**: Add contract delta files under `specs/010-email-verification-trusted-devices/contracts/` for the new/changed endpoints, then reconcile them into `specs/006-permissions-redesign/contracts/` as an explicit foundational implementation task (T016) before endpoint implementation proceeds.

**Rationale**:
- This feature changes auth response shapes and adds trusted-device account endpoints, so planning needs explicit endpoint contracts.
- Keeping them in spec/010 during planning avoids prematurely editing the broader spec/006 contract set. T016 makes the canonical contract merge explicit for implementation.

**Alternatives considered**:
- Directly edit spec/006 contract YAML during planning. Rejected because this turn is planning-only and implementation tasks should own canonical contract edits.

## D-12. Rollout flags are mandatory

**Decision**: Add independent flags for email-verification enforcement, trusted-device registration, and trusted-device 2FA bypass. Verification token issuance can ship before enforcement; trusted-device cookie issuance can ship before bypass.

**Rationale**:
- Email deliverability problems should not immediately lock users out of protected product workflows.
- Trusted-device cookie issuance can be tested in production-like environments before it changes login behavior.
- Flags allow staged rollback without reverting schema migrations.

**Alternatives considered**:
- Single global auth rollout flag. Rejected because email verification and trusted-device bypass have different risk profiles and operational failure modes.

## D-13. Existing-user migration policy

**Decision**: Because the project is pre-launch/limited-rollout, controlled seed/test/admin accounts may be marked verified by audited bootstrap data. All other existing users start with `email_verified_at = null` and receive a grace-period verification campaign before enforcement is enabled.

**Rationale**:
- Avoids silently claiming mailbox proof for users who never completed a verification flow.
- Keeps CI/E2E seeds usable.
- Makes enforcement rollout operationally reversible through the enforcement flag.

## D-14. Resend abuse controls

**Decision**: Pre-session resend is allowed only with layered controls: IP rate limit, normalized-email global rate limit, account/user rate limit when authenticated, outstanding active-token cap, and generic 202 anti-enumeration response. CAPTCHA/proof-of-work remains a fallback if abuse is observed, not a hard initial dependency.

**Rationale**:
- Anti-enumeration responses prevent account discovery but can otherwise enable mailbox flooding.
- Per-email caps are required even when account existence is not disclosed.

## D-15. BFF response shape keeps existing access-token compatibility

**Decision**: Keep the current BFF pattern of returning the BFF-issued `access_token` in successful auth responses while also setting cookies, because existing `web_v1/auth.py` and spec/009 already rely on that shape. This feature does not introduce localStorage persistence of the token.

**Rationale**:
- Removing `access_token` from auth responses is a separate BFF auth redesign and would broaden scope.
- The trusted-device feature only adds a new `login_state="complete"` branch to the existing pattern.

## Summary

All planning clarifications are resolved:

- Canonical email verification state: `users.email_verified_at`.
- Token model: dedicated hash-only, single-use, purpose/email-bound table.
- Registration: enqueue verification email, no session.
- Unverified users: can login, protected actions return 403 `ERR_EMAIL_VERIFICATION_REQUIRED`.
- Trusted device authority: secure cookie secret + server hash row, not IP/UA.
- Trusted device creation: only after successful 2FA/WebAuthn and explicit user choice.
- Login bypass: post-password, non-privileged only, revocation/risk-aware.
- Expiry: absolute maximum 30 days; no sliding extension.
- High-risk/admin: no weakening; recent step-up/WebAuthn remains required.
- Rollout: independent flags for enforcement and bypass.
- Existing-user migration: seed/test/admin verified by bootstrap, others verify with grace period.
