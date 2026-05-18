# Tasks: Email Verification and Trusted Devices

**Input**: Design documents from `/specs/010-email-verification-trusted-devices/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. The repository constitution mandates TDD, and this feature changes authentication, account state, cookie behavior, and security controls.

**Organization**: Tasks are grouped by user story so each increment is independently testable. Phase 1 and Phase 2 are shared prerequisites.

## Phase 1: Setup & Inventory

**Purpose**: Lock down the current auth/test surface before changing behavior.

- [X] T001 Create test inventory for existing auth assumptions in `specs/010-email-verification-trusted-devices/test-inventory.md`
- [X] T002 [P] Create canonical contract reconciliation checklist in `specs/010-email-verification-trusted-devices/contract-reconciliation.md`
- [X] T003 [P] Create rollout Go/No-Go checklist in `specs/010-email-verification-trusted-devices/rollout-checklist.md`
- [X] T004 [P] Audit existing frontend `is_verified` usage and record replacement plan in `specs/010-email-verification-trusted-devices/frontend-type-audit.md`

---

## Phase 2: Foundational Prerequisites

**Purpose**: Shared schema, settings, crypto, and contract scaffolding that all user stories depend on.

**Critical**: No user-story implementation should start until this phase is complete.

### Tests First

- [X] T005 [P] Add failing migration/schema test for `users.email_verified_at`, `email_verification_tokens`, and `trusted_devices` in `apps/api/tests/integration/migrations/test_email_verification_trusted_devices_schema.py`
- [X] T006 [P] Add failing unit tests for HMAC token hashing and fixed-length token generation in `apps/api/tests/unit/services/test_account_security_token_hashing.py`
- [X] T007 [P] Add failing settings tests for email/trusted-device rollout flags and cookie config in `apps/api/tests/unit/core/test_auth_settings_010.py`
- [X] T008 [P] Add failing OpenAPI/contract expectations for spec/010 auth deltas in `apps/api/tests/contract/test_auth_010_contract.py`

### Implementation

- [X] T009 Add Alembic migration for `users.email_verified_at`, `email_verification_tokens`, and `trusted_devices` in `apps/api/alembic/versions/00xx_email_verification_trusted_devices.py`
- [X] T010 Update `User` ORM with `email_verified_at` in `apps/api/echoroo/models/user.py`
- [X] T011 [P] Add `EmailVerificationToken` ORM model in `apps/api/echoroo/models/email_verification_token.py`
- [X] T012 [P] Add `TrustedDevice` ORM model in `apps/api/echoroo/models/trusted_device.py`
- [X] T013 Add token hashing/generation helpers for 43-character base64url secrets and HMAC-SHA-256 storage in `apps/api/echoroo/services/account_security_tokens.py`
- [X] T014 Add rollout settings for email enforcement, trusted-device registration, trusted-device bypass, cookie name, TTLs, and resend caps in `apps/api/echoroo/core/settings.py`
- [X] T015 Update public auth path allowlist for exact verify-email and resend routes in `apps/api/echoroo/core/auth_paths.py`
- [X] T016 Reconcile spec/010 auth/trusted-device contract deltas into canonical contract files under `specs/006-permissions-redesign/contracts/`
- [X] T017 Run foundational tests for migration, token hashing, settings, and contract expectations from `apps/api/tests/integration/migrations/test_email_verification_trusted_devices_schema.py`, `apps/api/tests/unit/services/test_account_security_token_hashing.py`, `apps/api/tests/unit/core/test_auth_settings_010.py`, and `apps/api/tests/contract/test_auth_010_contract.py`

**Checkpoint**: Schema/config/contracts are ready. User-story work can begin.

---

## Phase 3: User Story 1 - New User Verifies Email Address (Priority: P1) MVP

**Goal**: Registration creates an unverified user, issues a single-use verification token, sends a verification email, and `/web-api/v1/auth/verify-email` verifies the address.

**Independent Test**: Register a user, capture the verification email/outbox event, submit the token, confirm `email_verified_at` is set, and confirm token reuse/expiry/tampering fails.

### Tests for User Story 1

- [X] T018 [P] [US1] Replace 501-stub assertions with failing real verify-email route tests in `apps/api/tests/integration/api/web_v1/test_auth_verify_email.py`
- [X] T019 [P] [US1] Add failing concurrent token consume, reuse, and same-email invitation acceptance verification tests in `apps/api/tests/security/authentication/test_email_verification.py`
- [X] T020 [P] [US1] Add failing email verification service unit tests, including same-email invitation acceptance helper coverage, in `apps/api/tests/unit/services/test_email_verification_service.py`
- [X] T021 [P] [US1] Add failing verification email outbox handler registration test in `apps/api/tests/unit/workers/test_email_verification_dispatcher.py`
- [X] T022 [P] [US1] Add failing verify-email frontend unit tests in `apps/web/src/routes/(auth)/verify-email/verify-email.spec.ts`

### Implementation for User Story 1

- [X] T023 [P] [US1] Add email verification request/response schemas in `apps/api/echoroo/schemas/web_v1/auth.py`
- [X] T024 [P] [US1] Add email verification token repository in `apps/api/echoroo/repositories/email_verification_token.py`
- [X] T025 [US1] Implement token issue, atomic consume, supersede, same-email invitation acceptance verification helper, and audit-safe failures in `apps/api/echoroo/services/email_verification_service.py`
- [X] T026 [US1] Replace `AuthService.verify_email()` stub with delegation to the real verification service in `apps/api/echoroo/services/auth.py`
- [X] T027 [US1] Implement real `POST /web-api/v1/auth/verify-email` behavior in `apps/api/echoroo/api/web_v1/auth.py`
- [X] T028 [US1] Add verification email outbox event handler and worker registration in `apps/api/echoroo/workers/outbox_processor.py`
- [X] T029 [US1] Enqueue verification token and email outbox event during registration in `apps/api/echoroo/api/web_v1/auth.py`
- [X] T030 [US1] Update verify-email frontend page to handle success, invalid token, expired token, and reused token states in `apps/web/src/routes/(auth)/verify-email/+page.svelte`
- [X] T031 [US1] Connect same-email invitation acceptance to email verification in `apps/api/echoroo/api/web_v1/projects/_members.py`
- [X] T032 [US1] Run US1 backend and frontend tests from `apps/api/tests/integration/api/web_v1/test_auth_verify_email.py`, `apps/api/tests/security/authentication/test_email_verification.py`, and `apps/web/src/routes/(auth)/verify-email/verify-email.spec.ts`

**Checkpoint**: US1 is independently functional and demoable.

---

## Phase 4: User Story 2 - Unverified User Can Sign In But Protected Actions Are Blocked (Priority: P1)

**Goal**: Unverified users can authenticate and see account state, but protected actions fail with 403 `ERR_EMAIL_VERIFICATION_REQUIRED`; resend is rate-limited and anti-enumeration safe.

**Independent Test**: Log in as an unverified user, confirm current-user response exposes `email_verified_at = null`, attempt a protected action and receive 403, resend a verification email, verify email, then retry successfully.

### Tests for User Story 2

- [X] T033 [P] [US2] Add failing current-user `email_verified_at` integration tests in `apps/api/tests/integration/api/web_v1/test_users_me_email_verification.py`
- [X] T034 [P] [US2] Add failing protected-action enforcement tests and protected-endpoint inventory assertions in `apps/api/tests/security/authentication/test_email_verification_required.py`
- [X] T035 [P] [US2] Add failing resend rate-limit and anti-enumeration tests in `apps/api/tests/security/rate_limiting/test_email_verification_resend.py`
- [X] T036 [P] [US2] Add failing frontend auth-store/user-type tests for `email_verified_at` in `apps/web/src/lib/stores/auth.email-verification.test.ts`
- [X] T037 [P] [US2] Add failing UI tests for unverified account state and resend in `apps/web/src/routes/(app)/profile/email-verification.spec.ts`

### Implementation for User Story 2

- [X] T038 [P] [US2] Add `email_verified_at` to backend user response schemas in `apps/api/echoroo/schemas/user.py`
- [X] T039 [P] [US2] Replace frontend `is_verified` assumptions with `email_verified_at` in `apps/web/src/lib/types/index.ts`
- [X] T040 [US2] Update `/web-api/v1/users/me` to expose `email_verified_at` in `apps/api/echoroo/api/web_v1/users.py`
- [X] T041 [US2] Implement resend token issue, supersession, per-IP/per-email/per-user caps, and generic 202 behavior in `apps/api/echoroo/services/email_verification_service.py`
- [X] T042 [US2] Implement `POST /web-api/v1/auth/verify-email/resend` in `apps/api/echoroo/api/web_v1/auth.py`
- [X] T043 [US2] Implement `ERR_EMAIL_VERIFICATION_REQUIRED` enforcement middleware/dependency and protected endpoint inventory in `apps/api/echoroo/middleware/email_verification_enforcement.py`
- [X] T044 [US2] Wire email verification enforcement into FastAPI middleware/router setup in `apps/api/echoroo/main.py`
- [X] T045 [US2] Add audit-safe events for resend, blocked protected action, success, and failure in `apps/api/echoroo/services/email_verification_service.py`
- [X] T046 [US2] Update frontend auth store and API client types for `email_verified_at` in `apps/web/src/lib/stores/auth.svelte.ts`
- [X] T047 [US2] Add resend affordance and unverified account state in `apps/web/src/routes/(app)/profile/+page.svelte`
- [X] T048 [US2] Run US2 tests from `apps/api/tests/security/authentication/test_email_verification_required.py`, `apps/api/tests/security/rate_limiting/test_email_verification_resend.py`, and `apps/web/src/lib/stores/auth.email-verification.test.ts`

**Checkpoint**: US1 and US2 work independently; email enforcement can be toggled by flag.

---

## Phase 5: User Story 3 - User Trusts a Device After Successful 2FA (Priority: P2)

**Goal**: A user can explicitly trust a browser after successful TOTP/setup confirmation, creating a revocable trusted-device record and secure cookie.

**Independent Test**: Complete 2FA with `trust_device=true`, confirm secure cookie attributes, confirm only a hash is stored, list the trusted device, revoke it, and confirm the record is no longer active.

### Tests for User Story 3

- [X] T049 [P] [US3] Add failing trusted-device service unit tests for issue, hash-only storage, five-device cap, and auto-revoke in `apps/api/tests/unit/services/test_trusted_device_service.py`
- [X] T050 [P] [US3] Add failing cookie attribute security tests in `apps/api/tests/security/authentication/test_trusted_device_cookie.py`
- [X] T051 [P] [US3] Add failing 2FA trust-device integration tests in `apps/api/tests/integration/api/web_v1/test_auth_trusted_device.py`
- [X] T052 [P] [US3] Add failing account trusted-device list/revoke tests in `apps/api/tests/integration/api/web_v1/test_account_trusted_devices.py`
- [X] T053 [P] [US3] Add failing frontend trusted-devices API tests in `apps/web/src/lib/api/trusted-devices.test.ts`

### Implementation for User Story 3

- [X] T054 [P] [US3] Add trusted-device schemas in `apps/api/echoroo/schemas/web_v1/trusted_device.py`
- [X] T055 [P] [US3] Add trusted-device repository in `apps/api/echoroo/repositories/trusted_device.py`
- [X] T056 [US3] Implement trusted-device issue, hash, cap eviction, revoke, list, and audit-safe events in `apps/api/echoroo/services/trusted_device_service.py`
- [X] T057 [US3] Extend 2FA challenge and TOTP setup confirm request/response schemas with `trust_device`, `device_label`, and `trusted_device_created` in `apps/api/echoroo/schemas/web_v1/auth.py`
- [X] T058 [US3] Set trusted-device cookie after successful `/auth/2fa/challenge` when registration flag and `trust_device=true` allow it in `apps/api/echoroo/api/web_v1/auth.py`
- [X] T059 [US3] Set trusted-device cookie after successful `/auth/2fa/setup/totp/confirm` when registration flag and `trust_device=true` allow it in `apps/api/echoroo/api/web_v1/auth.py`
- [X] T060 [US3] Implement trusted-device list/revoke BFF routes in `apps/api/echoroo/api/web_v1/account_trusted_devices.py`
- [X] T061 [US3] Register trusted-device account routes in `apps/api/echoroo/api/web_v1/__init__.py`
- [X] T062 [US3] Add frontend trusted-device API client in `apps/web/src/lib/api/trusted-devices.ts`
- [X] T063 [US3] Add account security trusted-device list/revoke UI in `apps/web/src/routes/(app)/profile/+page.svelte`
- [X] T064 [US3] Add trust-device checkbox to login 2FA form in `apps/web/src/routes/(auth)/login/+page.svelte`
- [X] T065 [US3] Add trust-device checkbox to first-login TOTP setup confirmation in `apps/web/src/routes/(auth)/2fa-setup/+page.svelte`
- [X] T066 [US3] Run US3 backend and frontend tests from `apps/api/tests/integration/api/web_v1/test_auth_trusted_device.py`, `apps/api/tests/integration/api/web_v1/test_account_trusted_devices.py`, and `apps/web/src/lib/api/trusted-devices.test.ts`

**Checkpoint**: Users can create, see, and revoke trusted devices; no login bypass yet unless US4 is complete.

---

## Phase 6: User Story 4 - Trusted Device Skips Routine 2FA for Non-Privileged Login (Priority: P2)

**Goal**: A non-privileged user logging in with a valid trusted-device cookie receives a complete session instead of a routine TOTP challenge.

**Independent Test**: Trust a device, log out while preserving the trusted-device cookie, log in again from the same browser and confirm `login_state="complete"`; repeat without cookie, with revoked cookie, and with expired cookie to confirm 2FA is required.

### Tests for User Story 4

- [X] T067 [P] [US4] Add failing login response schema tests for `login_state="complete"` in `apps/api/tests/unit/schemas/test_auth_login_response_010.py`
- [X] T068 [P] [US4] Add failing trusted-device login bypass integration tests in `apps/api/tests/integration/api/web_v1/test_auth_trusted_device_login.py`
- [X] T069 [P] [US4] Add failing security tests for missing, malformed, revoked, expired, user-mismatched, stamp-mismatched, and recent-failure devices in `apps/api/tests/security/authentication/test_trusted_device_bypass.py`
- [X] T070 [P] [US4] Add failing Playwright same-browser/new-browser trusted-device login tests in `apps/web/tests/e2e/auth-trusted-device.spec.ts`
- [X] T071 [P] [US4] Add failing frontend login complete-state tests in `apps/web/src/routes/(auth)/login/login-trusted-device.spec.ts`

### Implementation for User Story 4

- [X] T072 [US4] Extend login response schemas to include complete state and discriminator-compatible typing in `apps/api/echoroo/schemas/web_v1/auth.py`
- [X] T073 [US4] Implement trusted-device lookup scoped by password-authenticated user in `apps/api/echoroo/services/trusted_device_service.py`
- [X] T074 [US4] Update `/web-api/v1/auth/login` to issue a real session for valid non-privileged trusted-device login in `apps/api/echoroo/api/web_v1/auth.py`
- [X] T075 [US4] Record audit-safe trusted-device accepted/rejected reasons in `apps/api/echoroo/services/trusted_device_service.py`
- [X] T076 [US4] Update frontend auth API types for `login_state="complete"` in `apps/web/src/lib/api/web-auth.ts`
- [X] T077 [US4] Update auth store login flow for complete trusted-device response in `apps/web/src/lib/stores/auth.svelte.ts`
- [X] T078 [US4] Update login page to skip TOTP UI on complete trusted-device response in `apps/web/src/routes/(auth)/login/+page.svelte`
- [X] T079 [US4] Run US4 tests from `apps/api/tests/security/authentication/test_trusted_device_bypass.py`, `apps/api/tests/integration/api/web_v1/test_auth_trusted_device_login.py`, and `apps/web/tests/e2e/auth-trusted-device.spec.ts`

**Checkpoint**: Routine non-privileged trusted-device login is independently functional.

---

## Phase 7: User Story 5 - Administrator and High-Risk Actions Remain Strongly Protected (Priority: P2)

**Goal**: Trusted devices do not weaken superuser/admin login, WebAuthn, destructive step-up, 2FA reset, API key issuance, ownership transfer, or other high-risk flows.

**Independent Test**: Create a trusted device for an elevated account, log in, then confirm admin/destructive operations still require WebAuthn or recent step-up and that security events revoke trusted devices.

### Tests for User Story 5

- [X] T080 [P] [US5] Add failing admin/superuser no-bypass tests in `apps/api/tests/security/authentication/test_trusted_device_admin_no_bypass.py`
- [X] T081 [P] [US5] Add failing trusted-device revocation and email-change verification reset matrix tests for password reset/change, email change, 2FA reset, account deletion, and security-stamp rotation in `apps/api/tests/security/authentication/test_trusted_device_revocation_events.py`
- [X] T082 [P] [US5] Add failing high-risk recent-step-up tests for API key issuance, ownership transfer, destructive project mutation, and mass export in `apps/api/tests/security/authentication/test_trusted_device_high_risk_step_up.py`
- [X] T083 [P] [US5] Add failing log/audit redaction tests for email verification and trusted-device events in `apps/api/tests/security/authentication/test_auth_event_redaction_010.py`

### Implementation for User Story 5

- [X] T084 [US5] Ensure trusted-device bypass rejects superuser/admin elevation contexts in `apps/api/echoroo/services/trusted_device_service.py`
- [X] T085 [US5] Integrate trusted-device bulk revocation into password reset confirmation in `apps/api/echoroo/api/web_v1/auth.py`
- [X] T086 [US5] Integrate trusted-device bulk revocation into 2FA reset completion in `apps/api/echoroo/services/two_factor_service.py`
- [X] T087 [US5] Integrate trusted-device bulk revocation into account deletion/anonymization in `apps/api/echoroo/services/user_deletion_service.py`
- [X] T088 [US5] Implement email-change security behavior in `apps/api/echoroo/services/user.py`: clear `email_verified_at`, supersede active verification tokens, send verification to the new address, notify the previous address when available, and revoke trusted devices
- [X] T089 [US5] Verify high-risk actions continue using existing step-up token dependency in `apps/api/echoroo/middleware/step_up.py`
- [X] T090 [US5] Add audit-safe event payloads for trusted-device revocation, rejected bypass, and high-risk step-up denials in `apps/api/echoroo/services/trusted_device_service.py`
- [X] T091 [US5] Run US5 security tests from `apps/api/tests/security/authentication/test_trusted_device_admin_no_bypass.py`, `apps/api/tests/security/authentication/test_trusted_device_revocation_events.py`, and `apps/api/tests/security/authentication/test_trusted_device_high_risk_step_up.py`

**Checkpoint**: Trusted-device convenience does not weaken privileged or high-risk security posture.

---

## Phase 8: Polish & Cross-Cutting Verification

**Purpose**: Final hardening, docs, rollout readiness, and full validation.

- [X] T092 [P] Add release readiness notes for email verification and trusted devices in `docs/runbook/release_readiness.md`
- [X] T093 [P] Add trusted-device operational runbook in `docs/runbook/trusted_devices.md`
- [X] T094 [P] Add email verification delivery and bounce/dead-letter runbook in `docs/runbook/email_verification.md`
- [X] T095 Add email delivery dead-letter/bounce alert verification to rollout checklist in `specs/010-email-verification-trusted-devices/rollout-checklist.md`
- [X] T096 Update `apps/api/README.md` with local verification email and trusted-device test instructions
- [X] T097 Update `apps/web/README.md` with local trusted-device browser testing notes
- [X] T098 Run backend focused suite from `apps/api/tests/integration/api/web_v1/test_auth_verify_email.py`, `apps/api/tests/security/authentication/test_email_verification.py`, `apps/api/tests/security/authentication/test_trusted_device_bypass.py`, and `apps/api/tests/security/authentication/test_auth_event_redaction_010.py`
- [X] T099 Run frontend focused suite from `apps/web/src/routes/(auth)/verify-email/verify-email.spec.ts`, `apps/web/src/routes/(auth)/login/login-trusted-device.spec.ts`, and `apps/web/tests/e2e/auth-trusted-device.spec.ts`
- [X] T100 Run contract and migration checks from `apps/api/tests/contract/test_openapi_diff.py` and `apps/api/tests/integration/migrations/test_email_verification_trusted_devices_schema.py`
- [X] T101 Validate `specs/010-email-verification-trusted-devices/quickstart.md` end-to-end and record results in `specs/010-email-verification-trusted-devices/quickstart-validation.md`
- [X] T102 Run API-key/programmatic auth regression and BFF mutual-rejection checks from `apps/api/tests/contract/test_auth_separation.py` and relevant `/api/v1` auth tests

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup & Inventory**: No dependencies.
- **Phase 2 Foundational**: Depends on Phase 1; blocks all user stories.
- **US1 (Phase 3)**: Depends on Phase 2; MVP.
- **US2 (Phase 4)**: Depends on US1 for `email_verified_at`, token issue/resend, and current-user schema.
- **US3 (Phase 5)**: Depends on Phase 2; can start after Foundation, but should not ship before US1/US2 if rollout wants email verification first.
- **US4 (Phase 6)**: Depends on US3 trusted-device persistence and cookie issuance.
- **US5 (Phase 7)**: Depends on US3/US4 trusted-device service; should complete before trusted-device bypass is enabled in production.
- **Phase 8 Polish**: Depends on selected stories being complete.

### User Story Dependencies

- **US1**: Independent MVP after Foundation.
- **US2**: Builds on US1 email state and resend.
- **US3**: Independent of US1/US2 at code level after Foundation, but product rollout should sequence after email verification.
- **US4**: Requires US3.
- **US5**: Requires US3 and US4 behavior to verify no weakening.

### TDD Order Within Each Story

1. Write failing tests for the story.
2. Implement models/repositories if needed.
3. Implement services.
4. Implement routes/middleware.
5. Implement frontend/API client changes.
6. Run story-specific verification before moving on.

---

## Parallel Execution Examples

### Setup

```text
Task: "Create canonical contract reconciliation checklist in specs/010-email-verification-trusted-devices/contract-reconciliation.md"
Task: "Create rollout Go/No-Go checklist in specs/010-email-verification-trusted-devices/rollout-checklist.md"
Task: "Audit existing frontend is_verified usage and record replacement plan in specs/010-email-verification-trusted-devices/frontend-type-audit.md"
```

### US1 Tests

```text
Task: "Replace 501-stub assertions with failing real verify-email route tests in apps/api/tests/integration/api/web_v1/test_auth_verify_email.py"
Task: "Add failing concurrent token consume and reuse tests in apps/api/tests/security/authentication/test_email_verification.py"
Task: "Add failing email verification service unit tests in apps/api/tests/unit/services/test_email_verification_service.py"
Task: "Add failing verify-email frontend unit tests in apps/web/src/routes/(auth)/verify-email/verify-email.spec.ts"
```

### US3 Tests

```text
Task: "Add failing trusted-device service unit tests for issue, hash-only storage, five-device cap, and auto-revoke in apps/api/tests/unit/services/test_trusted_device_service.py"
Task: "Add failing cookie attribute security tests in apps/api/tests/security/authentication/test_trusted_device_cookie.py"
Task: "Add failing account trusted-device list/revoke tests in apps/api/tests/integration/api/web_v1/test_account_trusted_devices.py"
Task: "Add failing frontend trusted-devices API tests in apps/web/src/lib/api/trusted-devices.test.ts"
```

### US5 Security Matrix

```text
Task: "Add failing admin/superuser no-bypass tests in apps/api/tests/security/authentication/test_trusted_device_admin_no_bypass.py"
Task: "Add failing trusted-device revocation matrix tests for password reset/change, email change, 2FA reset, account deletion, and security-stamp rotation in apps/api/tests/security/authentication/test_trusted_device_revocation_events.py"
Task: "Add failing high-risk recent-step-up tests for API key issuance, ownership transfer, destructive project mutation, and mass export in apps/api/tests/security/authentication/test_trusted_device_high_risk_step_up.py"
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2.
2. Complete US1 only.
3. Validate registration → verification email → token consume → `email_verified_at` end-to-end.
4. Stop and decide whether to ship email verification persistence before enforcement.

### Incremental Delivery

1. US1: real email verification.
2. US2: unverified account state and protected-action enforcement behind flag.
3. US3: trusted-device registration and revoke behind registration flag.
4. US4: trusted-device login bypass behind bypass flag.
5. US5: privileged/high-risk hardening before bypass rollout.

### Parallel Team Strategy

After Phase 2:

- Worker A can own US1 email verification service/routes/tests.
- Worker B can prepare US3 trusted-device model/service/tests in parallel, because it writes different files.
- Worker C can audit frontend type migration and UI tests, but must coordinate before editing `apps/web/src/lib/stores/auth.svelte.ts` because US2 and US4 both touch it.

### Notes

- Every task is written for TDD: test tasks precede implementation tasks in each story.
- `[P]` means different files and no dependency on an incomplete task in the same phase.
- Avoid concurrent edits to `apps/api/echoroo/api/web_v1/auth.py`, `apps/api/echoroo/schemas/web_v1/auth.py`, and `apps/web/src/lib/stores/auth.svelte.ts`; these are shared integration points.
- Do not enable enforcement or bypass flags by default until Phase 8 validation is complete.
