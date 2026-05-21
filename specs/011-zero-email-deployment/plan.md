# Implementation Plan: Zero-email Deployment

**Branch**: `011-zero-email-deployment` | **Date**: 2026-05-21 | **Spec**: [spec.md](./spec.md) (Rev.3.2)
**Input**: Feature specification from `/specs/011-zero-email-deployment/spec.md` (Rev.3.2) + Rev.2 of research.md / data-model.md / contracts/ + Rev.3.2 patches in spec.md / plan.md / data-model.md.

## Summary

Echoroo's email-verification subsystem and outbound-email subsystem are silently dysfunctional in dev / preview / fresh-deploy (Resend unconfigured). The deployment persona is ecologists who cannot reasonably operate SMTP / DKIM / DNS. This feature deletes the outbound-email subsystem entirely and replaces every flow that used it with an admin-mediated or in-app primitive: collaborator onboarding via existing `project_invitations` with the token surfaced to the issuing admin (not emailed), bulk-invite for lab-sized cohorts, system-superuser project bootstrap, admin-mediated password reset (with step-up: password + 2FA) and 2FA recovery, in-app banner notifications backed by the audit log, and a forced-change middleware that locks out every route except `/auth/change-password` until a temp password is rotated. The codebase no longer carries `resend`, `aiosmtplib`, Mailpit, or any SMTP egress code path. Trusted Device functionality from spec/010 is preserved with extended revocation triggers on sensitive account changes.

## Technical Context

**Language/Version**: Python 3.11 (backend, per `apps/api/pyproject.toml`), TypeScript 5 / SvelteKit (frontend)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0, Alembic, Redis (rate-limit and invitation rate-limit per spec/006 FR-056 — **not** used for step-up tokens; step-up is HS256 JWT signed with `web_session_secret`, no Redis state), Celery (existing dispatchers), Pydantic v2; **`resend` package removed in this feature**
**Storage**: PostgreSQL (existing `users`, `projects`, `project_invitations`, `project_members`, `project_trusted_users`, `project_audit_log`, `platform_audit_log` tables; new `user_banner_dismissals` table)
**Testing**: pytest (backend, including contract / integration / security), Playwright (frontend e2e)
**Target Platform**: Linux server via docker compose; the reference deployer is a single-host research-cloud VM
**Project Type**: web (FastAPI backend + SvelteKit frontend, single repo)
**Performance Goals**: invitation acceptance under 200ms p95 (one transaction, one SAVEPOINT for bootstrap path); banner list under 50ms p95 (`user_banner_dismissals` is a tiny join); `/invite/{token}` resolver constant 200–400ms (timing-padded per NFR-011-006)
**Constraints**: no outbound email under any circumstance (NFR-011-001); forward-only migrations (NFR-011-002); two-phase deployment (Phase A 0021 additive → Phase B 0022 destructive); OpenAPI diff harness extension to multi-spec contracts directories with per-PR YAML update (NFR-011-009); step-up token TTL 5 minutes, HS256 JWT signed with `web_session_secret`, transmitted via `X-Step-Up-Token` header
**Scale/Scope**: 5–50 users per deployment (research lab cohort); invitations max 50 per bulk request; per-issuer global rate-limit 200/h, 1000/d (NFR-011-006); banner age limit 30 days

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Clean Architecture

✅ **Pass**. New endpoints live in API layer (`api/web_v1/projects/_members.py`, `api/web_v1/admin.py`, `api/web_v1/me.py`, `api/web_v1/auth.py`). Business logic lives in service layer (`services/invitation_service` extension, `services/admin_password_reset` new, `services/user_banner` new, `services/step_up_token_service` extension). Data access lives in repository layer (existing `repositories/`). New `ForcedPasswordChangeMiddleware` is a cross-cutting concern handled correctly via middleware.

### II. Test-Driven Development (NON-NEGOTIABLE)

✅ **Pass**. Test plan in spec.md §Test Plan enumerates contract / integration / security / endpoint-coverage / 9-class coherence / Playwright tests for every new and removed surface. The CI guard test (`test_no_email_subsystem_traces.py`, R12) catches regression.

### III. Type Safety

