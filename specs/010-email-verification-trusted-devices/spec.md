# Feature Specification: Email Verification and Trusted Devices

**Feature Branch**: `010-email-verification-trusted-devices`
**Created**: 2026-05-18
**Status**: Draft
**Input**: Product/security decision to improve the first-party authentication experience by implementing real email-address verification and a server-bound trusted-device mechanism before relaxing the current "TOTP on every password login" behavior for non-privileged users.
**Amends**: `specs/006-permissions-redesign/` authentication requirements (FR-065 to FR-073, especially the blanket "all users TOTP on every login" posture)

## Summary

Echoroo currently treats every password login as high risk: users who have not enrolled TOTP are forced through first-login TOTP setup, and users who have enrolled TOTP must complete a TOTP or backup-code challenge on every password login. This is strong, but too strict for general users and especially awkward for users unfamiliar with authenticator apps.

At the same time, the email-verification surface exists only as a route mirror; the shared `AuthService.verify_email()` implementation is still a Phase-4 stub, and the canonical `users` table has no email-verification state. That means Echoroo has stronger second-factor friction than email-deliverability assurance, even though email is the account identifier and a recovery/notification channel.

This spec introduces two foundations:

1. **Email verification** as a real account lifecycle state.
2. **Trusted devices** as a server-bound device cookie plus revocable database record, registered only after a successful 2FA event.

After this work, non-privileged users who have completed 2FA on a trusted device can use password-only login on that device until trust expires or is revoked. New, unknown, expired, or suspicious devices still require 2FA. Administrator and high-risk flows remain stricter.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — New user verifies their email address (Priority: P1)

A new user registers with an email address and password. Echoroo creates the account, sends a verification email, and asks the user to verify the address before unlocking normal product functionality.

**Why this priority**: Email is the account identifier and recovery/notification channel. Implementing device trust before proving email deliverability would weaken the account lifecycle.

**Independent Test**: Register a new user, capture the outbound verification email from the test mail sink/outbox, open the verification link, and confirm `email_verified_at` is set. Confirm login still follows the existing 2FA path until trusted-device registration is introduced.

**Acceptance Scenarios**:

1. **Given** a user registers with a valid email address, **When** registration succeeds, **Then** Echoroo stores the user as unverified and enqueues exactly one verification email.
2. **Given** the verification email contains a valid token, **When** the user submits the token, **Then** the user's `email_verified_at` is set and the token cannot be reused.
3. **Given** the user submits an invalid, expired, already-used, or wrong-purpose token, **When** verification is attempted, **Then** the request is rejected without revealing whether the email belongs to an account.

---

### User Story 2 — Unverified user can sign in but cannot perform protected actions (Priority: P1)

A user who has not yet verified their email can still authenticate and reach enough UI to understand what is required, but cannot perform actions that rely on a deliverable email identity or create meaningful platform risk.

**Why this priority**: Hard lockout creates support burden, but allowing unverified accounts to operate normally undermines abuse controls and recovery assumptions.

**Independent Test**: Log in as an unverified user, confirm the account state is visible to the frontend, and verify protected actions return a clear 403 response with a stable error code.

**Acceptance Scenarios**:

1. **Given** an unverified user has valid credentials and completes required 2FA, **When** they log in, **Then** the session is issued and `/users/me` or the BFF equivalent exposes `email_verified_at = null`.
2. **Given** an unverified user attempts a protected action, **When** the request reaches the API, **Then** it is blocked with 403 `ERR_EMAIL_VERIFICATION_REQUIRED`.
3. **Given** an unverified user requests another verification email, **When** the resend limit has not been exceeded, **Then** Echoroo issues a new single-use token and invalidates or supersedes previous unconsumed tokens for the same purpose.

---

### User Story 3 — User trusts a device after successful 2FA (Priority: P2)

A user completes TOTP or backup-code verification on a browser they control and chooses "trust this device". Echoroo stores a revocable trusted-device record and sets a secure device cookie.

**Why this priority**: Trusted devices are the mechanism that reduces repeated 2FA prompts without dropping 2FA protection for new or unknown devices.

