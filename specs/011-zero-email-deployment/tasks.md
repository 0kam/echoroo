# Tasks: Zero-email Deployment

**Branch**: `011-zero-email-deployment` | **Spec**: [spec.md](./spec.md) (Rev.3.2) | **Plan**: [plan.md](./plan.md) (Rev.2 + Rev.3.2 patches)
**Generated**: 2026-05-21
**Prerequisites**: plan.md, spec.md (Rev.3.2), research.md (Rev.2), data-model.md (Rev.2), contracts/{6 yaml} (Rev.2), quickstart.md (Rev.2). All converged by three-way review.

**Tests**: Tests are required by the constitution (Principle II — TDD NON-NEGOTIABLE) and listed explicitly per phase. The spec lists 7 acceptance criteria (US1-US7 Independent Tests, SC-1..SC-6) — every one is covered by a Playwright e2e or pytest task.

**Organization**: Tasks are grouped by user story (P1 first → P2). Phase 2 (Foundational) is a blocking prerequisite for every user story. The MVP is **US1 alone** (fresh deployment works without email).

## ⚠️ Reconciliation status (2026-05-31) — checkboxes were stale; true state below

A codebase reconciliation found many `[ ]` boxes were STALE (implemented in the 12-step-plan PRs #93-#105 but never checked). The boxes have now been synced to reality. **spec/011 is materially INCOMPLETE** — not a cleanup tail.

- **Done (backend core)**: US1 email removal, US2/US3/US6 invitation+bootstrap BACKEND (invitation_service, bulk SAVEPOINT, SU bootstrap ownership transfer), contracts, backend integration/security tests, runbooks, README docs (T180/T181/T191), and the foundational allowlist/settings (T013/T021/T022/T031/T090/T091/T092/T242/T244).
- **Done this slice (PR `011-residual-backend-slice`, 2026-05-31)**: **US5 T400** (fixed a real bug — admin 2FA-reset step-up scope `SCOPE_ADMIN_DESTRUCTIVE`→`SCOPE_ADMIN_RECOVERY`; no frontend caller existed so nothing broke), **T402** (`platform.user.two_factor_reset_by_superuser` audit emit with correct superuser.id→user_id self-reset detection), **T404** test; **foundational T020/T023/T024** (11 audit-action constants declared at owning services + A-13 PII-detector registration + `test_audit_action_constants_registered.py`); **T032/T033 decisions**: accepted the US4 `USER_SCOPED_ONLY` registration in `core/endpoint_allowlist.py` (no separate `AUTHENTICATED_SELF_NO_GATE` constant) and the existing `test_endpoint_coverage.py` `is_allowlisted` exemption as canonical (no separate `test_endpoint_coverage_hard_fail.py`).
- **GENUINELY REMAINING (large)**: **US7 banners/activity** T600-T663 (entire feature: `me.py` endpoints, the 5 email→audit emit rewrites T610-T617 that currently never surface banners, change_email cooldown T620/T621, banner GC T625, trusted-device revoke audit T630/T631, frontend T640-T643); **US2 public invite flow** T220/T223 (public invite resolver + new-user signup + client-side TOTP enroll page; auth.ts resolveInvitation/acceptInvitation) — **must be built under `(public)` NOT `(auth)` (token-leak via login redirect)**; **US2/US3 collaborators page** T221/T222/T280/T281 (single+bulk invite, listing, revoke — new `/collaborators` tab coexisting with `/members`); **T030/T034** (3 banner ACTIONs — need US7 endpoints); **Step 12b** Playwright e2e T192/T245/T292/T405/T544/T663/T740/T745. T180/T181 docs were already done.
- **Done this slice (PR `011-us6-su-bootstrap`, 2026-06-01)**: **T520** SU-bootstrap frontend (projects/new `intended_owner_email` SU-gated field + one-shot `InvitationUrlDialog` shown BEFORE redirect + 422 `ERR_INVALID_INTENDED_OWNER_EMAIL` mapping) + **invitation plumbing** (lib/types invitation type set + ProjectCreate{Request,Response}; projects.ts `create()`→ProjectCreateResponse + issue/list/bulk/revoke invitation methods unblocking the future collaborators PR; `InvitationUrlDialog.svelte` shared component, backdrop/Escape non-dismissive to protect the one-shot URL). Gate 1 (npm check 0 new) + review (mergeable, 2 plumbing-type nullability fixes applied) + Gate 3 (SU sees field → request carries intended_owner_email → 201 invitation_url → dialog before redirect; non-SU field absent from DOM; console 0). i18n: 8 keys en=ja. NOTE: chose IA = `/collaborators` coexists with `/members`; US2 new-user signup uses client-side TOTP secret generation (add `otpauth` dep in PR-1) since backend has no public TOTP-begin endpoint.
- **Done this slice (PR `011-us7-banner-backend`, 2026-06-01)**: **US7 BACKEND complete** — `me.py` banner/activity read API (T600-T602) gated via the **`USER_SCOPED_ONLY` allowlist path** (OQ1: the `Action` model has no user-self scope, so `gate_action(USER_BANNER_*)` is not representable; followed the step-up T031-T033 precedent → **T030/T034 reinterpreted = NO `actions.py` change**, 3 allowlist entries instead); `services/email.py` 5 stubs rewritten to **fresh-session audit emits each carrying `target_user_id`** (T610-T614, load-bearing for banner surfacing) + 4 workers switched off email/outbox onto audit emit (T615-T617); `change_email` 24h cool-off (409 `email_change_cooldown_active`) + banner + security_stamp-rotation session invalidation (T620/T621) — **the cool-off ALSO gates `self_password_change` AND legacy `UserService.change_password`** (FR-011-305; the legacy path was a review-found bypass, OQ14-adjacent); `trusted_device_service.revoke_all_for_user` reason-allowlist (**added `password_change`** so shipped self/legacy change-password flows don't ValueError) + `actor_user_id` param + fresh-session idempotent audit (one row even at count 0), all 6 call-sites remapped (T630/T631); `workers/banner_gc.py` daily Celery beat 03:30 aligned to `DEFAULT_BANNER_MAX_AGE_DAYS` (T625); `me-banners-activity` OpenAPI stem promoted PENDING→LIVE (T660); tests T661/T662 + GC + revoke-idempotent + cool-off. **Adversarial multi-lens review: 13 confirmed (1 medium FR-011-305 legacy-path bypass + 12 low: orphan-banner cross-tx ordering ×3 accepted per FR-088, hash-of-a-hash fixed, 7 test-file ruff nits) — all fixed or accepted-by-precedent.** Gate 1 ruff+mypy clean (branch code), Gate 2 ~140 tests pass / 0 regressions, Gate 3 N/A (no frontend in this slice). **Still REMAINING for US7: frontend T640-T643 + T663 Playwright e2e (slice D / Step 12b).**
- **Done this slice (PR `011-step7c-coverage`, 2026-05-31)**: **T190** fresh-deployment integration test; **Step 7c** coverage uplift PARTIAL — `middleware/rate_limit.py` (→100%) and `observability/sentry.py` (→94.4%) brought over threshold and removed from `PHASE17_PENDING` in `scripts/check_coverage_threshold.py`; `services/invitation_service.py` improved (error-branch unit tests added) but STAYS in `PHASE17_PENDING` (its SAVEPOINT ownership-transfer / trusted-invite paths need integration tests to cross the threshold — follow-up); `services/email.py` stays exempt (emit rewrites are US7 T610-T617, deferred).

## Format

`- [ ] [ID] [P?] [Story?] Description`

- `[P]`: parallelizable (different files, no in-phase deps)
- `[Story]`: `[US1]..[US7]` for user-story phases
- File paths are absolute relative to repo root unless otherwise noted

## Path Conventions

- Backend: `apps/api/echoroo/`
- Frontend: `apps/web/src/`
- Migrations: `apps/api/alembic/versions/`
- Tests: `apps/api/tests/` and `apps/web/tests/`
- Docs: `docs/operations/`, `docs/runbook/`
- Contracts: `specs/011-zero-email-deployment/contracts/`

---

## Phase 1: Setup

**Purpose**: Configuration scaffolding that blocks Phase 2.

- [x] T001 Verify feature branch `011-zero-email-deployment` is the active worktree branch and clean (`git status`)
- [x] T002 [P] Remove `resend` from `apps/api/pyproject.toml` `[project.dependencies]` AND regenerate `apps/api/uv.lock`. (Landed in Step 2 PR together with T100 services/email.py reduction; deferred from Step 0 because services/email.py needed the helper stubs first.)
- [x] T003 [P] Remove `RESEND_API_KEY=${RESEND_API_KEY:-}` line from `compose.dev.yaml`
- [x] T004 [P] Remove `RESEND_API_KEY=` line and any `EMAIL_FROM` entry from `.env.example`; add example placeholders for `INVITATION_TOKEN_KID_NEW`, `INVITATION_TOKEN_KID_OLD`, `INVITATION_TOKEN_HMAC_KEY`, `INVITATION_TOKEN_HMAC_KEY_OLD`, `INVITATION_TOKEN_KID_GRACE_HOURS` with explanatory comments

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema additions, action/middleware/audit/banner/step-up/invitation scaffolding that **every** user story depends on. No user story phase may begin until Phase 2 completes.

### Database

- [x] T010 Create migration `apps/api/alembic/versions/0021_zero_email_additive.py` (FR-011-002 partial / FR-011-122 / FR-011-203 / FR-011-301):
  - `users.must_change_password BOOLEAN NOT NULL DEFAULT false`
  - `users.temp_password_expires_at TIMESTAMPTZ NULL`
  - `users.email_change_cooldown_until TIMESTAMPTZ NULL` (grep-verified absent from current schema; required by FR-011-305 24h cool-off)
  - `project_invitations.ownership_transfer_on_accept BOOLEAN NOT NULL DEFAULT false`
  - CHECK `ck_project_invitations_ownership_transfer_kind_member`: `(ownership_transfer_on_accept = false OR kind = 'member')`
  - New table `user_banner_dismissals(user_id, audit_table, audit_log_id, dismissed_at)` with composite PK + CHECK `audit_table IN ('project_audit_log', 'platform_audit_log')` + FK only on `user_id` (polymorphic — no FK on audit_log_id; per data-model.md §user_banner_dismissals)
  - `downgrade()` raises (forward-only, NFR-011-002)
- [x] T011 Add `apps/api/tests/unit/test_migration_0021.py` (P): apply + rollback-raise tests; assert all columns/tables/CHECK constraints present after upgrade

### Settings + env validation

- [x] T012 In `apps/api/echoroo/core/settings.py` add the five new env vars (NFR-011-010, data-model.md §Settings):
  - `INVITATION_TOKEN_KID_NEW: str` (required at every boot)
  - `INVITATION_TOKEN_KID_OLD: str | None` (optional after grace)
  - `INVITATION_TOKEN_KID_GRACE_HOURS: int = 24`
  - `INVITATION_TOKEN_HMAC_KEY: str` (required at every boot)
  - `INVITATION_TOKEN_HMAC_KEY_OLD: str | None`
  - `model_validator(mode='after')` raises `ValueError` when `INVITATION_TOKEN_KID_OLD` is set without `INVITATION_TOKEN_HMAC_KEY_OLD` (and vice versa) — mirror the A-12 pattern at `core/settings.py:516-528`
- [x] T013 [P] **SPLIT ACROSS Step 2 / 3 / 10** — Remove the legacy email settings in the same PR as the consumer cleanup so settings + readers stay in sync: `RESEND_API_KEY`/`EMAIL_FROM` move to Step 2 (with `services/email.py` rewrite), `EMAIL_VERIFICATION_ENFORCEMENT_ENABLED` **deleted in Step 3 (this PR)** alongside the middleware atomic swap, `EMAIL_VERIFICATION_TOKEN_TTL_SECONDS` remains until Step 10 (`services/email_verification_service.py` deletion). Avoids `AttributeError` between PRs.
- [x] T014 [P] Add `apps/api/tests/unit/core/test_invitation_token_kid_settings.py`: assert presence, defaults, refuse-to-start co-presence validator

### Audit substrate

- [x] T020 Declare the 11 new audit-action constants (NFR-011-005) at the call-site / service-private level, matching the existing codebase convention (e.g. `services/two_factor_reset_service.py:125-141` declares `AUDIT_ACTION_REQUESTED = "two_factor_reset.requested"` etc.; `services/audit_service.py` does **not** carry such constants). Specifically:
  - `services/invitation_service.py` adds:
    - `AUDIT_ACTION_PROJECT_MEMBER_INVITE_ACCEPTED_SIGNUP = "project.member.invite_accepted_signup"`
    - `AUDIT_ACTION_PROJECT_MEMBER_INVITE_ACCEPTED = "project.member.invite_accepted"`
    - `AUDIT_ACTION_PROJECT_TRUSTED_USER_INVITE_ACCEPTED = "project.trusted_user.invite_accepted"`
    - `AUDIT_ACTION_PROJECT_OWNERSHIP_BOOTSTRAP_TRANSFER = "project.ownership.bootstrap_transfer"`
  - `services/admin_password_reset.py` (new, T310) adds:
    - `AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_BY_SUPERUSER = "platform.user.password_reset_by_superuser"`
    - `AUDIT_ACTION_PLATFORM_USER_PASSWORD_RESET_SELF = "platform.user.password_reset_self"`
  - `services/auth.py` (or wherever `LoginService` lives) adds:
    - `AUDIT_ACTION_AUTH_LOGIN_NEW_DEVICE = "auth.login.new_device"`
  - `services/api_key_lifecycle.py` (or wherever `revoke` is emitted) adds:
    - `AUDIT_ACTION_PLATFORM_API_KEY_REVOKE = "platform.api_key.revoke"`
  - `services/user.py` adds:
    - `AUDIT_ACTION_PLATFORM_USER_EMAIL_CHANGED = "platform.user.email_changed"`
  - `services/two_factor_reset_service.py` (or admin 2FA disable path) adds:
    - `AUDIT_ACTION_PLATFORM_USER_TWO_FACTOR_RESET_BY_SUPERUSER = "platform.user.two_factor_reset_by_superuser"`
  - `services/trusted_device_service.py` adds:
    - `AUDIT_ACTION_AUTH_TRUSTED_DEVICE_REVOKE_ALL = "auth.trusted_device.revoke_all"`
- [x] T021 In `apps/api/echoroo/services/audit_service.py` add `DESTRUCTIVE_ACTIONS: Final[frozenset[str]]` per research.md R6 (6 entries: `project.delete`, `dataset.delete`, `recording.delete`, `project.acl.update`, `project.permission.elevate`, `project.visibility.update`)
- [x] T022 In `apps/api/echoroo/services/audit_service.py` add `build_pre_transfer_action_summary(session, project_id, actor_user_id, since, until) -> dict` helper that queries `project_audit_log` rows for `actor_user_id == :actor AND project_id == :project AND created_at BETWEEN :since AND :until`, returning `{summary: [{action, timestamp, target_id?}]}` with `target_id` preserved iff `action ∈ DESTRUCTIVE_ACTIONS`
- [x] T023 [P] Register each of the 11 new audit-action strings and `DESTRUCTIVE_ACTIONS` with the Phase 17 A-13 operator free-form PII detector (NFR-011-005) — extend the existing detector registration test
- [x] T024 [P] Add `apps/api/tests/security/test_audit_action_constants_registered.py`: asserts every new constant is unique vs existing audit-action strings + appears in the PII detector allowlist

### ACTION constants + endpoint coverage allowlist

- [x] T030 (DONE via allowlist path — banner ACTIONs are `USER_SCOPED_ONLY` allowlist entries, NOT `actions.py` constants, since the `Action` model has no user-self scope; the 2 project/admin ACTIONs already existed) In `apps/api/echoroo/core/actions.py` add the five new ACTION constants (data-model.md §ACTION):
  - `PROJECT_MEMBER_INVITATION_ISSUE_ACTION` (PROJECT scope, `MANAGE_MEMBERS` required)
  - `ADMIN_USER_RESET_PASSWORD_ACTION` (USER scope, superuser-only)
  - `USER_BANNER_LIST_ACTION` (USER self-scope)
  - `USER_BANNER_DISMISS_ACTION` (USER self-scope)
  - `USER_ACTIVITY_LIST_ACTION` (USER self-scope)
- [x] T031 In `apps/api/echoroo/core/endpoint_allowlist.py` add `TOKEN_AUTH_ONLY` entries for `GET /web-api/v1/auth/invitations/{token}` and `POST /web-api/v1/auth/invitations/{token}/accept` (spec.md NFR-011-004)
- [x] T032 In `apps/api/echoroo/core/endpoint_allowlist.py` add `AUTHENTICATED_SELF_NO_GATE` entries (new allowlist; create the constant if absent) for `POST /web-api/v1/auth/step-up/begin` and `POST /web-api/v1/auth/step-up/complete` (spec.md NFR-011-004)
- [x] T033 Update `apps/api/tests/contract/test_endpoint_coverage_hard_fail.py` to recognise the new allowlists and exempt the four routes from `gate_action` requirement
- [x] T034 (DONE — allowlist path chosen, so no new Actions to register; `test_actions_coherence.py` + `test_endpoint_coverage_hard_fail.py` stay green with the 3 `USER_SCOPED_ONLY` entries) Update `apps/api/tests/contract/test_actions_coherence.py` (9-class coherence per spec/007) to register the five new ACTIONs with their scope / required_permission / superuser-only triple

### Step-up token extension (existing service)

- [x] T040 Extend `apps/api/echoroo/services/step_up_token_service.py`:
  - Add new scope constant `SCOPE_ADMIN_RECOVERY: Final[str] = "admin_recovery"`
  - Modify `StepUpTokenClaims` dataclass: add `factors: dict[str, Any] | None = None`
  - Add `issue_admin_recovery_step_up_token(*, user_id, security_stamp, assertion_id, password_verified: bool, second_factor: Literal["totp", "webauthn"]) -> tuple[str, datetime]` — payload `factors = {"password": password_verified, "second_factor": second_factor}`; scope `"admin_recovery"`
  - Modify `verify_step_up_token`: when `expected_scope == "admin_recovery"`, additionally require `payload["factors"]["password"] is True` and `payload["factors"]["second_factor"] in {"totp", "webauthn"}` — raise `StepUpTokenInvalidError` otherwise
- [x] T041 Extend `apps/api/echoroo/middleware/step_up.py`: `require_step_up_token(scope=SCOPE_ADMIN_RECOVERY)` factory variant (the existing factory already takes a scope parameter; ensure it works with the new constant) and the new error codes thread through correctly
- [x] T042 [P] Add `apps/api/tests/unit/services/test_step_up_admin_recovery_token.py`: issue + verify path, factors invariant enforced, scope confusion (admin_destructive token rejected for admin_recovery, vice versa), security_stamp rotation revocation

### Invitation envelope 4-part + outcome reshape

- [x] T050 In `apps/api/echoroo/services/invitation_service.py` extend `sign_invitation_token` to produce a 4-part envelope `{raw_token_b64u}.{exp_unix_ts}.{kid}.{mac_b64u}` where `mac = _b64u_encode(HMAC-SHA-256(secret_for(kid), raw + "." + exp + "." + kid))` and `kid` = `settings.INVITATION_TOKEN_KID_NEW`
- [x] T051 In `apps/api/echoroo/services/invitation_service.py` extend `verify_invitation_token` (the verification side) to accept either (a) a 4-part envelope routed by `kid` to `INVITATION_TOKEN_KID_NEW` / `_OLD` secret, or (b) a 3-part legacy envelope verified under `INVITATION_TOKEN_KID_OLD` secret iff within the grace window (`now < created_at + 7d + GRACE_HOURS`). Constant-time MAC comparison via `hmac.compare_digest` (NFR-011-003)
- [x] T052 Remove `InvitationMailPayload` dataclass from `apps/api/echoroo/services/invitation_service.py` (FR-011-104)
- [x] T053 In `apps/api/echoroo/services/invitation_service.py` replace the `mail_payload` field on `InvitationCreateOutcome` with `signed_token_envelope: str`. Consumers read it once and surface it on the API response; never persisted
- [x] T054 In `apps/api/echoroo/services/invitation_service.py` remove the outbox-email enqueue from `trigger_post_commit_side_effects` (FR-011-010 producer side)
- [x] T055 In `apps/api/echoroo/services/invitation_service.create_invitation` add the application-level guard (R5): if `ownership_transfer_on_accept=True AND kind != ProjectInvitationKind.MEMBER`, raise `InvitationStateError("ownership_transfer_on_accept_invalid_for_kind")` BEFORE INSERT
- [x] T056 In `apps/api/echoroo/services/invitation_service.accept_invitation` add the same R5 guard (defence-in-depth)
- [x] T057 [P] Add `apps/api/tests/security/test_invitation_token_kid_rotation.py` (NFR-011-010): planned rotation, emergency rotation, legacy 3-part within grace, legacy 3-part after grace, kid mismatch
- [x] T058 [P] Add `apps/api/tests/security/test_invitation_kind_guard.py` (R5): direct INSERT rejected by CHECK, `create_invitation` raises, `accept_invitation` raises

### Banner subsystem (write/enqueue side)

- [x] T060 Create `apps/api/echoroo/services/user_banner.py` with:
  - `dismiss(session, user_id, audit_table, audit_log_id) -> None` — validates row exists in named table AND (row.actor_user_id == user_id OR row.detail.target_user_id == user_id); 404-on-mismatch (FR-011-302, security review M-2)
  - `list_banners(session, user_id, max_age_days=30) -> list[BannerItem]` — joins `project_audit_log` + `platform_audit_log` against `user_banner_dismissals`
  - `list_activity(session, user_id, cursor, limit) -> ActivityPage` — full history view (FR-011-307)
  - `enqueue_event(session, user_id, audit_table, audit_log_id) -> None` — no-op shim (the audit write itself surfaces; this exists for callers that need to make the surface explicit)
- [x] T061 [P] Add `apps/api/tests/unit/services/test_user_banner.py`: list / dismiss / activity / age filtering / cross-user 404

### Forced-change middleware swap (atomic, FR-011-204 / NFR-011-007 / R8)

- [x] T070 Create `apps/api/echoroo/middleware/forced_password_change.py`:
  - `ForcedPasswordChangeMiddleware(BaseHTTPMiddleware)` returning 423 Locked + `Location: /change-password` for every path EXCEPT the allowlist (`POST /web-api/v1/auth/change-password`, `POST /api/v1/auth/change-password`, `POST /web-api/v1/auth/logout`, `POST /api/v1/auth/logout`, `GET /health`, `GET /metrics`, `GET /favicon.ico`, OPTIONS method on any path, static `/static/` prefix)
  - WebSocket scope close 1011 (future-proofing)
- [x] T071 In `apps/api/echoroo/main.py`, in a SINGLE commit (R8): register `ForcedPasswordChangeMiddleware` at the topological position previously occupied by `EmailVerificationEnforcementMiddleware` AND remove the registration of `EmailVerificationEnforcementMiddleware`. The old middleware source file remains on disk until Phase 3 (US1) deletion
- [x] T072 [P] Add `apps/api/tests/integration/test_must_change_password_middleware.py`: allowlist matrix (every path × method × scope), 423 vs pass-through, WebSocket 1011, v1 mirror coverage

### OpenAPI harness extension

- [x] T080 Extend `apps/api/tests/contract/test_openapi_diff.py`:
  1. Locate the hard-coded contracts directory constant (currently a single `pathlib.Path` pointing to `specs/006-permissions-redesign/contracts/` near line 47-50). Refactor it from a single `Path` to a tuple/list `_CONTRACTS_DIRS = (..., specs/006-... contracts, specs/011-zero-email-deployment/contracts)`.
  2. Update the assertion loop to iterate every directory in `_CONTRACTS_DIRS`, loading every `*.yaml` from each, and subset-asserting against the live FastAPI app's `openapi.json`.
  3. Add a regression assertion: spec/006 contracts must still pass byte-for-byte (sanity check that the refactor introduced no false negatives).
  4. The harness has no snapshot file — it reads YAML on each run and compares to live app. Document this in a module docstring so future contributors don't add snapshot-regeneration logic.
- [x] T081 [P] Add a meta-test `apps/api/tests/contract/test_openapi_diff_multi_spec.py` that verifies the multi-spec extension itself (e.g. all 6 spec/011 yaml files are loaded)

### CI guard + runbooks (skeleton)

- [x] T090 Create `apps/api/tests/contract/test_no_email_subsystem_traces.py` (R12): grep the regex from NFR-011-001 across `apps/`, `scripts/`, `compose.dev.yaml`, `.env.example`, `apps/api/README.md`, `README.md`, `.github/workflows/`, `docs/runbook/`, `apps/api/alembic/`; exclude itself and `*_legacy*.py`; fail on any match
- [x] T091 [P] Create skeleton `docs/runbook/invitation_token_kid_rotation.md` (R3) with sections: planned rotation, emergency rotation, forensic query for impacted invitations, initial-deploy first-time setup. Full content filled in Polish phase
- [x] T092 [P] Create skeleton `docs/runbook/zero-email-deployment-secret-rotation.md` (R2) listing CI/Actions secrets to delete (`RESEND_API_KEY`, `EMAIL_FROM`, `SMTP_*`)

### Email helper reduction (skeleton — full rewrite in Phase 9 US7)

- [x] T100 In `apps/api/echoroo/services/email.py`:
  - Delete the Resend SDK initialiser (`resend.api_key = settings.RESEND_API_KEY`)
  - Delete `send_verification_email`, `send_password_reset_email`, `send_2fa_reset_magic_link`
  - Leave the remaining 5 helpers as **no-op stubs** that log a warning (`send_login_notification`, `send_email_change_notification`, `send_2fa_reset_dispatched`, `send_api_key_scope_degrade_email`, `send_api_key_revoke_email`). Full rewrite-to-banner-enqueue lands in Phase 9 US7

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel.

---

## Phase 3: US1 — Fresh deployment without configuring email (Priority: P1) 🎯 MVP

**Goal**: A naive deployer can `docker compose up`, run `/setup/initialize`, and use Echoroo with zero email configuration. No "verify email" UI anywhere. Email-verification subsystem completely deleted.

**Independent Test**: All env vars unset, complete setup wizard, navigate primary screens, run `pytest test_no_email_subsystem_traces.py` — passes with zero matches outside spec/test/historical files.

### Backend deletions

- [x] T110 [US1] [P] Delete `apps/api/echoroo/services/email_verification_service.py` (FR-011-001..004)
- [x] T111 [US1] [P] Delete `apps/api/echoroo/models/email_verification_token.py` (FR-011-002)
- [x] T112 [US1] [P] Delete `apps/api/echoroo/models/password_reset_token.py` (FR-011-003)
- [x] T113 [US1] [P] Delete `apps/api/echoroo/repositories/email_verification_token.py` (and `repositories/password_reset_token.py` if present)
- [x] T114 [US1] [P] Delete `apps/api/echoroo/middleware/email_verification_enforcement.py` (FR-011-004) — the registration was already removed in T071
- [x] T115 [US1] [P] Delete `apps/api/echoroo/workers/email_verification_dispatcher.py` (FR-011-010)
- [x] T116 [US1] [P] Update `apps/api/echoroo/workers/celery_app.py` to remove the `email_verification_dispatcher` Celery include
- [x] T117 [US1] In `apps/api/echoroo/models/__init__.py` remove re-exports of `EmailVerificationToken`, `PasswordResetToken`
- [x] T118 [US1] In `apps/api/echoroo/models/user.py` remove `email_verified_at` field (FR-011-002)
- [x] T119 [US1] [P] In `apps/api/echoroo/api/web_v1/auth.py` delete all `/verify-email*`, `/password-reset/*`, `/2fa-reset/magic-link*` route handlers and their rate-limit primitives (FR-011-005)
- [x] T120 [US1] [P] In `apps/api/echoroo/api/v1/auth.py` delete the v1 mirrors of the above
- [x] T121 [US1] [P] In `apps/api/echoroo/services/auth.py` delete legacy `verify_email`, `request_password_reset`, `confirm_password_reset` functions and the `EmailVerificationService` import
- [x] T122 [US1] [P] In `apps/api/echoroo/api/web_v1/projects/_members.py` remove the `EmailVerificationService(db).mark_verified_from_same_email_invitation()` call-sites
- [x] T123 [US1] [P] In `apps/api/echoroo/services/user.py` remove the `email_verified_at = None` reset on email change (only the reset; the broader change-email flow is wired in Phase 9 US7)
- [x] T124 [US1] [P] In `apps/api/echoroo/services/setup.py` and `apps/api/echoroo/scripts/init_superuser.py` remove every reference to `email_verified_at` (FR-011-009)
- [x] T125 [US1] [P] In `apps/api/echoroo/services/two_factor_reset_service.py` remove the `send_2fa_reset_magic_link` call-site (the self-service magic-link path is dead in this spec)
- [x] T126 [US1] [P] In `apps/api/echoroo/schemas/web_v1/auth.py` remove `email_verification_required` field
- [x] T127 [US1] [P] In `apps/api/echoroo/schemas/setup.py` and `apps/api/echoroo/schemas/user.py` remove `email_verified_at` field; add `must_change_password` to User schema
- [x] T128 [US1] [P] In `apps/api/echoroo/core/auth_paths.py` remove `/verify-email`, `/password-reset`, `/2fa-reset/magic-link` from `PUBLIC_AUTH_PATHS`. Do NOT add `/auth/change-password` to PUBLIC_AUTH_PATHS (security review M7 — it's in the middleware allowlist instead, T070)
- [x] T129 [US1] [P] In `apps/api/echoroo/core/endpoint_allowlist.py` remove the 3 verify/resend entries (related to FR-011-005)

### Frontend deletions

> **Step 10b completion (2026-05-31)** — frontend email-UI removal done on branch `011-step10b-email-ui-removal`. Deleted `(auth)/verify-email/`, `forgot-password/`, AND `reset-password/` (the email-magic-link reset, dead now that backend password-reset endpoints are gone; NOT the US4 `change-password/` page). Removed the login forgot-password link, `/forgot-password`+`/verify-email` from `hooks.server.ts` AUTH_ROUTES + `auth.svelte.ts` NO_REDIRECT_PATH_SEGMENTS, the profile/dashboard email-verify badges + `isEmailVerified`, the `verifyEmail`/`resendVerificationEmail`/`requestPasswordReset`/`confirmPasswordReset` client methods (auth.ts + web-auth.ts) + CSRF_EXEMPT entries, `email_verified_at` from `User`/`SetupUserResponse`, the orphaned `PasswordResetRequest`/`PasswordResetConfirm`/`EmailVerifyRequest` types, and 16 i18n keys. `must_change_password` (US4) KEPT. Gate 1 (npm check 0 new) + code review (zero live dangling refs, no over-deletion) + Gate 3 smoke (login/dashboard/profile clean, deleted routes 404, /change-password intact, console clean) + vitest 64/64 (Trusted Device preserved); i18n parity en=ja. **Still open: T180/T181 (README SMTP/Resend/Mailpit doc cleanup) — separate docs follow-up.**

- [x] T140 [US1] [P] Delete `apps/web/src/routes/(auth)/verify-email/` directory
- [x] T141 [US1] [P] Delete `apps/web/src/routes/(auth)/forgot-password/` directory (if present)
- [x] T142 [US1] [P] Delete `apps/web/src/routes/(auth)/2fa-reset/` magic-link path (if present)
- [x] T143 [US1] [P] In `apps/web/src/routes/(auth)/login/+page.svelte` remove any link to `/forgot-password` or `/2fa-reset/magic-link`
- [x] T144 [US1] [P] In `apps/web/src/hooks.server.ts` remove `email_verified_at` from the session shape
- [x] T145 [US1] [P] In `apps/web/src/routes/(app)/profile/+page.svelte` remove the email-verify badge
- [x] T146 [US1] [P] In `apps/web/src/routes/(app)/dashboard/+page.svelte` remove the `isEmailVerified` derived
- [x] T147 [US1] [P] In `apps/web/src/lib/api/auth.ts` remove `verifyEmail`, `resendVerification`, `requestPasswordReset` client methods
- [x] T148 [US1] [P] In `apps/web/src/lib/api/web-auth.ts` mirror T147 edits (if the parallel client surface exists)
- [x] T149 [US1] [P] In `apps/web/src/lib/types/index.ts` remove `email_verified_at` from `User` and derived types; add `must_change_password`
- [x] T150 [US1] [P] In `apps/web/src/lib/stores/auth.svelte.ts` remove `email_verified_at` references; add `must_change_password` derived
- [x] T151 [US1] [P] In `apps/web/messages/en.json` and `apps/web/messages/ja.json` remove every email-verification key

### Test deletions

- [x] T160 [US1] [P] Delete `apps/api/tests/security/authentication/test_email_verification_required.py`
- [x] T161 [US1] [P] Delete `apps/api/tests/unit/middleware/test_email_verification_enforcement.py`
- [x] T162 [US1] [P] In `apps/api/tests/unit/core/test_auth_settings_010.py` trim verification-only fields
- [x] T163 [US1] [P] In `apps/api/tests/integration/test_setup_flow.py` remove email-verification assertions
- [x] T164 [US1] [P] Delete `apps/web/src/routes/(auth)/verify-email/verify-email.spec.ts`
- [x] T165 [US1] [P] Delete `apps/web/src/routes/(app)/profile/email-verification.spec.ts` (if present)
- [x] T166 [US1] [P] Delete `apps/web/src/lib/stores/auth.email-verification.test.ts`
- [x] T167 [US1] [P] In `apps/web/src/routes/(auth)/login/login-trusted-device.spec.ts` trim fixture references to `email_verified_at`; preserve Trusted Device assertions (spec/010 in-scope)
- [x] T168 [US1] [P] In `apps/web/tests/e2e/auth.spec.ts` (or equivalent) remove verify-email walkthroughs

### Docs

- [x] T180 [US1] [P] Update root `README.md` quickstart section to remove SMTP / Resend / Mailpit / DKIM / DNS as setup steps
- [x] T181 [US1] [P] Update `apps/api/README.md` to remove the same references

### US1 acceptance tests

- [x] T190 [US1] [P] Add integration `apps/api/tests/integration/test_fresh_deployment_no_email_state.py` (FR-011-009, US1 AC1-2): setup wizard creates user with no `email_verified_at` column reference, `/users/me` response has no `email_verification_required` field
- [x] T191 [US1] Run `pytest apps/api/tests/contract/test_no_email_subsystem_traces.py` and verify ZERO matches outside Spec / Revision History / itself (US1 AC3)
- [ ] T192 [US1] [P] Add Playwright e2e `apps/web/tests/e2e/no-email-ui-fresh-deployment.spec.ts` (US1 AC1-3): bring up with no env vars, complete setup, navigate Profile + Dashboard + Settings, assert no "verify email" / "メール認証" UI anywhere

**Checkpoint**: US1 deliverable complete — fresh deployment runs end-to-end with zero email configuration.

---

## Phase 4: US2 — Single-collaborator invitation (Priority: P1)

**Goal**: Project admin issues an invitation to one email + role, receives a one-shot URL, hands it off out-of-band. Recipient (new or existing user) opens the URL and lands in the project at the chosen role.

**Independent Test**: As project admin, issue invitation for `alice@univ.edu` + `member`, receive URL in response, open URL in a separate browser session, complete signup, verify Alice appears in project membership at role=member.

### Backend

- [x] T200 [US2] Add `POST /web-api/v1/projects/{project_id}/invitations` to `apps/api/echoroo/api/web_v1/projects/_members.py` (FR-011-101). Body: `{email, role}` (no `ttl_seconds` override per spec). Response: `{invitation_id, invitation_url, expires_at, bound_email_hash}` with `Cache-Control: no-store, no-cache, must-revalidate, private`. Gate via `gate_action(PROJECT_MEMBER_INVITATION_ISSUE_ACTION)`. The invitation_url is the new 4-part envelope token (T050)
- [x] T201 [US2] [P] Add `GET /web-api/v1/projects/{project_id}/invitations` to list invitations (already partly exists per spec/006; extend to include kind=member rows alongside trusted). FR-011-108
- [x] T202 [US2] Add `GET /web-api/v1/auth/invitations/{token}` resolver to `apps/api/echoroo/api/web_v1/auth.py` (FR-011-105, FR-011-107). TOKEN_AUTH_ONLY. Optional session cookie. Returns `InvitationContext` with `is_logged_in` and `authenticated_email_matches_bound` flags. 404 generic with 300ms±50ms timing pad
- [x] T203 [US2] Add `POST /web-api/v1/auth/invitations/{token}/accept` to `apps/api/echoroo/api/web_v1/auth.py` (FR-011-105, FR-011-106). TOKEN_AUTH_ONLY. Body shape branches on `is_logged_in` (NewUserPayload vs `{accept: true}` ExistingUserPayload). Returns `AcceptResponse` with required `kind` field
- [x] T204 [US2] Modify `accept_invitation` in `apps/api/echoroo/services/invitation_service.py` to support the existing-user branch (R11): branch on auth state, use existing `canonicalize_email` (NFKC + casefold) for bound-email comparison, return 409 when caller is already a member of the project at the same or higher role
- [x] T205 [US2] In `accept_invitation` implement the FR-011-106 SQL atomicity pattern: `UPDATE project_invitations SET status='accepted', accepted_at=now() WHERE id=:id AND status='pending' AND expires_at > now() RETURNING *` with named placeholders only; zero rows → abort + generic invalid response
- [x] T206 [US2] [P] Add per-IP (10/min) and global (200/min) rate-limit + constant 200-400ms timing pad to `/auth/invitations/*` per Phase 17 A-6 pattern (NFR-011-006)
- [x] T207 [US2] Modify `POST /web-api/v1/projects/{project_id}/trusted-users` response in `apps/api/echoroo/api/web_v1/trusted.py` to include `invitation_url` field; remove outbox-email enqueue (FR-011-103). This formally supersedes spec/006 FR-051
- [x] T208 [US2] Audit-action emission on accept (T020 constants): `project.member.invite_accepted_signup` for new-user signup, `project.member.invite_accepted` for existing-user accept, `project.trusted_user.invite_accepted` for trusted-overlay path

### Frontend

- [ ] T220 [US2] [P] Create `apps/web/src/routes/(auth)/invite/[token]/+page.svelte`: resolver fetch, signup form vs accept confirmation per `is_logged_in`, bound email read-only, 2FA enrollment integration
- [ ] T221 [US2] [P] In `apps/web/src/routes/(app)/projects/[id]/collaborators/+page.svelte` add single-invite form (email + role selector + Issue button + one-shot URL display with Copy)
- [ ] T222 [US2] [P] In `apps/web/src/routes/(app)/projects/[id]/collaborators/+page.svelte` extend the invitation listing to show kind=member rows with revoke button (FR-011-108)
- [ ] T223 [US2] [P] In `apps/web/src/lib/api/auth.ts` add `acceptInvitation` client method (handles both new-user signup and existing-user confirmation payloads)

### Contracts + tests

- [x] T240 [US2] [P] Validate `specs/011-zero-email-deployment/contracts/member-invitations.yaml` against the live FastAPI app (`pytest test_openapi_diff.py`); fix YAML or app discrepancies in this PR — single-invite + listing endpoints land in this PR; YAML's bulk + revoke routes remain part of Step 8, so the stem stays in `_SPEC_011_PENDING_STEMS` until Step 8 promotes it
- [x] T241 [US2] [P] Validate `specs/011-zero-email-deployment/contracts/invitation-public.yaml` against the live app — stem promoted to `_SPEC_011_LIVE_CONTRACT_STEMS`
- [x] T242 [US2] [P] Validate `specs/011-zero-email-deployment/contracts/trusted-users-invitation-url.yaml` against the live app (after T207)
- [x] T243 [US2] [P] Add `apps/api/tests/integration/test_member_invitation_flow.py` (FR-011-101..109): issue → resolve → accept (new user) → membership row check; issue → resolve → accept (existing user) → no duplicate user; mismatched email → generic invalid
- [x] T244 [US2] [P] Already added in T057 (`test_invitation_token_kid_rotation.py`); confirm it covers the FR-011-105 resolver
- [ ] T245 [US2] [P] Add Playwright e2e `apps/web/tests/e2e/single-invitation-flow.spec.ts` (US2 AC1-6): admin issues, copy URL, second browser opens, signup, lands in project at correct role; repeat for existing-user variant; 409 for already-member

**Checkpoint**: US2 deliverable complete.

---

## Phase 5: US3 — Bulk-invitation (Priority: P1)

**Goal**: Admin pastes up to 50 emails, gets a CSV of URLs in one response. Per-issuer global rate-limit (200/h, 1000/d) enforced.

**Independent Test**: Submit 10 valid emails + 1 role, verify exactly 10 invitations created and URLs returned as a top-level JSON array.

### Backend

- [x] T260 [US3] Add `POST /web-api/v1/projects/{project_id}/invitations/bulk` endpoint to `apps/api/echoroo/api/web_v1/projects/_members.py` (FR-011-110). Body: `{role, emails: [<=50]}`. Response: top-level array of `{email, status, invitation_url?, invitation_id?, error_message?}` per FR-011-113 (NOT object-wrapped)
- [x] T261 [US3] Bulk validation (FR-011-111): pre-INSERT pass that rejects entire request if any email is malformed OR `len(set(canonicalize_email(e) for e in emails)) != len(emails)` (in-list duplicate)
- [x] T262 [US3] Per-row SAVEPOINT semantics (NFR-011-008): each issuance inside its own SAVEPOINT; per-row failure (duplicate_pending / rate_limited) reported in the row without rolling back successful rows
- [x] T263 [US3] Add per-issuer global rate-limit at 200/hour and 1000/day across all projects (FR-011-114), sliding window via existing Phase 17 A-6 pattern
- [x] T264 [US3] [P] Audit-action emission: same `project.member.invite_accepted_signup` per row's eventual accept; each issuance row gets a separate `project.invitation.create` (existing) audit entry

### Frontend

- [ ] T280 [US3] [P] In `apps/web/src/routes/(app)/projects/[id]/collaborators/+page.svelte` add bulk-mode toggle, newline-separated email paste textarea, single role selector, submit; render result table with "Copy all as CSV" affordance
- [ ] T281 [US3] Verify URLs are NOT recoverable after navigation (FR-011-110 / FR-011-113); add a UI warning to that effect

### Contracts + tests

- [x] T290 [US3] [P] Update `specs/011-zero-email-deployment/contracts/member-invitations.yaml` bulk path to reflect the live shape, re-run `test_openapi_diff.py`
- [x] T291 [US3] [P] Add `apps/api/tests/integration/test_bulk_invitation.py` (FR-011-110..115): success with 10 emails, in-list duplicate rejection, per-row duplicate_pending, malformed email rejection (atomic), rate-limit enforcement
- [ ] T292 [US3] [P] Add Playwright e2e `apps/web/tests/e2e/bulk-invitation-flow.spec.ts` (US3 AC1-6): paste 5 emails, submit, verify 5 URLs in result table, each redeems independently

**Checkpoint**: US3 deliverable complete.

---

## Phase 6: US4 — Admin password reset (Priority: P1)

**Goal**: System superuser completes step-up (password + 2FA) → resets target user's password → temp password revealed once → target user logs in → forced-change middleware blocks every route until they pick a new password.

**Independent Test**: As superuser, step-up + reset user; second session logs in with temp password → 423 Locked on `/dashboard`; submit new password → free.

### US4 completion (2026-05-31) — PR (branch `011-us4-admin-password-reset`)

US4 is complete. Step-up + admin-reset backend (T300/T301/T302/T310/T311/T312) shipped earlier in **PR #126**; this branch adds the self change-password endpoint (T320/T321), the full frontend UX (T149-subset / T340-T343), the contract alignment (T360 for change-password), and the tests (T361 integration, T362 env-gated Playwright e2e). The current session SURVIVES change-password (FR-011-205: BFF re-issues cookies + a fresh access_token; other sessions stay invalidated via the rotated security_stamp). Internal 4-lens adversarial review (13 raised → 9 confirmed → all fixed) + 2 Gate-3-discovered FE auth-wiring bugs fixed: (a) `postAuth` now attaches the `Authorization: Bearer` in-memory token (authenticated auth POSTs were 401ing), (b) `changePassword` consumes the returned `access_token` and `completeLogin`/`initialize()` route a 423 `ERR_PASSWORD_CHANGE_REQUIRED` to `/change-password` (a freshly-reset user was stranded on a blank dashboard). Gate 1/2/3/4 all green; full natural flow (login → auto /change-password → change → dashboard with surviving session) verified in-browser. **NOTE**: T342's real path is `apps/web/src/routes/(admin)/admin/users/+page.svelte` (the `(admin)` group), NOT `(app)` as written below. T149 here is only the additive `must_change_password` field subset; the `email_verified_at` removal remains in the Step 10b cluster. `reason` input omitted in v1; roster badge deferred; WebAuthn step-up deferred to a follow-up spec.

### Backend — step-up endpoints

- [x] T300 [US4] Add `POST /web-api/v1/auth/step-up/begin` to `apps/api/echoroo/api/web_v1/auth.py`. Body: `{scope: "admin_recovery"}`. Returns challenge_id (UUID4) + factors_required. AUTHENTICATED_SELF_NO_GATE (T032). **TOTP-only initial release** (2026-05-29 closeout): factors_required advertises `["password", "totp"]`; WebAuthn-only users receive 409 (`step_up_2fa_not_enrolled`). WebAuthn step-up issuance is reserved for a follow-up task / spec.
- [x] T301 [US4] Add `POST /web-api/v1/auth/step-up/complete` to `apps/api/echoroo/api/web_v1/auth.py`. Body: `{challenge_id, factors: {password, totp_code}}`. Returns step_up_token (5min TTL). **Server-side MUST verify password against stored hash before setting factors.password=true** (security review M-1). **TOTP-only initial release**: the WebAuthn variant declared in earlier YAML revisions has been removed; the request schema is flat (no oneOf). The 401 envelope is uniform (`error_code = "step_up_factor_invalid"`) across password / TOTP / challenge mismatch / challenge expired to avoid a per-factor side channel; the internal failure reason is captured only on the platform audit log. The Redis challenge record is fetched-and-deleted via `GETDEL` in a single round-trip so concurrent completes cannot both succeed. **Round 2 timing-oracle defence (2026-05-29)**: the handler MUST verify password AND TOTP unconditionally on every request — short-circuiting on password failure surfaces an argon2-cost timing channel that lets a stolen-session attacker probe password correctness. The AND-condition collapses at the very end so only the single "any factor failed" bit leaks via the unified 401 envelope.
- [x] T302 [US4] [P] Add `apps/api/tests/security/test_step_up_complete_password_verify_invariant.py` (security review M-1): wrong password returns 401, correct password issues JWT with `factors.password=true`, invariant enforced even when payload claims `factors.password=true`

### Backend — admin reset

- [x] T310 [US4] Create `apps/api/echoroo/services/admin_password_reset.py` with `reset_password(session, actor_id, target_user_id, reason) -> str` (returns the one-time temp password). Generates random password meeting policy, sets `users.must_change_password=true`, `users.temp_password_expires_at=now()+24h`, invalidates target's other sessions, calls existing `TrustedDeviceService.revoke_all_for_user(target_user)` (R10 reuse), emits `platform.user.password_reset_by_superuser` audit (or `_self` for self-reset). Temp password is NOT written anywhere except `users.password_hash`
- [x] T311 [US4] Add `POST /web-api/v1/admin/users/{user_id}/reset-password` to `apps/api/echoroo/api/web_v1/admin.py`. Gate via `gate_action(ADMIN_USER_RESET_PASSWORD_ACTION)` (superuser-only) and `require_step_up_token(SCOPE_ADMIN_RECOVERY)` middleware. Response includes `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, click-to-reveal payload with clipboard auto-clear after 60s. Body: `{reason?}` (free-form, A-13 PII detector applies)
- [x] T312 [US4] [P] Add `apps/api/tests/security/test_step_up_required_for_admin_recovery.py`: every recovery endpoint (this T311 + 2FA disable in Phase 7) rejects requests without admin_recovery step-up token; rejects WebAuthn-only `admin_destructive` tokens

### Backend — change-password + forced-change

- [x] T320 [US4] Add `POST /web-api/v1/auth/change-password` AND `POST /api/v1/auth/change-password` (v1 mirror, FR-011-204..205). CSRF-protected (`x-csrf-required: true`). Body: `{current_password, new_password}`. `current_password` accepts the live password OR the temp password during its 24h TTL. On success clears `must_change_password` and `temp_password_expires_at`, invalidates target's other sessions, calls `TrustedDeviceService.revoke_all_for_user`
- [x] T321 [US4] [P] In `apps/api/echoroo/core/auth_paths.py` register `/auth/change-password` in the ForcedPasswordChangeMiddleware allowlist (NOT in PUBLIC_AUTH_PATHS — already enforced in T070/T128, this is reinforcement)

### Frontend

- [x] T340 [US4] [P] Create `apps/web/src/routes/(auth)/change-password/+page.svelte`: forced-change screen, current + new password fields, success redirects to dashboard
- [x] T341 [US4] [P] In `apps/web/src/lib/api/auth.ts` add `changePassword` client method
- [x] T342 [US4] [P] In `apps/web/src/routes/(app)/admin/users/+page.svelte` add "Reset password" button per user row; step-up modal (password + TOTP, **TOTP-only initial release** — the frontend MUST NOT render a WebAuthn branch; WebAuthn step-up is reserved for a follow-up spec); reveal dialog with copy + auto-clear timer
- [x] T343 [US4] [P] In `apps/web/src/lib/stores/auth.svelte.ts` use the `must_change_password` derived (added in T150) to enforce a route guard: redirect to `/change-password` for any non-allowlisted route

### Contracts + tests

- [x] T360 [US4] [P] Validate `specs/011-zero-email-deployment/contracts/admin-password-reset.yaml` against the live app; fix any drift
- [x] T361 [US4] [P] Add `apps/api/tests/integration/test_admin_password_reset.py` (FR-011-201..210): superuser does step-up → reset → temp password returned once; target user logs in with temp password; forced-change middleware blocks other routes; submits new password; old sessions invalidated; trusted devices revoked; audit entry exists with NO temp password value; admin self-reset uses `_self` audit type
- [x] T362 [US4] [P] Add Playwright e2e `apps/web/tests/e2e/admin-password-reset.spec.ts` (US4 AC1-7): full flow including step-up modal, reveal dialog, target user forced-change UX, 24h TTL expiry path

**Checkpoint**: US4 deliverable complete.

---

## Phase 7: US5 — Admin 2FA reset (Priority: P2)

**Goal**: Existing admin 2FA disable flow per Phase 17 A-11 still works; now enforces step-up, emits banner audit, revokes target sessions + trusted devices, sends no email.

**Independent Test**: Trigger admin 2FA disable; observe step-up enforced; target sessions invalidated; trusted devices revoked; banner audit emitted; zero email side effects.

- [x] T400 [US5] In `apps/api/echoroo/services/two_factor_service.py` (or `two_factor_reset_service.py` admin-disable path) wire `require_step_up_token(SCOPE_ADMIN_RECOVERY)` to the admin-disable endpoint
- [x] T401 [US5] [P] On admin 2FA disable, invalidate target's other sessions + call `TrustedDeviceService.revoke_all_for_user(target_user)` (FR-011-306, FR-011-402)
- [x] T402 [US5] [P] On admin 2FA disable, emit `platform.user.two_factor_reset_by_superuser` audit (T020) — replaces the previous outbound email
- [x] T403 [US5] [P] Remove the `send_2fa_reset_magic_link` call-site from `apps/api/echoroo/services/two_factor_reset_service.py` (T100 stubbed it; T403 deletes the call). Also drops the now-unreferenced `send_2fa_reset_magic_link` helper + `EmailDeliverySuppressed` exception from `services/email.py` and updates integration tests that monkeypatched the deleted symbol.
- [x] T404 [US5] [P] Add `apps/api/tests/integration/test_admin_2fa_reset_side_effects.py`: step-up enforced, sessions invalidated, trusted devices revoked, audit emitted, no email enqueued
- [ ] T405 [US5] [P] Add Playwright e2e `apps/web/tests/e2e/admin-2fa-reset.spec.ts` (US5 AC1): admin disables target user's 2FA, target re-enrolls successfully

**Checkpoint**: US5 deliverable complete.

---

## Phase 8: US6 — Superuser project bootstrap (Priority: P2)

**Goal**: SU creates a project with `intended_owner_email = alice@univ.edu` → project initially owned by SU + Admin invitation issued for Alice with `ownership_transfer_on_accept = true` → URL returned in response → Alice accepts → ownership transferred to Alice + SU demoted to Admin + composite audit entry includes `pre_transfer_action_summary`.

**Independent Test**: As SU, create project with intended_owner_email; verify ownership; accept as Alice in separate session; verify `owner_id = Alice`, SU is Admin, audit row has pre_transfer_action_summary JSON.

### Backend

- [x] T500 [US6] Extend the project creation endpoint in `apps/api/echoroo/api/web_v1/projects/_core.py` to accept optional `intended_owner_email`. Silently drop server-side unless caller has `users.is_superuser=true` — FR-011-120 / FR-011-125. Same response shape SU and non-SU (anti-enumeration)
- [x] T501 [US6] When SU supplies `intended_owner_email`, atomically (single TX): create project with `owner_id=superuser.id`, issue `kind=member, role=ADMIN` invitation with `ownership_transfer_on_accept=true`, return both in response with `invitation_url`. Always set `Cache-Control: no-store` on create-project response
- [x] T502 [US6] In `apps/api/echoroo/services/invitation_service.accept_invitation_via_public_token` add the FR-011-123 nested SAVEPOINT branch for `ownership_transfer_on_accept=true`:
  1. Inside SAVEPOINT: capture `pre_transfer_action_summary` via T022 helper (`build_pre_transfer_action_summary`)
  2. Update `Project.owner_id = accepting_user.id`
  3. Upsert prior-owner `ProjectMember` row at `role=ADMIN`
  4. Emit composite `project.ownership.bootstrap_transfer` audit with `{prior_owner, new_owner, pre_transfer_action_summary, at}`
  - On SAVEPOINT failure: rollback the SAVEPOINT and the parent transaction
- [x] T503 [US6] [P] On invitation revoke / expire / decline, do NOT auto-transfer (FR-011-124); project remains SU-owned

### Frontend

- [x] T520 [US6] [P] Extend the project creation form (likely `apps/web/src/routes/(app)/projects/new/+page.svelte`) to show the `intended_owner_email` field for superusers only (read `auth.svelte.ts` `isSuperuser` derived; hide the field otherwise). Display the response invitation_url with Copy in a one-shot dialog

### Contracts + tests

- [x] T540 [US6] [P] Validate `specs/011-zero-email-deployment/contracts/su-bootstrap-project-create.yaml` against the live app
- [x] T541 [US6] [P] Add `apps/api/tests/integration/test_superuser_bootstrap_invitation.py` (FR-011-120..125): SU + intended_owner_email → project + invitation; non-SU same payload → field silently dropped + same response shape; accept by intended owner → ownership transferred + audit composite with pre_transfer_action_summary; declined → no transfer
- [x] T542 [US6] [P] Already covered in T058 (`test_invitation_kind_guard.py`); reverify against ownership_transfer_on_accept=true + kind=trusted attempts
- [x] T543 [US6] [P] Add `apps/api/tests/security/test_pre_transfer_action_summary_destructive_allowlist.py` (R6): destructive event types preserve `target_id`; all other entries do not; A-13 detector test covers all spec/011 event types
- [ ] T544 [US6] [P] Add Playwright e2e `apps/web/tests/e2e/su-bootstrap.spec.ts` (US6 AC1-6): SU creates project for Alice, copies URL, Alice accepts in second browser, ownership transferred and visible in activity view with pre_transfer_action_summary

**Checkpoint**: US6 deliverable complete.

---

## Phase 9: US7 — In-app banners + activity view (Priority: P2)

**Goal**: Banners surface security-relevant events (new device login, API key revoke, email change, 2FA reset) to the user via a sticky in-app stack. Full activity history available indefinitely. All formerly-emailed notifications now banner-only.

**Independent Test**: Trigger each of the 4 event types; banner appears on next login; dismiss; banner does not reappear; activity view still shows it.

### Backend — banner read API

- [x] T600 [US7] Add `GET /web-api/v1/me/banners` to `apps/api/echoroo/api/web_v1/me.py` (or new file). Returns undismissed events targeting the authenticated user, ≤30 days old. Gate via `gate_action(USER_BANNER_LIST_ACTION)`
- [x] T601 [US7] Add `POST /web-api/v1/me/banners/dismiss` with body `{audit_table, audit_log_id}`. CSRF-required. Idempotent (204 each time). 404 collapsed for any failure (not found / not yours / unauthenticated) per FR-011-302 anti-enumeration. Gate via `gate_action(USER_BANNER_DISMISS_ACTION)`. Calls `services/user_banner.dismiss` which performs the actor-or-target match (T060)
- [x] T602 [US7] Add `GET /web-api/v1/me/activity` to `apps/api/echoroo/api/web_v1/me.py`. Cursor-based pagination, all events targeting the authenticated user, no age limit. Gate via `gate_action(USER_ACTIVITY_LIST_ACTION)`

### Backend — banner enqueue rewrite (final, from Phase 2 stubs)

- [x] T610 [US7] Rewrite `apps/api/echoroo/services/email.py:send_login_notification` to emit `auth.login.new_device` audit (T020) via `AuditLogService.write_platform_event`; remove all email-transport code
- [x] T611 [US7] [P] Rewrite `send_email_change_notification` to emit `platform.user.email_changed` audit + integrate with T620 change-email flow
- [x] T612 [US7] [P] Rewrite `send_2fa_reset_dispatched` to emit `platform.user.two_factor_reset_by_superuser` audit (call site removed in T403; this helper becomes a thin wrapper for the audit write)
- [x] T613 [US7] [P] Rewrite `send_api_key_scope_degrade_email` to emit a `platform.api_key.scope_degrade` audit (existing event-type) — banner-eligible
- [x] T614 [US7] [P] Rewrite `send_api_key_revoke_email` to emit `platform.api_key.revoke` audit (T020)
- [x] T615 [US7] [P] In `apps/api/echoroo/workers/login_notification_dispatcher.py` switch from email send to banner enqueue (already preset by T610 emitting the audit row)
- [x] T616 [US7] [P] In `apps/api/echoroo/workers/trusted_expiry_dispatcher.py` + `apps/api/echoroo/workers/trusted_expiry_notifier.py` switch from email send / outbox row to banner enqueue (FR-011-401, FR-011-010)
- [x] T617 [US7] [P] In `apps/api/echoroo/workers/api_key_age_check.py` replace the email send call-sites (`send_api_key_revoke_email`, `send_api_key_scope_degrade_email`) with the banner-enqueue helpers (already wired via T613/T614 — confirm the call-site delegates)

### Backend — email-change flow (FR-011-305)

- [x] T620 [US7] In `apps/api/echoroo/services/user.py` modify `change_email`:
  - Emit `platform.user.email_changed` audit
  - Invalidate ALL of the user's active sessions (forcing re-login)
  - Call `TrustedDeviceService.revoke_all_for_user(user)` (R10)
  - Set 24h cool-off (a `users.email_change_cooldown_until` column already exists? If not, add as part of the additive migration T010 — re-check; this is an additive change if missing)
  - Reject further `change_email` or `change_password` for the user during the cool-off
- [x] T621 [US7] [P] Implement the cool-off check in `services/user.change_email`: read `users.email_change_cooldown_until` (added by T010); reject the request with a clear "please wait until <ts>" error if `now() < cooldown_until`; on a successful change, set `cooldown_until = now() + 24h`. Mirror the same gate in `services/admin_password_reset.reset_password` for the user's own concurrent password-change requests (FR-011-305).

### Backend — TrustedDevice revocation audit (R10)

- [x] T625 [US7] [P] Add Celery beat task `gc_user_banner_dismissals` in `apps/api/echoroo/workers/banner_gc.py` (new file) that runs daily and deletes `user_banner_dismissals` rows older than 30 days (FR-011-309). Wire the schedule entry in `workers/celery_app.py`. The GC window MUST align with the banner age limit (FR-011-302) so a dismissed banner whose dismissal row was GC'd does not re-surface (data-model.md invariant). Add `tests/integration/test_banner_dismissal_gc.py` verifying age-cutoff behaviour
- [x] T630 [US7] Modify `TrustedDeviceService.revoke_all_for_user` in `apps/api/echoroo/services/trusted_device_service.py` so that the existing `reason: str | None` parameter is **no longer discarded** (currently `del reason` on line 106). Instead, after revoking, emit one `auth.trusted_device.revoke_all` audit row via `AuditLogService.write_platform_event` carrying `{user_id, revoked_count, reason}`. Wire all existing call-sites to pass an appropriate reason code:
  - `services/user.py` (email change): `reason="email_change"`
  - `services/two_factor_service.py` (admin 2FA disable): `reason="2fa_disable"`
  - `api/web_v1/auth.py` (self trusted-device wipe): `reason="user_self_revoke"`
  - `services/user_deletion_service.py`: `reason="user_deleted"`
  - `api/web_v1/account/trusted_devices.py` (single-device revoke surface that may sweep): keep existing semantics
  - `services/admin_password_reset.py` (new, T310): `reason="password_reset"` (or `"password_reset_self"` for self-reset)
  Reason code allowlist: `{"password_reset", "password_reset_self", "email_change", "2fa_disable", "user_self_revoke", "user_deleted"}`. Reject unknown reason codes at the helper boundary (raise `ValueError`). Keep the helper idempotent (R10 followup): calling it when the user has zero active devices is a no-op that still emits exactly one audit row with `revoked_count=0`.
- [x] T631 [US7] [P] Add `apps/api/tests/security/test_trusted_device_revoke_idempotent.py`: revoke twice in the same TX is a no-op on the second call

### Frontend — banner UI

- [ ] T640 [US7] [P] Create `apps/web/src/lib/components/BannerStack.svelte`: stacks undismissed banners non-modally at the top of the page; each banner dismissable; links to activity view
- [ ] T641 [US7] [P] In `apps/web/src/routes/(app)/+layout.svelte` (or the authenticated layout) render `BannerStack`
- [ ] T642 [US7] [P] Add `apps/web/src/routes/(app)/profile/activity/+page.svelte` (or extend Profile) with the full activity history (cursor pagination)
- [ ] T643 [US7] [P] In `apps/web/src/lib/api/auth.ts` (or `me.ts`) add `listBanners`, `dismissBanner({audit_table, audit_log_id})`, `listActivity({cursor, limit})` client methods

### Contracts + tests

- [x] T660 [US7] [P] Validate `specs/011-zero-email-deployment/contracts/me-banners-activity.yaml` against the live app
- [x] T661 [US7] [P] Add `apps/api/tests/integration/test_user_banners.py` (FR-011-301..310): each of 4 trigger events surfaces; dismiss is idempotent; cross-user dismissal 404
- [x] T662 [US7] [P] Add `apps/api/tests/security/test_user_banner_dismiss_actor_or_target_match.py` (security review M-2): every combination of `(audit_table × actor_user_id vs detail.target_user_id × authenticated user)` enumerated; cross-user dismissals all return 404
- [ ] T663 [US7] [P] Add Playwright e2e `apps/web/tests/e2e/banner-stack.spec.ts` (US7 AC1-5): trigger new-device login, API key revoke, email change, 2FA reset; verify banner stack updates, dismiss works, activity view shows full history

**Checkpoint**: US7 deliverable complete.

---

## Phase 10: Polish & Cross-Cutting

**Purpose**: Final destructive migration, telemetry redaction, runbook completion, README/docs polish, end-to-end SC validation.

### Migration 0022 (destructive — runs AFTER all readers gone)

- [x] T700 Create `apps/api/alembic/versions/0022_email_subsystem_removal.py` (FR-011-002..003): drops `email_verification_tokens`, `password_reset_tokens`, `users.email_verified_at`. `downgrade()` raises (forward-only, NFR-011-002)
- [x] T701 [P] Verify the migration runs cleanly on a dev DB that has already received `0021`: pre-migration assert tables exist, run upgrade, post-migration assert tables absent + column absent + every reader from spec/011 Removal Plan grep produces zero hits

### Telemetry redaction (R13)

- [x] T710 Create new package `apps/api/echoroo/observability/` (with `__init__.py`) and module `apps/api/echoroo/observability/sentry.py`. Implement `init_sentry()` that is a no-op when `SENTRY_DSN` is unset; otherwise wires `sentry_sdk.init(dsn=..., before_send=...)`. The `before_send` hook scrubs request bodies, response bodies, and breadcrumbs whose key matches `temporary_password`, `step_up_token`, `invitation_url`, or `signed_token_envelope`; also scrubs request headers matching `X-Step-Up-Token`. The package directory does not exist today (grep-verified). (Step 12, 2026-05-23.)
- [x] T711 [P] Create new file `apps/api/echoroo/middleware/redaction.py` (do NOT extend `middleware/audit_logging.py` — separate concerns per research.md R13). Implement `RedactionMiddleware(BaseHTTPMiddleware)` that drops the same four field names from the structured-log envelope before emission. Register in `apps/api/echoroo/main.py` after all auth/CSRF middleware so the redaction sees the final response payload. (Step 12, 2026-05-23.)
- [x] T712 [P] Add `apps/api/tests/security/test_telemetry_scrubs_sensitive_fields.py`: simulate request/response carrying each sensitive field; assert Sentry hook + middleware both scrub; assert nothing in `caplog` or test log capture contains the values (Step 12, 17/17 passed.)
- [x] T713 [P] In `docs/operations/admin-recovery-flows.md` include an Nginx `log_format` snippet that scrubs `X-Step-Up-Token` request header (operator-side config) (Step 12, folded into the T721 file.)

### Documentation

- [x] T720 [P] Write `docs/operations/inviting-users.md` (single + bulk invite walkthroughs) (Step 12, 2026-05-23.)
- [x] T721 [P] Write `docs/operations/admin-recovery-flows.md` (password / 2FA recovery; includes T713 Nginx example) (Step 12, 2026-05-23.)
- [x] T722 [P] Write `docs/operations/superuser-bootstrap.md` (SU bootstrap workflow with `intended_owner_email`) (Step 12, 2026-05-23.)
- [x] T723 [P] Fill `docs/runbook/invitation_token_kid_rotation.md` (skeleton from T091) with planned-rotation + emergency-rotation + forensic-query sections (Step 12, 2026-05-23.)
- [x] T724 [P] Fill `docs/runbook/zero-email-deployment-secret-rotation.md` (skeleton from T092) with the full list of CI / Actions secrets to rotate / delete (Step 12, 2026-05-23.)

### Final OpenAPI sync + cumulative grep

- [x] T725 [P] Open-questions closeout: walk the 5 entries in spec.md §Open Questions (invitation issuer removal handling, invitation role catalog change handling, forced password change TTL per-reset, activity/banner retention, bulk invitation maximum size) plus the step-up token rotation note. For each, confirm the tentative answer is unchanged after implementation; if any were amended during implementation, update spec.md inline. Commit message: `docs(spec/011): close out open questions` (Step 12 — all 5 + step-up note unchanged; closeout annotation added inline in `specs/011-zero-email-deployment/spec.md` §Open Questions.)
- [x] T730 Re-run `pytest apps/api/tests/contract/test_openapi_diff.py` against the final HEAD; resolve any final YAML / live drift; commit message: `chore(openapi): final sync for spec/011` (Step 12, 27/27 passed across `test_openapi_diff.py` + `test_openapi_diff_multi_spec.py` — zero drift.)
- [x] T731 Re-run `pytest apps/api/tests/contract/test_no_email_subsystem_traces.py` against the final HEAD; zero matches (Step 12 — passed when run from worktree-mounted repo root.)

### SC final validation (one task per success criterion)

- [ ] T740 [P] **SC-1**: A naive deployer can complete README quickstart §1-§5 without being required to configure SMTP/Resend/Mailpit/DKIM/DNS — manual walkthrough recorded as an end-to-end Playwright test `apps/web/tests/e2e/sc1-naive-deployer.spec.ts` (deferred to Step 12b — frontend Playwright)
- [ ] T741 [P] **SC-2**: Lab admin onboards 20 collaborators via one bulk-invitation operation — covered by T292 + a manual lab-scale exercise (deferred to Step 12b — manual exercise)
- [ ] T742 [P] **SC-3**: User who forgot password is reset and back to working state under 5 minutes — covered by T362 (deferred to Step 12b — already covered by T362 in Step 5)
- [ ] T743 [P] **SC-4**: SU bootstraps a project in a single create-project operation; new owner sees `pre_transfer_action_summary` — covered by T544 (deferred to Step 12b — already covered by T544 in Step 9)
- [x] T744 [P] **SC-5**: Test suite passes including endpoint-coverage hard-fail (TOKEN_AUTH_ONLY + AUTHENTICATED_SELF_NO_GATE exemptions), OpenAPI diff (multi-spec), 9-class coherence, security-test corpus — composite gate; run all spec/011 tests (Step 12 — composite: contract+unit 2794 passed / 142 skipped / 61 xfailed / 0 failed; security 625 passed / 28 skipped / 4 xfailed / 10 failed (all pre-existing on main HEAD `cc21326a`, none spec/011-introduced); integration 322 passed / 41 skipped / 96 errors (all pre-existing testcontainer fixture issues); spec/011-tagged subset 240/240 passed.)
- [ ] T745 [P] **SC-6**: spec/010 Trusted Device user stories continue to pass (regression check) — re-run spec/010's Playwright suite; additionally assert FR-011-402 revocation triggers fire correctly across the 4 new call-sites (deferred to Step 12b — Playwright)

---

## Dependency Graph

```
Phase 1 Setup (T001-T004)
   ↓
Phase 2 Foundational (T010-T100)
   ├── Migration 0021 (T010-T011)
   ├── Settings (T012-T014)
   ├── Audit substrate (T020-T024)
   ├── ACTIONs + allowlists (T030-T034)
   ├── Step-up extension (T040-T042)
   ├── Invitation envelope + outcome (T050-T058)
   ├── Banner subsystem write side (T060-T061)
   ├── Forced-change middleware atomic swap (T070-T072)
   ├── OpenAPI harness multi-spec (T080-T081)
   ├── CI guard + runbook skeletons (T090-T092)
   └── services/email.py reduction stubs (T100)
   ↓
   ╔══════════════════════════════════════════════════════╗
   ║  Phase 3 US1 (T110-T192)   ←  MVP — runnable alone  ║
   ║                                                      ║
   ║  Phase 4 US2 (T200-T245)   ←  independent of US1+   ║
   ║  Phase 5 US3 (T260-T292)   ←  depends on US2 (T202) ║
   ║  Phase 6 US4 (T300-T362)   ←  independent           ║
   ║  Phase 7 US5 (T400-T405)   ←  depends on US4 (T301) ║
   ║  Phase 8 US6 (T500-T544)   ←  depends on US2 (T204) ║
   ║  Phase 9 US7 (T600-T663)   ←  independent           ║
   ╚══════════════════════════════════════════════════════╝
   ↓
Phase 10 Polish (T700-T745)
```

**Story-level dependencies**:

- US1 stands alone — the MVP. Implementable directly after Phase 2.
- US2 depends only on Phase 2 (invitation envelope + resolver TOKEN_AUTH_ONLY).
- US3 depends on US2's `POST /invitations` handler (T200) being in place.
- US4 stands alone (uses step-up service from Phase 2).
- US5 depends on US4's step-up endpoints (T300-T301) being merged.
- US6 depends on US2's `accept_invitation` extension (T204).
- US7 stands alone (banner read API is on top of Phase 2's enqueue side).

**Parallel execution windows**:

- After Phase 2 completes: US1, US2, US4, US6 backend, US7 backend can all begin in parallel.
- US3 backend can begin once T200 (single-invite handler) is in place.
- US5 backend can begin once T300-T301 (step-up endpoints) are in place.

---

## MVP Scope (recommended initial delivery)

**Phase 1 + Phase 2 + Phase 3 (US1)** only.

This delivers:
- Fresh deployment works with zero email configuration
- Resend / SMTP / DNS / DKIM never mentioned in setup
- All email-verification UI gone
- ForcedPasswordChangeMiddleware in place (no-op for users without temp passwords)
- Step-up extension live (no callers yet)
- Invitation envelope 4-part (existing trusted-overlay path still works)
- CI guard test passes

US2-US7 are independent feature deliveries on top of the MVP foundation.

---

## FR / NFR / SC Coverage Matrix

| FR / NFR / SC | Phase | Primary Tasks |
|---|---|---|
| FR-011-001 (no outbound email) | Phase 2, 3, 9 | T100, T119, T610-T614 |
| FR-011-002 (drop email_verified_at) | Phase 10 | T700 |
| FR-011-003 (drop tokens tables) | Phase 10 | T700 |
| FR-011-004 (remove enforcement middleware) | Phase 2, 3 | T071, T114 |
| FR-011-005 (delete verify-email/password-reset/magic-link routes) | Phase 3 | T119-T120 |
| FR-011-006 (remove settings) | Phase 1, 3 | T002-T004, T013, T037 |
| FR-011-007 (drop resend dep) | Phase 1 | T002 |
| FR-011-008 (reduce services/email.py) | Phase 2, 9 | T100, T610-T614 |
| FR-011-009 (setup/init_superuser cleanup) | Phase 3 | T124 |
| FR-011-010 (remove outbox dispatcher) | Phase 2, 3, 9 | T054, T115-T116, T616 |
| FR-011-011 (frontend cleanup) | Phase 3 | T140-T151 |
| FR-011-012 (README cleanup) | Phase 3, 10 | T180-T181, T720 |
| FR-011-013 (login forgot-password link) | Phase 3 | T143 |
| FR-011-014 (e2e specs) | Phase 3 | T168 |
| FR-011-101 (member invitation endpoint) | Phase 4 | T200 |
| FR-011-102 (invitation_url, kid envelope) | Phase 2, 4 | T050-T053, T200 |
| FR-011-103 (Trusted-overlay invitation_url) | Phase 4 | T207, T242 |
| FR-011-104 (signed_token_envelope outcome) | Phase 2 | T052-T053 |
| FR-011-105 (resolver) | Phase 4 | T202 |
| FR-011-106 (atomic accept) | Phase 4 | T204-T205 |
| FR-011-107 (generic invalid + timing pad) | Phase 4 | T202-T203, T206 |
| FR-011-108 (admin listing + revoke) | Phase 4 | T201, T222 |
| FR-011-109 (public projects don't require invite) | Phase 4 | T203 (negative branch) |
| FR-011-110..115 (bulk invitation) | Phase 5 | T260-T264, T280-T281, T290-T292 |
| FR-011-120..125 (SU bootstrap) | Phase 8 | T500-T503, T520, T541 |
| FR-011-201..210 (admin password reset) | Phase 6 | T300-T362 |
| FR-011-204 (forced-change middleware) | Phase 2, 6 | T070-T072, T320-T321 |
| FR-011-206 (step-up password + 2FA) | Phase 2, 6 | T040-T042, T300-T302 |
| FR-011-301..310 (banner) | Phase 9 | T600-T663 |
| FR-011-401..402 (Trusted Device compat) | Phase 7, 9 | T401, T620, T630 |
| NFR-011-001 (CI grep guard) | Phase 2, 10 | T090, T731 |
| NFR-011-002 (two-phase migration) | Phase 2, 10 | T010-T011, T700-T701 |
| NFR-011-003 (constant-time compare) | Phase 2 | T051 |
| NFR-011-004 (gate_action + allowlists) | Phase 2 | T030-T034 |
| NFR-011-005 (audit-action registration + PII) | Phase 2 | T020-T024 |
| NFR-011-006 (rate-limit + timing pad) | Phase 4 | T206 |
| NFR-011-007 (middleware position) | Phase 2 | T070-T071 |
| NFR-011-008 (bulk SAVEPOINT) | Phase 5 | T262 |
| NFR-011-009 (OpenAPI multi-spec harness) | Phase 2 | T080-T081 |
| NFR-011-010 (kid rotation + 4-part envelope + co-presence validator) | Phase 2 | T012, T050-T051, T057 |
| SC-1 (naive deployer) | Phase 3, 10 | T192, T740 |
| SC-2 (20-person bulk) | Phase 5, 10 | T292, T741 |
| SC-3 (5-min password reset) | Phase 6, 10 | T362, T742 |
| SC-4 (SU bootstrap one-op + visibility) | Phase 8, 10 | T544, T743 |
| SC-5 (full test suite) | Phase 10 | T744 |
| SC-6 (spec/010 regression) | Phase 10 | T745 |

---

## Task counts

- **Phase 1 Setup**: 4 tasks
- **Phase 2 Foundational**: 41 tasks (T010-T100, mix of [P] and serial)
- **Phase 3 US1 (MVP)**: 35 tasks
- **Phase 4 US2**: 13 tasks
- **Phase 5 US3**: 7 tasks
- **Phase 6 US4**: 16 tasks
- **Phase 7 US5**: 6 tasks
- **Phase 8 US6**: 9 tasks
- **Phase 9 US7**: 25 tasks (T625 added: banner-dismissal GC, F7)
- **Phase 10 Polish**: 18 tasks (T725 added: Open Questions closeout, F12)
- **Total**: 192 tasks

Approximate parallelization (counting [P]): ~96 of 192 tasks (~50%) can run in parallel within their phase.

**Post-analyze patch summary (analysis F1-F12)**:
- F1 (T020): audit-action constants relocated from `audit_service.py` to service-private call sites (matches existing codebase convention).
- F2 (T630): `TrustedDeviceService.revoke_all_for_user` modified to consume `reason` (previously discarded) and emit an audit row; 6 existing call-sites enumerated to receive a reason code.
- F3 (T080): `_CONTRACTS_DIRS` refactor specified concretely (list of directories, regression assertion for spec/006 baseline).
- F4 (FR-011-306 / data-model.md / BannerItem): naming converged on `platform.user.two_factor_reset_by_superuser`.
- F5 (R13 / T710-T711): observability surface paths pinned; `observability/sentry.py` and `middleware/redaction.py` are new files (codebase has neither today).
- F6 (T010 / T621): `users.email_change_cooldown_until` added to migration 0021's column manifest (grep-verified absent); T621 simplified to cool-off enforcement only.
- F7 (T625): banner-dismissal GC task added (was missing).
- F10 (R6 / data-model.md): `pre_transfer_action_summary` JSON shape canonical = `{action, occurred_at, target_id?}` (was inconsistent across R6 / data-model.md).
- F12 (T725): Open Questions closeout task added.