✅ **Pass**. New API schemas added to `apps/api/echoroo/schemas/`; frontend types in `apps/web/src/lib/types/`. mypy strict + TS strict apply unchanged.

### IV. ML Pipeline Architecture

✅ **N/A**. Feature does not touch the ML pipeline. Existing Celery workers that send email (`email_verification_dispatcher`, `login_notification_dispatcher`, `trusted_expiry_dispatcher`, `api_key_age_check`) are repurposed or removed; none of them run ML tasks.

### V. API Versioning

✅ **Pass**. New endpoints follow `/web-api/v1/*` and `/api/v1/*` conventions. The deletions of `/verify-email*` and `/password-reset/*` are tracked via the OpenAPI diff harness extension (NFR-011-009) — each endpoint-touching PR updates the relevant YAML in `specs/011-zero-email-deployment/contracts/` and re-runs `apps/api/tests/contract/test_openapi_diff.py`. No snapshot file is involved (the harness is a YAML-contracts-vs-live-app subset asserter). Note: spec/006 FR-051 is formally superseded by FR-011-103; the supersede is documented in spec.md.

### Security Requirements

✅ **Pass**. Step-up auth strengthens admin-recovery actions to password + 2FA AND-condition. Temp-password reveal is Cache-Control: no-store, telemetry-redacted, clipboard auto-cleared, 24h TTL. Invitation token kid rotation aligns with Phase 17 A-12. `/invite/{token}` resolver is timing-padded and rate-limited. CSRF protection retained on `change-password` and `banners/dismiss`. PII handling: A-13 detector registration for all new free-form fields. OWASP top 10 reviewed in spec.md (Rev.2 security review §6); no new attack surface.

**Result**: All five Core Principles + Security Requirements pass. No violations to justify in Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/011-zero-email-deployment/
├── spec.md              # Source specification (Rev.3.2)
├── plan.md              # This file
├── research.md          # Phase 0 — R1..R12 decision blocks
├── data-model.md        # Phase 1 — migrations, entities, ACTION constants
├── quickstart.md        # Phase 1 — operator-facing walkthrough
├── contracts/           # Phase 1 — OpenAPI shape for new endpoint groups
│   ├── member-invitations.yaml
│   ├── invitation-public.yaml
│   ├── admin-password-reset.yaml
│   ├── me-banners-activity.yaml
│   ├── su-bootstrap-project-create.yaml
│   └── trusted-users-invitation-url.yaml
└── tasks.md             # Phase 2 — generated by /speckit-tasks (not yet)
```

### Source Code (repository root)

The codebase is a monorepo with `apps/api` (FastAPI backend) and `apps/web` (SvelteKit frontend). Affected files are listed exhaustively in spec.md §Removal Plan. The high-level shape:

```text
apps/api/echoroo/
├── api/
│   ├── web_v1/
│   │   ├── auth.py                # delete verify-email/password-reset/2fa-magic; add change-password, step-up, invitation resolver/accept
│   │   ├── admin.py               # add POST /admin/users/{user_id}/reset-password
│   │   ├── me.py                  # new: GET /me/banners, POST /me/banners/dismiss (body: audit_table + audit_log_id), GET /me/activity
│   │   ├── projects/
│   │   │   ├── _members.py        # add POST /invitations, POST /invitations/bulk
│   │   │   ├── _lifecycle.py      # accept intended_owner_email field for SU
│   │   │   └── ...
│   │   └── trusted.py             # modify response to include invitation_url
│   └── v1/auth.py                 # delete legacy mirrors; add /change-password mirror
├── core/
│   ├── settings.py                # remove RESEND_*, EMAIL_*; add INVITATION_TOKEN_KID_*
│   ├── auth_paths.py              # remove verify-email / password-reset paths
│   ├── endpoint_allowlist.py      # update; add TOKEN_AUTH_ONLY entries
│   └── actions.py                 # add 5 ACTION constants
├── middleware/
│   ├── email_verification_enforcement.py    # DELETE
│   ├── forced_password_change.py            # NEW
│   └── step_up.py                           # extend verify to recognise admin_recovery scope + factors claim
├── models/
│   ├── email_verification_token.py          # DELETE
│   ├── password_reset_token.py              # DELETE
│   ├── user.py                              # remove email_verified_at; add must_change_password, temp_password_expires_at
│   └── project.py                           # add ownership_transfer_on_accept to ProjectInvitation
├── services/
│   ├── email.py                             # reduced to banner-event emitters
│   ├── email_verification_service.py        # DELETE
│   ├── admin_password_reset.py              # NEW
│   ├── step_up_token_service.py             # extend payload: add `factors` claim, new `admin_recovery` scope value
│   ├── user_banner.py                       # NEW (reads project_audit_log + platform_audit_log via AuditLogService)
│   ├── trusted_device_service.py            # NO new helper — reuse existing revoke_all_for_user
│   ├── invitation_service.py                # expose `signed_token_envelope` in outcome (drop `mail_payload`); extend envelope 3-part → 4-part with `kid`; add bootstrap branch
│   ├── auth.py                              # remove verify_email, request_password_reset
│   └── user.py                              # remove email_verified_at reset; trigger banner enqueue
├── workers/
│   ├── email_verification_dispatcher.py     # DELETE
│   ├── login_notification_dispatcher.py     # rewrite to banner enqueue
│   ├── trusted_expiry_dispatcher.py         # rewrite to banner enqueue
│   ├── trusted_expiry_notifier.py           # rewrite to banner enqueue
│   ├── api_key_age_check.py                 # rewrite revoke + scope_degrade to banner enqueue
│   └── celery_app.py                        # remove email_verification_dispatcher include
└── alembic/versions/
    ├── 0021_zero_email_additive.py          # NEW (additive)
    └── 0022_email_subsystem_removal.py      # NEW (destructive)