**Independent Test**: Complete the 2FA challenge with `trust_device=true`, confirm a secure device cookie is set, confirm the database stores only a hash of the device secret, and confirm the trusted device appears in the user's account security list.

**Acceptance Scenarios**:

1. **Given** a user completes TOTP successfully with `trust_device=true`, **When** the session is issued, **Then** Echoroo sets a device cookie with `HttpOnly`, `Secure`, `SameSite=Strict`, and an absolute expiry.
2. **Given** a trusted-device record exists, **When** an operator inspects the database, **Then** only a keyed hash or one-way hash of the device secret is stored, never the raw cookie value.
3. **Given** the user opens the account security page, **When** trusted devices are loaded, **Then** the user can see device metadata that is useful for recognition and can revoke each device individually.

---

### User Story 4 — Trusted device skips routine 2FA for non-privileged login (Priority: P2)

A non-privileged user returns on a trusted, unexpired, unrecalled browser. After password verification, Echoroo recognizes the trusted device and issues the normal session without prompting for TOTP again.

**Why this priority**: This is the primary UX improvement. The user still completed 2FA to bind the device, but does not need an authenticator app on every routine login from the same browser.

**Independent Test**: Trust a device, log out, log in again from the same browser, and confirm the response has `login_state="complete"` or equivalent session-issued state rather than `2fa_required`.

**Acceptance Scenarios**:

1. **Given** a non-privileged user logs in from a valid trusted device, **When** password verification succeeds, **Then** Echoroo issues the session without requiring TOTP.
2. **Given** the same user logs in without the device cookie, with a malformed cookie, or with an expired/revoked record, **When** password verification succeeds, **Then** Echoroo returns the existing `2fa_required` challenge state.
3. **Given** the trusted-device cookie is valid but contextual risk is elevated, **When** the user logs in, **Then** Echoroo requires 2FA and records the reason for the step-up.

---

### User Story 5 — Administrator and high-risk actions remain strongly protected (Priority: P2)

An administrator or a user performing a high-risk operation cannot rely on a long-lived trusted device alone. They must still satisfy the stricter authentication policy for admin sessions and sensitive operations.

**Why this priority**: The change is meant to reduce routine-user friction, not weaken high-impact account or data controls.

**Independent Test**: Log in as a superuser/admin from a trusted device and confirm admin elevation or destructive admin routes still require the existing WebAuthn/step-up policy. Attempt high-risk self-service actions from a trusted device and confirm recent step-up is required.

**Acceptance Scenarios**:

1. **Given** a superuser logs in from a trusted device, **When** admin access is requested, **Then** existing WebAuthn and step-up requirements still apply.
2. **Given** a user on a trusted device attempts to change password, change email, disable/reset 2FA, issue an API key, transfer ownership, delete high-value data, or perform a mass export, **When** no recent step-up exists, **Then** Echoroo requires step-up before completing the action.
3. **Given** a trusted-device record is revoked, **When** the browser later attempts login with the old cookie, **Then** the cookie is ignored and 2FA is required.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The canonical `users` model MUST include `email_verified_at: datetime | null`.
- **FR-002**: New user registration MUST create users with `email_verified_at = null` and MUST enqueue a verification email after successful account creation.
- **FR-003**: Email verification tokens MUST be single-use, purpose-scoped, bound to the target user/email, expire after 24 hours, and be stored in hashed form only.
- **FR-004**: `POST /web-api/v1/auth/verify-email` MUST replace the current Phase-4 stub with a real implementation that verifies a valid token and sets `users.email_verified_at`.
- **FR-005**: Email verification resend MUST be rate limited by user, normalized email, and IP address, and MUST use anti-enumeration response behavior.
- **FR-006**: Changing the account email address MUST clear `email_verified_at`, send a verification email to the new address, and notify the previous address when available.
- **FR-007**: The first-party current-user response MUST expose email verification state to the frontend without exposing verification tokens or raw delivery internals.
- **FR-008**: Unverified users MUST be allowed to authenticate but MUST be blocked from protected actions with 403 `ERR_EMAIL_VERIFICATION_REQUIRED`.
- **FR-009**: Protected actions for unverified users MUST include project creation, invitation/member management, upload/import, voting/commenting, API key creation, ownership transfer, destructive mutations, export/download of restricted data, and account email changes beyond the verification flow.
- **FR-010**: Email verification and resend attempts MUST emit platform audit events without logging raw verification tokens, full verification URLs, or unnecessary raw email addresses.
- **FR-011**: Accepting an email invitation MAY satisfy email verification only when the invitation token is valid, unexpired, single-use, and bound to the same normalized email address as the account being verified.
- **FR-012**: Production readiness MUST include SPF/DKIM/DMARC configuration, bounce/error monitoring, and an operator-visible signal when verification email delivery is failing.
- **FR-013**: The existing login notification based on IP/User-Agent hashes MAY remain as a notification/risk signal, but it MUST NOT be used as the trusted-device authority.
- **FR-014**: Trusted-device authority MUST be based on a high-entropy device secret stored in a secure browser cookie and represented server-side by a revocable database record.
- **FR-015**: The trusted-device cookie MUST be `HttpOnly`, `Secure`, `SameSite=Strict`, path-scoped to the first-party auth surface or application root as required by the BFF flow, and have an absolute expiry no longer than 30 days.
- **FR-016**: The server MUST store only a hash of the trusted-device secret. Raw cookie values MUST NOT be stored in the database or audit logs.
- **FR-017**: Trusted-device records MUST include `user_id`, `device_secret_hash`, `created_at`, `last_used_at`, `expires_at`, `revoked_at`, `last_ip_hash`, `last_user_agent_hash`, and a user-editable or server-derived display label.
- **FR-018**: A user MUST be able to list and revoke their own trusted devices from the account/security UI.
- **FR-019**: Revoking a trusted device MUST make future logins with that device cookie require 2FA.
- **FR-020**: 2FA challenge and first-login TOTP setup confirmation MUST accept an explicit `trust_device` boolean. The default MUST be false unless the UI clearly asks the user to trust the device.
- **FR-021**: A trusted device MUST only be registered after successful TOTP, backup-code, or stronger 2FA/WebAuthn verification. Password-only login MUST NOT create a trusted device.
- **FR-022**: Login from a valid trusted device MAY skip routine TOTP for non-privileged users after password verification.
- **FR-023**: Login from a missing, malformed, expired, revoked, mismatched, or risk-elevated device MUST follow the existing `2fa_required` path.
- **FR-024**: Trusted-device use MUST update `last_used_at`, `last_ip_hash`, and `last_user_agent_hash` without extending the absolute expiry beyond the original maximum lifetime.
- **FR-025**: The system MUST limit active trusted devices per user. The initial limit is 5 active devices.
- **FR-026**: Superusers and administrative step-up flows MUST NOT be weakened by trusted-device recognition. Existing WebAuthn and step-up requirements remain authoritative.
- **FR-027**: High-risk actions MUST require recent step-up even on trusted devices. The initial recent-step-up window is 10 minutes.
- **FR-028**: Security-stamp changes, password resets, 2FA resets, email changes, and account deletion MUST revoke or invalidate all trusted devices for the affected user.
- **FR-029**: The login response schema MUST gain an explicit successful state for trusted-device login (for example `login_state="complete"` with issued session/access token), while retaining `2fa_setup_required` and `2fa_required` for existing paths.
- **FR-030**: Browser and API tests MUST prove that trusted-device login does not call the 2FA challenge endpoint and that unknown-device login still does.
- **FR-031**: Existing API-key/programmatic `/api/v1/*` authentication MUST remain unchanged by this spec.
- **FR-032**: This spec MUST be implemented behind separate kill switches/config flags for email-verification enforcement, trusted-device registration, and trusted-device 2FA bypass, so rollout can be staged independently.

### Key Entities

#### User

- Existing account row.
- New field: `email_verified_at`.
- Existing fields such as `security_stamp`, `two_factor_enabled`, and `two_factor_reset_cooldown_until` remain authoritative.

#### EmailVerificationToken

- Purpose-scoped token record for verifying email ownership.
- Stores token hash, user binding, normalized email, expiry, consumed timestamp, creation metadata, and audit-safe request metadata.
- Raw token is shown only in the outbound email/link and never persisted.

#### TrustedDevice