apps/web/src/
├── routes/
│   ├── (auth)/
│   │   ├── verify-email/                    # DELETE directory
│   │   ├── forgot-password/                 # DELETE directory (if present)
│   │   ├── 2fa-reset/                       # DELETE magic-link path (if present)
│   │   ├── change-password/+page.svelte     # NEW
│   │   ├── invite/[token]/+page.svelte      # NEW
│   │   └── login/+page.svelte               # remove forgot-password link
│   └── (app)/
│       ├── profile/+page.svelte             # remove verify badge; add activity tab
│       ├── dashboard/+page.svelte           # remove isEmailVerified; surface banner stack
│       ├── projects/[id]/collaborators/+page.svelte  # add invite + bulk + list
│       └── admin/users/+page.svelte         # add reset-password button + dialog
├── lib/
│   ├── api/auth.ts                          # remove verify/forgot methods; add changePassword, acceptInvitation
│   ├── api/web-auth.ts                      # mirror auth.ts edits
│   ├── stores/auth.svelte.ts                # remove email_verified_at; add must_change_password derived
│   ├── types/index.ts                       # User type update
│   └── components/BannerStack.svelte        # NEW (banner UI)
├── hooks.server.ts                          # remove email_verified_at from session shape
└── messages/{en,ja}.json                    # remove verify keys; add new keys

apps/api/tests/
├── contract/test_no_email_subsystem_traces.py    # NEW (CI guard, R12)
├── contract/test_openapi_diff.py                 # extend to also include specs/011-zero-email-deployment/contracts/ (NFR-011-009; no snapshot file)
├── integration/test_member_invitation_flow.py    # NEW
├── integration/test_bulk_invitation.py           # NEW
├── integration/test_superuser_bootstrap_invitation.py  # NEW
├── integration/test_admin_password_reset.py      # NEW
├── integration/test_must_change_password_middleware.py # NEW
├── integration/test_user_banners.py              # NEW
├── security/test_invitation_token_kid_rotation.py # NEW
├── security/test_step_up_required_for_admin_recovery.py # NEW
├── security/test_invitation_kind_guard.py        # NEW
├── security/authentication/test_email_verification_required.py  # DELETE
└── unit/middleware/test_email_verification_enforcement.py # DELETE

apps/web/tests/e2e/                          # delete verify-email walkthroughs; add invitation/banner/forced-change walkthroughs

docs/
├── operations/
│   ├── inviting-users.md                    # NEW
│   ├── admin-recovery-flows.md              # NEW
│   └── superuser-bootstrap.md               # NEW
└── runbook/
    ├── invitation_token_kid_rotation.md     # NEW (R3)
    └── zero-email-deployment-secret-rotation.md  # NEW (R2)
```

**Structure Decision**: The feature spans the existing monorepo unchanged — no new top-level directories. All edits are confined to existing module locations or sibling new files within `apps/api/echoroo/{api,services,middleware,workers}`, `apps/web/src/{routes,lib}`, `apps/api/alembic/versions/`, and `docs/`. The split between `apps/api` and `apps/web` is the existing Project Type=web layout.

## Implementation Phasing (mapped to spec.md §Implementation Plan steps 1–12)

Each step is a single mergeable PR. Step 1 lands the additive migration; steps 2–10 land code that depends on the new schema; step 11 lands the destructive migration after all readers are gone; step 12 is documentation cleanup.

- **Step 1**: Migration `0021_zero_email_additive` (additive only). Adds `must_change_password`, `temp_password_expires_at`, `ownership_transfer_on_accept`, `user_banner_dismissals`. Schema CHECK constraint on `ownership_transfer_on_accept` (R5).
- **Step 2**: Banner subsystem (`services/user_banner.py`, `api/web_v1/me.py`, `models/__init__.py` re-export; rewrite `services/email.py` helpers to banner enqueue; rewrite `workers/login_notification_dispatcher.py`, `workers/trusted_expiry_dispatcher.py`, `workers/trusted_expiry_notifier.py`, `workers/api_key_age_check.py`; `services/user.py` email-change side effect).
- **Step 3**: Middleware swap (FR-011-204): add `ForcedPasswordChangeMiddleware`, unregister `EmailVerificationEnforcementMiddleware` in the same PR. Source file of the old middleware remains until step 10. Allowlist matrix test added.
- **Step 4**: Extend `services/step_up_token_service.py` payload with the `factors` claim and the new `admin_recovery` scope value; extend `middleware/step_up.py` verifier to enforce `factors.password=true AND factors.second_factor IN ('totp','webauthn')` for the new scope. Add `POST /step-up/begin` and `POST /step-up/complete` endpoints for the admin-recovery flow. The existing `admin_destructive` scope path is unchanged. (R1)
- **Step 5**: `services/admin_password_reset.py` (new) + `POST /admin/users/{user_id}/reset-password` endpoint + admin UI. Step-up gate, target session invalidation, trusted-device revocation (via R10 helper), audit emission.
- **Step 6**: `invitation_service.create_invitation` modification — drop `InvitationMailPayload`, expose `signed_token_envelope`. Extend the invitation token envelope from 3-part (`{token}.{exp}.{mac}`) to 4-part (`{token}.{exp}.{kid}.{mac}`) per NFR-011-010 with backward-verify of legacy 3-part tokens during the grace window. Modify Trusted-overlay endpoint response to include `invitation_url` (FR-011-103). **Extend the OpenAPI diff harness `test_openapi_diff.py` to also assert against `specs/011-zero-email-deployment/contracts/`** (R4).
- **Step 7**: Member-kind invitation endpoint (`POST /projects/{id}/invitations`) + existing-user accept branch + frontend collaborator UI. TOKEN_AUTH_ONLY classification of resolver and accept routes.
- **Step 8**: Bulk-invitation endpoint + frontend bulk UI.
- **Step 9**: SU bootstrap (`intended_owner_email` field) + `accept_invitation` ownership-transfer SAVEPOINT (FR-011-123) + `pre_transfer_action_summary` with destructive-event allowlist (R6).
- **Step 10**: Delete email subsystem: settings, env, `services/email_verification_service.py`, `models/email_verification_token.py`, `models/password_reset_token.py`, `middleware/email_verification_enforcement.py`, `workers/email_verification_dispatcher.py`, `/verify-email*`, `/password-reset/*`, `/2fa-reset/magic-link*`, frontend routes/types/i18n, README references. Update affected `specs/011-zero-email-deployment/contracts/*.yaml` and re-run `apps/api/tests/contract/test_openapi_diff.py` to verify the subset relation against the live OpenAPI document (R4). Add `test_no_email_subsystem_traces.py` CI guard (R12).
- **Step 11**: Migration `0022_email_subsystem_removal` (destructive). Drops `email_verification_tokens`, `password_reset_tokens`, `users.email_verified_at`.
- **Step 12**: Documentation: README quickstart, `docs/operations/*.md`, `docs/runbook/*.md`.

### CI strategy for OpenAPI diff (R4 Rev.2)

The existing `apps/api/tests/contract/test_openapi_diff.py` asserts a subset relation between YAML contracts and the live FastAPI app's exposed shape. It hard-codes `specs/006-permissions-redesign/contracts/`. Step 6 extends the harness to also assert against `specs/011-zero-email-deployment/contracts/`. There is no snapshot file to regenerate.

Each step that touches an HTTP endpoint (2, 4, 5, 6, 7, 8, 9, 10) MUST update the relevant YAML under `specs/011-zero-email-deployment/contracts/` in the same PR. The diff harness re-runs locally and in CI on every PR; YAML/live mismatches fail the build.

## Phase 0: Outline & Research

**Status**: ✅ Complete (see `research.md` Rev.2).

14 decision blocks (R1..R14) cover every NEEDS-CLARIFICATION carried over from the three-way reviews of spec.md Rev.1, Rev.2, and the plan-phase three-way review of Rev.3. Rev.2 of research.md re-anchors all decisions to grep-verified existing implementations (HS256 JWT step-up, 3-part invitation envelope, `project_audit_log`/`platform_audit_log` tables, `TrustedDeviceService.revoke_all_for_user` already exists, `_NEW`/`_OLD` env-naming pattern, `test_openapi_diff.py` is a contracts-vs-live subset asserter not a snapshot). No remaining unknowns.

## Phase 1: Design & Contracts

**Status**: ✅ Complete (Rev.2 of all artefacts).

Artefacts:

- `data-model.md` (Rev.2) — exhaustive entity / migration / ACTION / audit-action listings; FK targets reconciled with the real `project_audit_log` and `platform_audit_log` tables; polymorphic dismissal join documented.
- `contracts/member-invitations.yaml` — issuance, listing, revoke, bulk for Member-kind invitations; bulk response is a top-level array (FR-011-113); revoke 403 collapsed into 404 for anti-enumeration.
- `contracts/invitation-public.yaml` — TOKEN_AUTH_ONLY resolver + accept; signup vs existing-user branch via `is_logged_in` and `authenticated_email_matches_bound` flags in the resolver context; optional session cookie; timing pad (`target_ms: 300, jitter_ms: 50`); AcceptResponse includes `kind` so `ownership_transferred=true ⇒ kind=member` is contract-asserted.
- `contracts/admin-password-reset.yaml` — step-up begin/complete (admin_recovery scope) with `oneOf` `password+totp_code` OR `password+webauthn_assertion`; admin reset; change-password (web-v1 + v1 mirror) marked `x-csrf-required: true`.
- `contracts/me-banners-activity.yaml` — banner list / dismiss / activity. Dismiss takes `(audit_table, audit_log_id)` in body (polymorphic). ActivityItem schema is independent of BannerItem and is unrestricted on `action`.
- `contracts/su-bootstrap-project-create.yaml` — project create extension with `intended_owner_email` (marked `x-superuser-only-field: true`); response shape is identical for SU and non-SU paths to prevent enumeration.
- `contracts/trusted-users-invitation-url.yaml` — FR-011-103 response-shape change for the existing Trusted-overlay endpoint.
- `quickstart.md` (Rev.2) — ecologist-facing walkthrough; satisfies SC-1 by moving "common misconceptions" content to a post-"you're done" FAQ.

### Agent context

This `plan.md` is linked from the SPECKIT marker block in `CLAUDE.md` (next step).

## Phase 2 (Out of scope for /speckit-plan)

`/speckit-tasks` will turn the steps above into ordered, dependency-tagged tasks with FR / NFR / SC coverage assertions. The granularity target is:

- Per migration → 1 task (with downgrade-stub assertion sub-task)
- Per service file change → 1 task
- Per endpoint → 1 task with contract + integration + security sub-tasks
- Per removed file → 1 task with grep-verification sub-task
- Per endpoint-touching PR → 1 sub-task to update the corresponding `specs/011-zero-email-deployment/contracts/*.yaml` and re-run `pytest tests/contract/test_openapi_diff.py` (no snapshot file)

## Complexity Tracking

> No constitution violations require justification. Section retained per template.

## Decision Snapshot (where to look for "why")

| Decision | Source |
|---|---|
| Reuse `project_invitations` (no new table) | research.md R7 |
| Two-phase migration (0021 additive + 0022 destructive) | spec.md NFR-011-002 |
| Middleware swap atomic in step 3 (single PR) | research.md R8 |
| Extend existing `step_up_token_service` HS256 JWT (not Redis, not parallel module) | research.md R1 (Rev.2) |
| Add `factors` claim + `admin_recovery` scope to step-up JWT | research.md R1 (Rev.2) |
| Step-up token transport via existing `X-Step-Up-Token` header | research.md R1 (Rev.2) |
| Invitation token envelope 3-part → 4-part `{token}.{exp}.{kid}.{mac}` | spec.md NFR-011-010 + research.md R3 (Rev.2) |
| Env vars `INVITATION_TOKEN_KID_NEW` / `_OLD` (mirrors A-12 `..._KID_NEW` / `..._KID_OLD`) | research.md R3 (Rev.2) |
| OpenAPI harness extension to multi-spec directories (not snapshot regen) | research.md R4 (Rev.2) |
| `DESTRUCTIVE_ACTIONS` allowlist for `pre_transfer_action_summary` in `services/audit_service.py` | research.md R6 (Rev.2) |
| Audit-action strings follow existing `prefix.subject.verb` 3-segment naming | research.md R6 + data-model.md (Rev.2) |
| CHECK + create_invitation + accept_invitation triple guard for `ownership_transfer_on_accept` ↔ `kind=member` | research.md R5 (Rev.2) |
| CI guard test (`test_no_email_subsystem_traces.py`) covering `.github/workflows/`, `docs/runbook/`, `apps/api/alembic/` | research.md R12 + R2 (Rev.2) |
| Trusted Device revoke on sensitive change — **reuse existing `TrustedDeviceService.revoke_all_for_user`** | spec.md FR-011-402 + research.md R10 (Rev.2) |
| Existing-user accept branch (`is_logged_in` flag in resolver context) | spec.md FR-011-106 + research.md R11 |
| `services/email.py` retain reduced (not rename) | research.md R9 |
| Polymorphic dismissal table `(audit_table, audit_log_id)` for `project_audit_log` + `platform_audit_log` | data-model.md (Rev.2) |
| Telemetry redaction surface: Sentry before_send + middleware + Nginx access log | research.md R13 (Rev.2) |
| Quickstart §11 moved to post-"you're done" FAQ to reconcile with SC-1 | research.md R14 (Rev.2) |

## Open Risks Carried into Implementation (not spec gaps)

- **R3 followup**: emergency `kid` rotation runbook must be exercised once before launch (table-top test). Tracked in `docs/runbook/invitation_token_kid_rotation.md` step "Initial validation".
- **R10 followup**: `TrustedDeviceService.revoke_all_for_user` (already exists in `services/trusted_device_service.py`) MUST be idempotent (calling it twice in the same TX is a no-op on the second call). Unit test enforces.
- **R13 followup**: Nginx access-log redaction of `X-Step-Up-Token` is operator-side config; the spec ships an example in `docs/operations/admin-recovery-flows.md` but cannot enforce it via application tests.
- **Invitation token envelope migration**: the 3-part → 4-part envelope change (R3 Rev.2) requires careful operator handling: on the first deploy operators MUST set both `INVITATION_TOKEN_KID_NEW` and `INVITATION_TOKEN_KID_OLD` (to the same legacy secret) plus `INVITATION_TOKEN_HMAC_KEY_OLD`. Tasks for the runbook capture this.

## Status

- [x] Phase 0: Research (`research.md`)
- [x] Phase 1: Design (`data-model.md`, `contracts/*.yaml`, `quickstart.md`)
- [x] Constitution Check (re-evaluated post-design)
- [ ] Phase 2: Tasks (`tasks.md` — generated by `/speckit-tasks`)
- [ ] Phase 3+: Implementation