- Revocable trusted-device binding for one user/browser.
- Stores hashed device secret and recognition metadata.
- Does not replace session cookies, refresh tokens, or WebAuthn credentials.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A newly registered user receives a verification email and can verify it end-to-end in integration tests.
- **SC-002**: Reusing, tampering with, or submitting an expired verification token fails with no account enumeration leak.
- **SC-003**: The current-user API exposes email verification status and the frontend can render an unverified-account state.
- **SC-004**: At least one protected-action test proves unverified users are blocked with 403 `ERR_EMAIL_VERIFICATION_REQUIRED`.
- **SC-005**: Completing 2FA with `trust_device=true` creates exactly one active trusted-device record and sets a secure device cookie.
- **SC-006**: A subsequent login from the same trusted device skips routine TOTP for a non-privileged user.
- **SC-007**: A login from a new browser, missing cookie, expired trusted device, or revoked trusted device still requires 2FA.
- **SC-008**: Superuser/admin flows and configured high-risk actions still require WebAuthn or recent step-up despite a trusted-device cookie.
- **SC-009**: No raw verification tokens, trusted-device cookie secrets, full verification URLs, raw IP addresses, or unnecessary raw email addresses appear in database rows, audit records, or application logs in the covered tests.
- **SC-010**: Rollout flags can independently disable email-verification enforcement, trusted-device registration, and trusted-device 2FA bypass without disabling ordinary login.

## Security and Privacy Requirements

- Trusted devices are not an authentication factor by themselves. They are a risk-reduction signal that allows Echoroo to skip repeated TOTP only after password verification.
- Email is a weak factor and MUST NOT be treated as sufficient MFA for high-risk actions.
- IP address and User-Agent hashes are signals only. They can trigger notification or step-up but MUST NOT alone grant device trust.
- Device cookies MUST be rotated if the server detects a stale hash format, key rotation boundary, or suspicious reuse pattern.
- A suspected stolen trusted-device cookie MUST be containable by revoking that device record or by changing the user's `security_stamp`.
- Account recovery and 2FA reset flows MUST remain at least as strict as the current implementation.

## Assumptions

- The project is still pre-launch or in limited rollout, so database migrations and auth contract changes are acceptable if shipped with tests.
- Existing users may already have TOTP enrolled. Their enrollment remains intact; this spec only changes when TOTP is prompted for routine non-privileged login.
- Controlled seed, test, and admin accounts may be marked verified through audited bootstrap data. Other existing users start with `email_verified_at = null` and receive a grace-period verification campaign before enforcement is enabled.
- Mail delivery is handled through the existing email/outbox infrastructure, with provider configuration and local test mail capture available.
- `specs/006-permissions-redesign/` remains the baseline for authentication, session, security-stamp, audit, WebAuthn, and superuser policy unless this spec explicitly amends it.
- The implementation may land incrementally: email verification first, trusted-device registration second, trusted-device login bypass third.

## Out of Scope

- Making TOTP enrollment optional for all users. This spec reduces repeated prompts on trusted devices but does not remove the enrollment requirement by itself.
- Weakening superuser WebAuthn, IP allowlist, M-of-N approval, or destructive admin step-up requirements.
- Using SMS as a second factor.
- Treating email verification as MFA.
- Replacing refresh-token rotation, session cookies, CSRF, or the BFF/programmatic API separation.
- Full account-recovery redesign beyond preserving existing 2FA reset and password-reset safety.
- Passkey/WebAuthn rollout for general users, except where existing WebAuthn admin flows must remain compatible.

## Implementation Notes

Recommended delivery order:

1. Add email-verification persistence and implement `/web-api/v1/auth/verify-email`.
2. Add resend and frontend unverified-account state.
3. Add protected-action middleware/guards for `ERR_EMAIL_VERIFICATION_REQUIRED`.
4. Add trusted-device persistence and account/security management endpoints.
5. Add `trust_device` handling to 2FA success paths and set the device cookie.
6. Add trusted-device recognition to password login for non-privileged users.
7. Add risk signals, revocation hooks, rollout flags, and browser E2E coverage.

The first implementation plan should explicitly inventory every current test that assumes "every password login returns `2fa_required`" and split those expectations between unknown-device and trusted-device cases.
