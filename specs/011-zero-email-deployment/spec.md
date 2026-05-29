# Feature Specification: Zero-email Deployment — Admin-mediated Lifecycle + Invitation Reuse

**Feature Branch**: `011-zero-email-deployment`
**Created**: 2026-05-21
**Status**: Draft (Rev.3.2, 2026-05-21)
**Supersedes (partial)**: `specs/010-email-verification-trusted-devices/` — the *Email Verification* portion of spec/010 is fully removed by this spec. The *Trusted Device* portion of spec/010 remains active and is adjusted only where this spec explicitly says so (FR-011-401, FR-011-402).
**Supersedes (named FRs)**: `specs/006-permissions-redesign/` FR-051 ("plain-text invitation tokens leave the process only through the post-commit email outbox") is formally superseded by FR-011-103.

## Revision History

- **Rev.0 (2026-05-21)**: Initial draft. Proposed new `project_invites` table with shareable multi-use links and standalone admin password reset.
- **Rev.1 (2026-05-21)**: Major rewrite based on architecture and security reviews. Reused existing `project_invitations`, added the missing Member-kind invitation HTTP endpoint, surfaced URL to the issuing admin, added bulk-invite and SU-bootstrap, reworked Removal Plan, added in-app banner mechanism, `must_change_password` middleware, two-phase migration, surgical `services/email.py` reduction.
- **Rev.3.2 (2026-05-21)**: Plan-phase Rev.2 three-way re-review (architect / security / Codex) caught residual textual drift in spec.md and plan.md not propagated by the Rev.2 rewrite of research.md / data-model.md / contracts/. Fixes: (a) `POST /web-api/v1/me/banners/{event_id}/dismiss` → `POST /web-api/v1/me/banners/dismiss` (body-shape, polymorphic over `audit_table` + `audit_log_id`) in FR-011-302, FR-011-310, Removal Plan, and Test Plan — contract and spec are now identical; (b) `INVITATION_TOKEN_KID_ACTIVE` / `INVITATION_TOKEN_KID_VERIFY_ALSO` → `INVITATION_TOKEN_KID_NEW` / `INVITATION_TOKEN_KID_OLD` (+ HMAC key vars) in Removal Plan §settings to match NFR-011-010 + research.md R3 + data-model.md §Settings; (c) `audit_events` residual references in Removal Plan §services and Open Questions replaced with `project_audit_log` / `platform_audit_log`; (d) "Snapshot regenerated" / "snapshot regeneration" residual in NFR-011-009 + Test Plan + plan.md replaced with the actual harness behaviour (YAML contracts vs live OpenAPI subset assertion, no snapshot file); (e) plan.md Technical Context Redis reference for step-up tokens removed; (f) plan.md Language/Version corrected to Python 3.11 (matches `apps/api/pyproject.toml`); (g) data-model.md invitation MAC representation corrected to `mac_b64u` with `_b64u_encode` wrapper (matches existing `services/invitation_service.sign_invitation_token`); (h) data-model.md `user_banner.py` MUST-validate "actor_user_id OR detail.target_user_id == authenticated user" anti-impersonation invariant (security review M-2) — was SHOULD; (i) research.md R3 §4 adds "MUST refuse to start if `INVITATION_TOKEN_HMAC_KEY_OLD` is unset on initial deploy" to prevent mid-flight legacy token invalidation; (j) research.md R9 fixes the "five remaining helpers" count (was "six plus one more grep-verified"); (k) admin-password-reset.yaml `X-Step-Up-Token` description corrected to `scope=admin_recovery` with `factors` AND-condition (Rev.3.1 left the old scope strings in place); (l) admin-password-reset.yaml step-up complete response carries an explicit "server MUST verify password before setting `factors.password=true`" invariant (security review M-1); (m) SC-1 reworded to "no required setup of SMTP / Resend / Mailpit / DKIM / DNS" (the success criterion is operational friction, not absence of the words in audience-framing or FAQ copy).
- **Rev.3.1 (2026-05-21)**: Plan-phase three-way review (architect / security / Codex) of `plan.md` / `research.md` / `data-model.md` / `contracts/` discovered six codebase-fact errors carried into Rev.3 spec language: (a) FR-011-206 said "Token format follow the existing service's conventions (signed via `web_session_secret`)" — accurate, but Rev.3 plan-phase research re-introduced a Redis-backed opaque alternative; this revision pins the spec to "extend the existing HS256 JWT with a `factors` claim", removing any Redis-storage option; (b) NFR-011-010 invitation token kid rotation was specified as if the existing envelope already had a kid slot — it does not (the current envelope is `{token}.{exp}.{mac}`, 3-part), so this revision specifies the new envelope as a 4-part `{token}.{exp}.{kid}.{mac}` plus a tail-comparison fallback for legacy 3-part tokens during the grace window; (c) NFR-011-001 grep target list now matches `research.md` R12 search paths (adds `.github/workflows/`, `docs/runbook/`, `apps/api/alembic/`); (d) the Removal Plan middleware row previously said the new and old middlewares "coexist for an interim where the new one is the active gate" — this contradicted the Rev.3 same-PR-swap rule; the row is rewritten to "land in step 3 in one atomic commit; old middleware source file deleted in step 10"; (e) the response-shape change to `POST /web-api/v1/projects/{project_id}/trusted-users` adding `invitation_url` (FR-011-103) is now explicit in the Removal Plan + Test Plan; (f) audit-event naming throughout this spec uses the existing codebase's `prefix.subject.verb` 3-segment pattern (`platform.project.archive`, `auth.password_reset_completed`, etc.) and the table targets are the existing `project_audit_log` / `platform_audit_log` tables (the spec previously referred to a non-existent `audit_events` table). Affected event-type strings: `project.member.invite.via_invitation`, `project.bootstrap_owner.transferred`, `platform.user.password_reset`, `platform.user.password_reset_self`, `auth.login.new_device`, `platform.api_key.revoked`, `auth.user.email_changed`, `platform.user.two_factor_reset`.
- **Rev.3 (2026-05-21)**: Three-way review of Rev.2 returned Converged from all three reviewers. This revision integrates the remaining minor fixes from the Codex review: corrected `FR-011-301` → `FR-011-306` typo in FR-011-206 step-up scope; reordered Implementation Plan so the new `ForcedPasswordChangeMiddleware` registration and the old `EmailVerificationEnforcementMiddleware` *runtime removal* land in the same step (step 3), eliminating the previously-allowed interim window where both middlewares could coexist as live gates; added `USER_BANNER_DISMISS_ACTION` to the ACTION matrix and to the gate_action coverage requirement; pivoted the step-up primitive from a new `services/step_up_auth.py` to an **extension of the existing `services/step_up_token_service.py` + `middleware/step_up.py`** to add password + 2FA AND-condition while preserving the existing WebAuthn-only assertion path; narrowed `NFR-011-001` grep regex to eliminate false positives on `allow_smtputf8`; separated frontend route `/invite/{token}` from API contract route `/web-api/v1/auth/invitations/{token}` in the Test Plan; reworded the step-up Open Question to reference the existing `web_session_secret` rotation policy rather than `kid` rotation (which applies only to invitation tokens, NFR-011-010).
- **Rev.2 (2026-05-21)**: Three-way review (architect / security / Codex) of Rev.1. Critical fixes: migration `0020` collision resolved by splitting into additive `0021` and destructive `0022`; corrected `send_2fa_reset_dispatched` helper name; added `trusted_expiry_notifier.py` to Removal Plan; expanded `ForcedPasswordChangeMiddleware` allowlist to cover v1 mirrors, `/health`, `/metrics`, `/favicon.ico`, OPTIONS preflight, and ASGI WebSocket scope; removed `/auth/change-password` from `PUBLIC_AUTH_PATHS`. High fixes: removed `send_2fa_reset_magic_link` entirely (admin-only 2FA recovery); added existing-user invitation acceptance path; classified `/invite/{token}` resolver and acceptance as `TOKEN_AUTH_ONLY` (no `gate_action`); strengthened admin self-reset step-up to require password + 2FA challenge; added per-issuer global rate-limit; added invitation token kid rotation alignment with Phase 17 A-12; added SU-bootstrap pre-transfer audit visibility; corrected middleware-position language; specified SAVEPOINT nesting for SU-bootstrap accept transaction; added OpenAPI snapshot regeneration NFR; extended Removal Plan to cover `hooks.server.ts`, e2e specs, `web-auth.ts`, login page `/forgot-password` link, `apps/api/README.md`; renamed `raw_token` outcome field to `signed_token_envelope`; added `Cache-Control: no-store`, telemetry redaction, banner-dismiss CSRF protection, email NFKC + casefold reuse, Trusted Device revocation on sensitive changes; unified generic-invalid copy for anti-enumeration; added bulk batch in-list duplicate pre-validation; aligned `user_banner_dismissals` GC window with banner age limit; added per-issuer bulk cap.

## Summary

Echoroo currently ships an email-verification subsystem that is silently dysfunctional in every environment except production-with-Resend-configured: in dev / preview / fresh-deploy, the verification email is never delivered because `RESEND_API_KEY` is empty and no SMTP catcher is bundled, leaving users with a permanently red "email unverified" badge with no way to clear it. The existing `ProjectInvitation` flow has the same defect — the invitation token is enqueued for outbound email via Resend and silently dropped when Resend is unconfigured, so a freshly deployed Echoroo cannot onboard collaborators at all. The existing self-service `/forgot-password` flow has the same defect.

Repairing these flows would require every Echoroo adopter to operate transactional email infrastructure (Resend account, domain verification, DKIM/SPF/DMARC DNS records, or an institutional SMTP relay). Echoroo's expected hosters are ecologists — research-domain experts, not infrastructure engineers — and an entire SMTP-and-DNS layer is an unrealistic adoption barrier.

This specification redirects Echoroo's authentication and onboarding lifecycle to a **zero-email default**: the application sends no email under any circumstance, all flows that previously relied on email are replaced by admin-mediated UI flows or invitation-URL handoff, and the bundled product no longer carries any SMTP / Resend / Mailpit dependency. Email verification is removed from the data model, the application boundary, and the frontend. Account recovery (password reset, 2FA reset, including the previously self-service "I lost my 2FA device, send me a magic link" flow) is handled exclusively through the existing admin tools. Collaborator onboarding uses the existing email-bound `ProjectInvitation` primitive, but instead of enqueuing an email, the invitation URL is returned directly to the issuing admin so they can hand it off through whatever out-of-band channel they prefer.

Echoroo still stores `users.email` as the login identifier and contact field, but it is treated as untrusted, opaque, operator-supplied data with no automated verification.

## Goals

1. A fresh `docker compose up` of Echoroo runs to completion and is fully functional with **zero** outbound-email configuration of any kind — no SMTP host, no API key, no DNS records.
2. Every flow that previously required an outbound email is replaced by an in-product UI or CLI flow that an admin can complete without leaving the application.
3. New collaborators can be granted access to a Restricted project at any non-owner role (Viewer / Member / Admin / Trusted overlay) without the deployment having any mail-sending capability.
4. A system superuser bootstrapping a project on behalf of a future owner can complete the bootstrap in a single admin operation that yields an invitation URL.
5. End-users who lose their password or 2FA device can recover access through admin intervention inside the application; no self-service email-driven recovery remains.
6. The Trusted Device functionality introduced by spec/010 continues to function. Its notification channel is reworked from email to in-app banner; in addition, Trusted Device records are revoked on sensitive account changes (password reset, email change, admin 2FA reset).
7. The codebase no longer carries Resend, Mailpit, `aiosmtplib`, or any other mail-delivery code path; deleting the email subsystem cannot regress because no SMTP egress code remains.

## Non-Goals

- Re-introducing outbound email as an opt-in feature for institutions that *do* have SMTP. (Out of scope; revisit only if real adopters demonstrate the need.)
- A user-facing API-key issuance UI. The backend `api_keys` schema and verifier exist but no end-user flow is wired; this spec leaves that state unchanged.
- Web push / mobile push notifications as replacements for the deleted email notifications. In-app banners and the audit log are sufficient for this iteration.
- Self-service password reset, self-service 2FA reset via magic link, or any other recovery flow that does not require admin intervention.
- Shareable multi-use invitation links. Each invitation is bound to a single recipient email by construction.

## Terminology

- **System superuser**: a user with `users.is_superuser = true`. Bootstrapped via `/setup/initialize` or `init_superuser` CLI. Single global role; not per-project.
- **Project admin**: a `ProjectMember` row with `role = ADMIN`. Per-project. May invite collaborators in their project but may **not** perform global recovery actions.
- **Admin (unqualified)**: in user stories, refers to whichever of the above is authorised for that flow. Each FR explicitly names the required role.

## Deployment Persona

The reference deployer for Echoroo is an ecologist running the application on a lab-managed server or research-cloud VM to support their own field team or collaborators. They:

- Understand `docker compose up` because it was in the README.
- Do not understand SMTP, DKIM, DMARC, Resend, or DNS records, and should not need to.
- Have a small fixed group of intended users (typically 5–50 people) whom they know personally.
- Communicate with their users via institutional email, lab Slack, Discord, or in-person — channels outside Echoroo's responsibility.
- Will accept a workflow in which "if a user loses access, they ask me (the operator / system superuser) directly and I fix it in the admin panel."
- Are the **system superuser** for their own deployment. Day-to-day collaboration features (issuing project invitations) are delegated to **project admins** they appoint per project.

Anything in this spec that contradicts that persona's capability is wrong.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Fresh deployment without configuring any email infrastructure (Priority: P1)

A research lab pulls Echoroo, runs `docker compose up`, opens the browser, completes the setup wizard with an admin email and password, and immediately uses the application normally. No email envelopes are sent. No SMTP error appears in the logs. No "email unverified" warning is shown anywhere in the UI.

**Why this priority**: This is the gating outcome for the entire spec. If a deployer cannot reach a working application without configuring email, the spec has failed.

**Independent Test**: Bring up the application with all email-related environment variables unset. Complete the setup wizard. Verify no `send_verification_email` code path exists, no `EMAIL_*` warning is logged, and the admin can navigate to all primary screens without any verification-related UI surface appearing.

**Acceptance Scenarios**:

1. **Given** a fresh deployment with no email config, **When** the operator completes `/setup/initialize`, **Then** the system superuser is created with no verification-related state and login succeeds immediately.
2. **Given** the system superuser is logged in, **When** they navigate to Profile, **Then** no "verify your email" banner, badge, button, or copy is rendered.
3. **Given** any source file in the deployed image, **When** searched for `RESEND`, `aiosmtplib`, `Mailpit`, `send_verification_email`, `send_password_reset_email`, `send_2fa_reset_magic_link`, or `email_verified_at`, **Then** the match count is zero outside this spec's documentation.

### User Story 2 — Inviting a single collaborator to a Restricted project (Priority: P1)

A project admin running a Restricted project (per spec/006) wants to bring in a new collaborator. They open the project's collaborator screen, choose a role (Viewer / Member / Admin) and target email, click "Issue invitation," and the response shows a one-shot invitation URL. They share the URL with the collaborator through their own channel. The collaborator opens the URL, either signs up (if new) or signs in (if already a user) using the bound email, and is automatically added to the project at the role the invitation specified.

**Why this priority**: Restricted projects cannot onboard members without this flow. The existing `kind=trusted` HTTP endpoint covers ephemeral overlay invitations only; regular-membership invitations are unreachable today.

**Independent Test**: As project admin on a Restricted project, issue an invitation for a chosen role. In a separate browser session, open the URL, complete signup with the bound email, and verify the new user appears in the project membership list at the correct role. Repeat with an existing user account, verifying that the existing account is added to the project without creating a duplicate user.

**Acceptance Scenarios**:

1. **Given** a project admin on a Restricted project's collaborator page, **When** they enter a target email and role and submit, **Then** the response includes an `invitation_url` of the form `/invite/{signed-token-envelope}` displayed exactly once for copy and the response carries `Cache-Control: no-store`.
2. **Given** an unused, unexpired invitation URL, **When** opened by a not-logged-in visitor, **Then** they reach a signup form prefilled with the bound email (read-only) and the role they will receive; for an already-logged-in visitor whose authenticated email matches the bound email, the form is replaced with a one-click "Accept this invitation" confirmation.
3. **Given** the visitor completes signup with the bound email + password + 2FA enrollment, **When** signup succeeds, **Then** they are added to the project at the invitation's role, the invitation is marked accepted, and the visitor lands inside the project.
4. **Given** an already-logged-in visitor whose authenticated email matches the bound email, **When** they confirm acceptance, **Then** their existing user account is added to the project at the invitation's role without creating a new user; if they are already a member, the request returns 409 with a clear "already a member" message.
5. **Given** the visitor (logged-in or not) submits an email different from the bound one, **When** they submit, **Then** the request is rejected with a generic invitation-invalid message indistinguishable from any other failure cause.
6. **Given** an invitation is expired or revoked, **When** opened, **Then** a generic "invitation no longer valid" page is rendered with response status, body length, and end-to-end timing indistinguishable from a never-issued token (±50ms).

### User Story 3 — Bulk-inviting many collaborators in one operation (Priority: P1)

A project admin onboarding a research group of 20 people needs to issue invitations for everyone in a single operation rather than 20 separate form submissions. They open the collaborator screen, switch to bulk mode, paste a newline-separated list of email addresses, choose one role to apply to all, and submit. The response lists every invitation URL paired with its target email, ready to copy. The admin shares each URL with its target through their own channels.

**Why this priority**: Even a small lab (5–20 people) becomes a usability cliff if every invitation requires a separate single-target operation. Bulk issuance keeps the per-deploy onboarding effort proportional to the lab's size, not its number of admin click-throughs.

**Independent Test**: Paste a list of 10 emails into the bulk-invite form, submit, and verify exactly 10 invitation rows are created (one per email), each with its own URL, and that the response table renders them paired correctly.

**Acceptance Scenarios**:

1. **Given** an admin on the collaborator page in bulk mode, **When** they submit 10 valid emails and one role, **Then** 10 separate invitation rows are created, each with `kind=member` and that role.
2. **Given** any submitted email is malformed, **When** the request is processed, **Then** the entire request is rejected with a per-row error listing, no invitations are created, and the admin can fix and resubmit.
3. **Given** the submitted list contains the same email twice in one request, **When** the request is processed, **Then** the request is rejected at validation with a "duplicate email in request" error and no invitations are created.
4. **Given** an email in the list already has an outstanding pending invitation to the same project, **When** the request is processed, **Then** that row is reported as `status="duplicate_pending"` in the response and the remaining rows are processed normally (per-row SAVEPOINT semantics).
5. **Given** the response is returned, **When** the admin views the result, **Then** the table shows every email and its corresponding `invitation_url` exactly once with a "copy all as CSV" affordance, and the response carries `Cache-Control: no-store`.
6. **Given** the admin closes the browser tab before copying, **When** they re-open the collaborator screen, **Then** the URLs are **not** recoverable — the admin must revoke and reissue per row. (Plain-text token confidentiality is preserved.)

### User Story 4 — System superuser resets a user's forgotten password (Priority: P1)

A user contacts the system superuser out-of-band: "I forgot my password." The superuser opens the admin user-management screen, selects the user, clicks "Reset password," **completes a step-up authentication challenge (password + 2FA)**, and is shown a freshly generated one-time temporary password. The superuser copies the temporary password and delivers it to the user through the same out-of-band channel. The user logs in with the temporary password, is forced to change it immediately before reaching any other route, and continues.

**Why this priority**: The previously available `/forgot-password` self-service flow relied on outbound email and is being removed. Without superuser-mediated recovery, password loss is a permanent lockout.

**Independent Test**: As system superuser, complete the step-up challenge, then reset another user's password. Capture the one-time password from the reveal dialog. In a separate session, log in as that user with the temporary password, observe the forced-change screen, set a new password, and verify the temporary password no longer works, the forced-change middleware blocked every other route during the interlude, the target user's other active sessions were invalidated, and the target user's trusted-device records were revoked.

**Acceptance Scenarios**:

1. **Given** the system superuser on the admin user-management screen, **When** they click "Reset password" for a specific user, **Then** they are first prompted to complete step-up authentication (current password re-entry **and** a TOTP challenge within the last 5 minutes; **TOTP-only initial release** — WebAuthn step-up is reserved for a follow-up spec); the reset is blocked until step-up succeeds, then a confirmation dialog explaining the consequences is shown.
2. **Given** the superuser confirms the reset, **When** the action completes, **Then** the screen displays a randomly generated temporary password in a click-to-reveal dialog with copy-to-clipboard that auto-clears after 60 seconds; the user's stored password hash is updated to that value; `temp_password_expires_at` is set to `now() + 24h`; `must_change_password` is set; **all other active sessions of the target user are immediately invalidated**; and **all trusted-device records of the target user are revoked**.
3. **Given** the target user logs in with the temporary password before 24 hours have elapsed, **When** authentication succeeds, **Then** every subsequent request to any path other than the forced-change allowlist returns `423 Locked` until they complete a password change.
4. **Given** the user submits a new password meeting policy, **When** the change succeeds, **Then** the `must_change_password` flag and `temp_password_expires_at` are cleared and they proceed normally.
5. **Given** the superuser reset action, **When** completed, **Then** an audit entry of type `platform.user.password_reset_by_superuser` is created naming actor, target, optional reason, and timestamp; the temporary password value never appears in any log, response, or persistent store other than the password-hash column.
6. **Given** the superuser resets their own password (allowed but special-cased), **When** the action completes, **Then** the audit entry uses `platform.user.password_reset_self` to distinguish actor-target identity; the step-up challenge (FR-011-206) is enforced; on completion all other sessions of the superuser are invalidated and trusted devices of the superuser are revoked.
7. **Given** the superuser resets a user repeatedly within the 24h TTL, **When** each subsequent reset commits, **Then** the most recent temp password overrides the prior one, `temp_password_expires_at` is refreshed, and any prior temp password is immediately invalidated.

### User Story 5 — System superuser resets a user's lost 2FA device (Priority: P2)

A user lost their phone with the authenticator app. The system superuser opens the admin user-management screen, selects the user, clicks "Disable 2FA," completes step-up authentication, confirms, and tells the user (out-of-band) to log in and re-enroll. This functionality already exists per Phase 17 A-11 and is referenced here only to confirm it remains the prescribed recovery path; the changes from this spec are limited to enforcing step-up auth on the action, removing the previously-emailed "2FA reset applied" notification (replaced by in-app banner + audit), and revoking the target user's trusted-device records and active sessions on completion.

**Why this priority**: Recovery exists today; this story documents the chosen path and the new constraints layered on top.

**Independent Test**: Trigger admin 2FA disable, observe step-up enforced, verify target user's active sessions invalidated, trusted devices revoked, and `platform.user.two_factor_reset_by_superuser` audit entry created. No email is enqueued anywhere.

**Acceptance Scenarios**:

1. **Given** the existing admin 2FA reset flow per Phase 17 A-11, **When** invoked, **Then** the actor must complete step-up authentication (FR-011-206); on completion all of the target user's active sessions are invalidated, all of the target user's trusted-device records are revoked, an `platform.user.two_factor_reset_by_superuser` audit entry is recorded, and an in-app banner is enqueued for the target user. No outbound email is attempted.

### User Story 6 — System superuser bootstraps a project on behalf of a future owner (Priority: P2)

A system superuser wants to set up a research project intended to be owned by a colleague who does not yet have an Echoroo account. From the project-creation form, the superuser fills in the project name, configuration, and an `intended_owner_email` field. On submit, Echoroo creates the project owned by the superuser as a placeholder, atomically issues an `Admin`-role invitation to the intended owner's email with `ownership_transfer_on_accept = true`, and returns the invitation URL. The superuser hands the URL to the intended owner. The intended owner opens the URL, registers (or accepts as an existing user), and on successful invitation acceptance, the project ownership is transferred to them in the same transaction and the superuser is demoted to Admin.

**Why this priority**: Without this, the superuser must perform four separate operations (create project, invite, transfer ownership, demote self) to bootstrap a project for someone else. For a lab with several students each owning their own thesis project, this becomes a meaningful operational burden.

**Independent Test**: As superuser, create a project with `intended_owner_email = alice@univ.edu`. Verify the project is initially owned by the superuser and an `Admin` invitation with the transfer flag exists for Alice. In a separate session, accept the invitation as Alice. Verify the project's `owner_id` is now Alice, the superuser's membership row reads `role = ADMIN`, and a composite audit entry records the automatic transfer naming both parties and listing every action the superuser performed on the project between creation and acceptance.

**Acceptance Scenarios**:

1. **Given** the system superuser on the project creation form, **When** they fill `intended_owner_email` and submit, **Then** the project is created (owned by the superuser), an `Admin` invitation with `ownership_transfer_on_accept = true` is issued for that email, the response includes the project record plus the invitation URL, and the response carries `Cache-Control: no-store`.
2. **Given** the intended owner accepts the invitation, **When** acceptance commits, **Then** the same database transaction transfers `Project.owner_id` to the accepting user, demotes the superuser's `ProjectMember` row to `role = ADMIN`, increments invitation use, and writes a composite audit entry of type `project.ownership.bootstrap_transfer`.
3. **Given** the composite audit entry, **When** the new owner opens their activity view, **Then** they can see a summary of every project-scoped action the superuser performed on the project between project creation and the ownership transfer (project config changes, dataset uploads, invitation issuances, etc.) so the new owner is not blind to the pre-transfer history.
4. **Given** the intended owner declines, revokes, or lets the invitation expire, **When** the invitation reaches a terminal non-accepted state, **Then** the project remains owned by the superuser; the auto-transfer never fires; the superuser can later re-issue or transfer manually.
5. **Given** the `intended_owner_email` field is empty, **When** the project is created, **Then** behavior is the existing default (superuser becomes owner, no invitation issued).
6. **Given** any user other than the system superuser opens the project creation form, **When** they submit with `intended_owner_email`, **Then** the field is silently ignored. (Silently rather than 403 to deny enumeration: a non-superuser does not learn the field exists.)

### User Story 7 — A user who notices something is wrong checks the audit log (Priority: P2)

Several flows previously sent notification emails: a new device logged in, your API key was revoked, your email was changed, your 2FA was reset. With email removed, these events surface only in-app: a sticky banner on next login (or in-session if a long-lived session is active) plus a permanent entry in the user's own activity view (backed by the audit log).

**Why this priority**: Notifications had real defensive value (a user noticing a hostile login on their account). The replacement is weaker than email but must be at least *present* so a vigilant user can investigate.

**Independent Test**: Trigger each of the formerly-emailed events (new-device login, API key revoke, email change, admin 2FA reset) and verify they appear in the user's activity view and as a sticky banner that remains for at least 7 days or until dismissed.

**Acceptance Scenarios**:

1. **Given** a user logs in from a device with no recognized trusted-device cookie, **When** the login completes, **Then** an audit entry of type `auth.login.new_device` is recorded and a sticky banner becomes visible to that user the next time their browser interacts with the application.
2. **Given** an admin revokes a user's API key, **When** the action completes, **Then** an audit entry of type `platform.api_key.revoke` is recorded against the target user and a banner appears to them.
3. **Given** a user's email address is changed by themselves or by an admin, **When** the change is committed, **Then** an audit entry of type `platform.user.email_changed` is recorded with old and new values redacted to local-part hash; all of that user's active sessions are immediately invalidated forcing re-login; **all of that user's trusted-device records are revoked**; and a 24-hour cool-off prevents another email or password change.
4. **Given** any of the above events, **When** the user opens their activity view, **Then** they can see all such entries in reverse chronological order with timestamps.
5. **Given** a user dismisses a banner, **When** they return on a later session, **Then** that specific banner does not reappear (within the 30-day banner-age window), but the corresponding entry remains visible in the activity view indefinitely.

### Edge Cases

- An invitation opened against a project that is later deleted: the response is the generic "invitation no longer valid" page, indistinguishable from any other failure cause (anti-enumeration).
- An invitation whose role no longer applies after a visibility downgrade: same generic invalid page; the issuer sees the same status in the invitation list and may revoke.
- A user whose admin-reset temporary password has expired (24h TTL exceeded before they used it): they cannot log in with it; the admin must reset again.
- A system superuser attempting to reset their own password through the admin UI: allowed, recorded under `platform.user.password_reset_self`, but step-up authentication is enforced (FR-011-206).
- An attempt to register without a valid invitation token on a Restricted project: rejected with the same generic "you need an invitation" copy regardless of whether the project exists.
- An invitation whose issuer is later removed from the project's admin set: the invitation remains valid until expiry or revocation; the audit log captures the original issuer.
- Concurrent acceptance attempts of the same invitation: the database `UPDATE ... WHERE status='pending' RETURNING` pattern ensures exactly one wins; the loser sees the same "no longer valid" page.
- An invitation accepted by an already-logged-in user whose email matches the bound email but who is already a project member: 409 with "already a member"; no duplicate `ProjectMember` row is created.
- A project deletion that occurs while an SU-bootstrap invitation for that project is still pending: the invitation falls into the generic invalid path.
- Browser back / refresh on the temp-password reveal dialog or invitation URL response: the response is marked `Cache-Control: no-store, no-cache, must-revalidate, private` and the in-memory render is destroyed on navigation; no replay is possible.

## Functional Requirements

### Removal — Email Verification Subsystem (FR-011-001..014)

- **FR-011-001**: The application MUST NOT send any email under any circumstance. All code paths that previously called the Resend SDK MUST be removed.
- **FR-011-002**: The `users.email_verified_at` column MUST be dropped via the forward-only destructive Alembic migration `0022_email_subsystem_removal`.
- **FR-011-003**: The `email_verification_tokens` table and the `password_reset_tokens` table MUST be dropped in `0022`.
- **FR-011-004**: The `EmailVerificationEnforcementMiddleware` MUST be removed from the middleware stack and the source tree.
- **FR-011-005**: All routes under `/web-api/v1/auth/verify-email*`, `/api/v1/auth/verify-email*`, `/web-api/v1/auth/password-reset/*`, `/api/v1/auth/password-reset/*`, and the existing `/auth/2fa-reset/magic-link*` self-service path MUST be removed. The admin-issued 2FA disable flow per Phase 17 A-11 is retained.
- **FR-011-006**: All settings under the `EMAIL_VERIFICATION_*`, `RESEND_*`, and `EMAIL_FROM` namespaces MUST be removed from `core/settings.py`, `.env.example`, and any compose file environment block.
- **FR-011-007**: The `resend` Python package MUST be removed from `pyproject.toml`. No replacement mail library (`aiosmtplib`, `smtplib`, etc.) may be added.
- **FR-011-008**: The `services/email.py` file MUST be reduced. Delete: the Resend SDK initialiser (`resend.api_key = settings.RESEND_API_KEY`), `send_verification_email`, `send_password_reset_email`, and `send_2fa_reset_magic_link`. Rewrite to enqueue in-app banner events and audit entries (not email): `send_login_notification`, `send_email_change_notification`, `send_2fa_reset_dispatched`, `send_api_key_scope_degrade_email`, `send_api_key_revoke_email`. (`send_2fa_reset_dispatched` is the real function name; an earlier spec revision listed it incorrectly as `send_2fa_reset_applied_notification`.) The module name may be retained or renamed to `services/user_event.py`; either choice MUST eliminate all remaining `import resend` references.
- **FR-011-009**: The HTTP `/setup/initialize` and CLI `init_superuser` paths MUST NOT set or reference any verification-related field on the created user.
- **FR-011-010**: The Outbox dispatcher worker `email_verification_dispatcher.py` MUST be removed. The producer-side enqueue of email-bound outbox rows MUST be removed from both `services/invitation_service.trigger_post_commit_side_effects` and `workers/trusted_expiry_notifier`. The `email_verification_dispatcher` and any consumer that exclusively handles email-bound outbox rows MUST be removed. The shared `outbox_events` table itself is retained for other event types.
- **FR-011-011**: The frontend `routes/(auth)/verify-email/` directory and `routes/(auth)/forgot-password/` directory and all components, types, hooks, e2e specs, and i18n strings whose sole purpose is email verification or self-service password reset MUST be removed. The `User` type's `email_verified_at` field MUST be removed from all frontend type definitions, store derivations, and the `hooks.server.ts` session shape.
- **FR-011-012**: The README quickstart and `apps/api/README.md` MUST be updated to remove any reference to SMTP, Resend, Mailpit, DKIM, or DNS as a deployment step.
- **FR-011-013**: Any login-page link to `/forgot-password` MUST be removed; no replacement link is added.
- **FR-011-014**: Any e2e Playwright spec that referenced the removed flows MUST be deleted, with new specs (Test Plan) replacing the lost coverage.

### Addition — Member-kind Invitation Endpoint (FR-011-101..109)

- **FR-011-101**: A new HTTP endpoint `POST /web-api/v1/projects/{project_id}/invitations` MUST be added that issues a `ProjectInvitation` with `kind=member`, a chosen `role ∈ {VIEWER, MEMBER, ADMIN}`, a chosen `email`, and the standard 7-day TTL. The endpoint MUST be gated by `gate_action` under a new ACTION constant `PROJECT_MEMBER_INVITATION_ISSUE_ACTION` (project scope, required permission `MANAGE_MEMBERS`).
- **FR-011-102**: The response of `POST /web-api/v1/projects/{project_id}/invitations` MUST include a one-shot `invitation_url` field of the form `https://<host>/invite/{signed-token-envelope}`. The signed-token envelope follows the existing HMAC pattern in `invitation_service` and MUST honour the Phase 17 A-12 env-driven kid rotation pattern with dual-verify of the previous kid for the active invitation TTL (7d) plus a configurable grace window. The response MUST carry `Cache-Control: no-store, no-cache, must-revalidate, private`. The `invitation_url` value MUST NOT appear in access logs, telemetry events, or any redaction-eligible field; the audit entry MUST record only the invitation id and recipient `email_hash`.
- **FR-011-103**: The existing Trusted-overlay invitation endpoint (`POST /web-api/v1/projects/{project_id}/trusted-users`) MUST be modified to include the `invitation_url` field in its response, replacing the outbound-email side effect. FR-051 of spec/006 ("plain-text invitation tokens leave the process only through the post-commit email outbox") is **formally superseded** for this spec — the token leaves the process exclusively through the issuing admin's API response, never persists past that single HTTP turn, and is recovered by no other endpoint.
- **FR-011-104**: The `services/invitation_service.create_invitation` callable MUST stop constructing the `InvitationMailPayload` carrier and stop populating the outbox-enqueue side effect for the email row. The outcome dataclass MUST expose a `signed_token_envelope` field (the value to embed in `invitation_url`); the previous `mail_payload` field MUST be removed. Consumers (Member and Trusted endpoint handlers, SU bootstrap) MUST read `signed_token_envelope` directly.
- **FR-011-105**: Opening `/invite/{signed-token-envelope}` (a frontend route that proxies to a new `GET /web-api/v1/auth/invitations/{signed-token-envelope}` resolver) MUST resolve the invitation context (project name, role, bound email). The resolver and the corresponding `POST /web-api/v1/auth/invitations/{signed-token-envelope}/accept` MUST be classified as `TOKEN_AUTH_ONLY` (no `gate_action` middleware; authenticated by token presence alone) and registered in the public-token allowlist per spec/007. They are not part of `PUBLIC_AUTH_PATHS` (which is for unauthenticated bootstrap paths) but are similarly exempt from `gate_action`.
- **FR-011-106**: Successful acceptance MUST be atomic in a single database transaction. The transaction MUST:
  1. Branch on the visitor's authentication state:
     - **New user (not logged in)**: validate signup payload (password + 2FA enrollment), create the user, then proceed to step 2 with that user.
     - **Existing user (logged in)**: verify `canonicalize_email(authenticated_user.email) == canonicalize_email(invitation.email)` using the existing `services.invitation_service.canonicalize_email` (NFKC normalise + casefold). If mismatch, abort with the generic invalid page.
  2. Mark the invitation via `UPDATE project_invitations SET status='accepted', accepted_at=now() WHERE id=:id AND status='pending' AND expires_at > now() RETURNING *` (named placeholders MUST be used; no string concatenation). If zero rows returned, abort the transaction with the generic invalid page.
  3. Apply the role:
     - `kind=member`: insert into `project_members(role=invitation.role)` unless the user is already a member, in which case return 409 "already a member" without modifying anything.
     - `kind=trusted`: insert into `project_trusted_users` with the existing overlay semantics.
  4. If `ownership_transfer_on_accept = true`, perform FR-011-123 in the same transaction.
  5. Write audit entries (`project.member.invite_accepted_signup` if a new user, `project.member.invite_accepted` / `project.trusted_user.invite_accepted`, and FR-011-123's composite entry if applicable).
- **FR-011-107**: If the invitation is in any terminal status, has expired, refers to a deleted project, or refers to a role that no longer exists for the project's current visibility, opening the URL MUST render an unambiguous "invitation no longer valid" page with no signup form and no information that distinguishes the failure reasons. Response status, body length, and end-to-end timing MUST be indistinguishable across failure causes (±50ms).
- **FR-011-108**: The existing admin invitation-listing UI MUST be extended to include `kind=member` rows alongside the existing `kind=trusted` rows. Each row MUST allow the project admin to revoke an active invitation immediately. The original token is **not** recoverable; if the admin needs to re-send, they revoke and reissue.
- **FR-011-109**: Public projects MUST NOT require invitations; they remain registerable through the existing open-signup flow per spec/006 US1. The new endpoint is reachable only on Restricted projects.

### Addition — Bulk Invitation Endpoint (FR-011-110..115)

- **FR-011-110**: A new HTTP endpoint `POST /web-api/v1/projects/{project_id}/invitations/bulk` MUST accept a JSON body of the form `{ "role": "member|viewer|admin", "emails": ["a@x", "b@x", ...] }` with a maximum of 50 emails per request.
- **FR-011-111**: The bulk endpoint MUST perform two validation passes before issuing any invitation: (a) every email is well-formed; (b) `len(set(canonicalize_email(e) for e in emails)) == len(emails)` — no in-list duplicates. Any validation failure rejects the entire request with a per-row error array; no rows are created.
- **FR-011-112**: For each email in the validated list, the bulk endpoint MUST attempt issuance as if `POST /web-api/v1/projects/{project_id}/invitations` had been called for it individually. Per-row failure (e.g., already has a pending invitation, hits per-issuer rate-limit) MUST be reported in the response row as `status="duplicate_pending"` or `status="rate_limited"` without rolling back successfully-issued rows. SAVEPOINT semantics MUST be used to isolate per-row failure (NFR-011-008).
- **FR-011-113**: The response MUST be an array of `{ email, status, invitation_url? }` records, one per submitted email, in submission order. `invitation_url` is populated only for `status="issued"` rows. The response MUST carry `Cache-Control: no-store, no-cache, must-revalidate, private`.
- **FR-011-114**: The bulk endpoint MUST share the existing per-issuer-per-project rate-limit budget with the single-invite endpoint (FR-056 of spec/006) and additionally MUST be subject to a per-issuer **global** rate-limit (across all projects) of 200 invitations/hour and 1000/day per the Phase 17 A-6 sliding window pattern.
- **FR-011-115**: The 50-row maximum is the same operational ceiling used by analogous bulk endpoints (e.g., dataset bulk-upload Phase 13). The figure is conservative; raising it MAY happen as a follow-up if real adopters request it.

### Addition — System Superuser Project Bootstrap (FR-011-120..125)

- **FR-011-120**: The project creation endpoint MUST accept an optional `intended_owner_email` field. The field MUST be silently ignored unless the requesting user has `users.is_superuser = true`. Silent ignoring (not 403) denies field-existence enumeration to non-superusers.
- **FR-011-121**: When the system superuser supplies `intended_owner_email`, the create-project transaction MUST atomically: (a) create the project with `owner_id = superuser.id`, (b) issue a `kind=member, role=ADMIN` invitation for the supplied email with `ownership_transfer_on_accept = true`, (c) include the `invitation_url` in the create-project response alongside the new project record.
- **FR-011-122**: A new boolean column `project_invitations.ownership_transfer_on_accept BOOLEAN NOT NULL DEFAULT false` MUST be added in the additive migration `0021_zero_email_additive` to support FR-011-121.
- **FR-011-123**: When `accept_invitation` processes a row with `ownership_transfer_on_accept = true`, the same transaction (FR-011-106) MUST perform the following inside a nested SAVEPOINT:
  1. Capture the prior owner's audit-event history on the project from `created_at` to `now()` (filter `project_audit_log WHERE actor_user_id = :prior_owner AND project_id = :project_id`; `platform_audit_log` rows are not project-scoped and are excluded) into a `pre_transfer_action_summary` JSON blob (event types and timestamps, with PII redacted per Phase 17 A-13).
  2. Update `Project.owner_id = accepting_user.id`.
  3. Upsert `ProjectMember(user=prior_owner, role=ADMIN)`; if the row exists it is updated, otherwise inserted.
  4. Emit a single composite audit entry of type `project.ownership.bootstrap_transfer` with `prior_owner`, `new_owner`, `pre_transfer_action_summary`, and `at`.
  
  Failure within the SAVEPOINT rolls back the SAVEPOINT and the parent transaction, leaving the project as the superuser's. Audit-event writes for the outer composite entry are part of the same TX commit. Read-side projections of the activity view (FR-011-307) MUST include the composite entry's `pre_transfer_action_summary` so the new owner is not blind to the pre-transfer history.
- **FR-011-124**: If a bootstrap invitation expires, is revoked, or is declined, the project remains owned by the superuser; the transfer never fires. The superuser may revoke and re-issue, or use the existing Phase 12 transfer-ownership endpoint manually thereafter.
- **FR-011-125**: A user other than the system superuser submitting `intended_owner_email` results in the field being silently dropped server-side; the project is created with that user as owner, no invitation is issued, and no audit entry mentions the dropped field.

### Addition — Admin Password Reset (FR-011-201..210)

- **FR-011-201**: A new endpoint `POST /web-api/v1/admin/users/{user_id}/reset-password` MUST be added, gated by `ADMIN_USER_RESET_PASSWORD_ACTION` (user scope, **system-superuser-only**: only `users.is_superuser = true` callers may invoke). Project admins MUST NOT have access to this action; if a user needs recovery on a deployment with multiple project admins, they contact the system superuser.
- **FR-011-202**: The reset action MUST generate a cryptographically random temporary password meeting the existing password policy and return it in a click-to-reveal dialog payload. The frontend MUST render the value with `Cache-Control: no-store, no-cache, must-revalidate, private`, `Referrer-Policy: no-referrer`, no browser back/forward retention, copy-to-clipboard with automatic clipboard clearing after 60 seconds, and a single confirmation button that destroys the in-memory value on close.
- **FR-011-203**: The reset action MUST set `users.must_change_password = true`, `users.temp_password_expires_at = now() + 24 hours`, and MUST immediately invalidate all other active sessions of the target user and revoke all of the target user's trusted-device records. Repeated resets within the TTL MUST overwrite the prior temp password atomically; only the most recent value is valid.
- **FR-011-204**: A new `ForcedPasswordChangeMiddleware` MUST be inserted into the middleware stack at the same topological position previously occupied by `EmailVerificationEnforcementMiddleware` (= after AuthRouter / session decode middleware, before TwoFactorEnforcement middleware in LIFO execution order — i.e. principal is already attached). When the authenticated principal's `must_change_password = true`, the middleware MUST return `423 Locked` with a `Location: /change-password` header for every request path **other than** the allowlist below. The middleware MUST cover both `/web-api/v1/*` and `/api/v1/*` mirrors, and the ASGI HTTP scope; WebSocket scope MUST close with code 1011 (Internal Error) if encountered (no WebSocket exists today; this future-proofs).
  
  **Allowlist (request passes through normally)**:
  - `POST /web-api/v1/auth/change-password`
  - `POST /api/v1/auth/change-password`
  - `POST /web-api/v1/auth/logout`
  - `POST /api/v1/auth/logout`
  - `GET /health`
  - `GET /metrics`
  - `GET /favicon.ico`
  - `OPTIONS` method on any path (CORS preflight)
  - Static asset prefix `/static/`
  
  `/auth/change-password` MUST NOT be added to `PUBLIC_AUTH_PATHS`. It is an authenticated endpoint; the forced-change middleware allows it through *because the user is authenticated and being routed to the only screen they may reach*. The endpoint itself preserves CSRF protection and session validation.
- **FR-011-205**: Successful password change MUST clear both `must_change_password` and `temp_password_expires_at` and MUST invalidate every other active session of the user.
- **FR-011-206**: The system superuser performing any of the actions in FR-011-201..210 (admin password reset and self-reset) or the admin 2FA disable flow surfaced by FR-011-306 / US5 / Phase 17 A-11 MUST complete a **step-up authentication challenge** within the last 5 minutes. The challenge requires BOTH (a) re-entry of the current password AND (b) successful completion of a 2FA challenge (TOTP code or WebAuthn assertion). Password-only re-entry is insufficient. The 5-minute window starts from the moment the step-up succeeds; subsequent sensitive actions within that window re-use the same step-up token without re-prompting. **Implementation**: extend the existing `services/step_up_token_service.py` (`issue_step_up_token` / `verify_step_up_token`) + `middleware/step_up.py` (`require_step_up_token`). The existing service mints an **HS256 JWT** signed with `settings.web_session_secret` whose payload is `{sub, type='step_up', scope, ss, aid, jti, iat, exp}` (Phase 16 Batch 6g-3). This spec adds two changes in-place: (i) a new claim `factors: { password: true|false, second_factor: 'totp'|'webauthn'|null }` representing the AND-condition completion, and (ii) a new scope value `admin_recovery` distinct from the existing `admin_destructive` so the verifier can refuse webauthn-only tokens for FR-011-201..210 / FR-011-306. The token continues to be transmitted via the existing `X-Step-Up-Token` header (current `middleware/step_up.py` convention). No new Redis state, no new module. `security_stamp` rotation continues to invalidate outstanding step-up tokens; password reset / 2FA reset rotate `security_stamp` per existing behaviour, providing immediate revocation when the target user is recovered. **Initial release scope (Step 12 closeout, 2026-05-29)**: the issuance endpoints `POST /web-api/v1/auth/step-up/begin` and `POST /web-api/v1/auth/step-up/complete` (T300 / T301) ship **TOTP-only**. The `factors_required` response advertises `["password", "totp"]`; the `complete` request body accepts only the TOTP variant. Users whose only second factor is WebAuthn receive a 409 (`step_up_2fa_not_enrolled`) directing them to enrol TOTP. The verifier middleware (`require_step_up_token`) continues to honour `second_factor in {"totp", "webauthn"}` so a future release can re-introduce the WebAuthn issuance path without re-validating the downstream gates. WebAuthn step-up is reserved for a follow-up task / spec; the 401 envelope on `complete` is intentionally uniform (`error_code = "step_up_factor_invalid"`) across password / TOTP / challenge mismatch / challenge expired so the issuance handler does not leak a per-factor side channel.
- **FR-011-207**: The temporary password value MUST never be written to application logs, audit logs, the response of any endpoint other than the single reset action's reveal dialog, or any persistent store other than `users.password_hash`. Telemetry / OpenAPI examples / Sentry-style scrubbers MUST register the field for redaction.
- **FR-011-208**: All reset and self-reset actions MUST emit an audit entry naming actor, target, optional reason field, and timestamp. The reason field of admin password-reset entries, the `revoked_reason` of invitations, and any free-form text input introduced by this spec MUST be registered with the Phase 17 A-13 operator free-form PII detector before merge.
- **FR-011-209**: If `temp_password_expires_at` has passed, authentication with that temp value MUST fail with a generic "invalid credentials" error; no signal is given that the value was once valid. The superuser MUST re-issue.
- **FR-011-210**: An admin self-reset (`platform.user.password_reset_self`) MUST follow the same flow as a target-user reset, with the actor and target being the same user, must enforce step-up (FR-011-206), and on completion MUST invalidate all other sessions of the superuser and revoke all of the superuser's trusted-device records.

### Addition — In-app Banner Notifications (FR-011-301..310)

- **FR-011-301**: A new table `user_banner_dismissals (user_id UUID, audit_table TEXT, audit_log_id UUID, dismissed_at TIMESTAMPTZ, PRIMARY KEY (user_id, audit_table, audit_log_id))` MUST be added in `0021_zero_email_additive`. The composite `(audit_table, audit_log_id)` references either `project_audit_log(id)` (when `audit_table = 'project_audit_log'`) or `platform_audit_log(id)` (when `audit_table = 'platform_audit_log'`); a CHECK constraint enforces the enum. Because Postgres does not support polymorphic FKs, FK constraints are NOT declared on `(audit_table, audit_log_id)` — instead, application-level invariants in `services/user_banner.py` enforce that the dismissed row exists in the named table at write time.
- **FR-011-302**: A new endpoint `GET /web-api/v1/me/banners` MUST return audit events targeting the authenticated user that (a) have not been dismissed by this user and (b) are at most 30 days old. A companion `POST /web-api/v1/me/banners/dismiss` MUST record the dismissal, accepting a JSON body of `{audit_table: "project_audit_log"|"platform_audit_log", audit_log_id: UUID}` (the body shape mirrors `user_banner_dismissals`' polymorphic composite key, FR-011-301). The dismiss endpoint MUST require CSRF protection; it MUST NOT appear in `PUBLIC_AUTH_PATHS` or any CSRF-exempt list. Repeated dismiss of the same `(audit_table, audit_log_id)` is idempotent (returns 204 each time). The endpoint MUST validate at write time that the targeted audit row's `actor_user_id` or `detail.target_user_id` is the authenticated user; otherwise return 404 (anti-enumeration).
- **FR-011-303**: A login from a device with no recognized trusted-device cookie MUST record an audit entry of type `auth.login.new_device` against the user. This entry surfaces through `GET /me/banners` until dismissed.
- **FR-011-304**: Revocation of one of the user's API keys MUST record an audit entry of type `platform.api_key.revoke` against that user. This entry surfaces through `GET /me/banners` until dismissed.
- **FR-011-305**: Change to the user's email address MUST record an audit entry of type `platform.user.email_changed` against that user, immediately invalidate all of that user's active sessions, **revoke all of that user's trusted-device records**, set a 24-hour cool-off preventing further `platform.user.email_changed` or password-change actions on the user, and surface via `GET /me/banners`.
- **FR-011-306**: Admin 2FA disable per Phase 17 A-11 MUST record an audit entry of type `platform.user.two_factor_reset_by_superuser` and surface via `GET /me/banners` until dismissed. There is no `user.2fa_reset_self` event because the self-service magic-link flow is removed (FR-011-005).
- **FR-011-307**: A new endpoint `GET /web-api/v1/me/activity` MUST return all audit events targeting the authenticated user in reverse chronological order, with optional cursor-based pagination. Dismissal does not affect this list. The 30-day banner age limit does not apply (activity is the permanent record).
- **FR-011-308**: The frontend layout MUST render undismissed banners as a non-modal stack at the top of every authenticated page. Each banner MUST be individually dismissable, link to the activity view for details, and remain sticky across browser sessions until dismissed (within the 30-day window).
- **FR-011-309**: `user_banner_dismissals` rows for `audit_event` rows older than 30 days MAY be garbage-collected; the GC window MUST align with the banner age limit (FR-011-302) so that an age-trimmed audit event whose dismissal row is also GC'd does not re-surface.
- **FR-011-310**: `GET /me/banners`, `POST /me/banners/dismiss`, and `GET /me/activity` MUST each be gated by `gate_action` under, respectively, `USER_BANNER_LIST_ACTION`, `USER_BANNER_DISMISS_ACTION`, and `USER_ACTIVITY_LIST_ACTION` (self-scope: the resource owner is always the authenticated user). The dismiss action is a distinct ACTION from list (rather than implicitly covered) so the endpoint-coverage hard-fail and the 9-class coherence test can verify it independently.

### Compatibility — Trusted Device (FR-011-401..402)

- **FR-011-401**: The Trusted Device subsystem established by spec/010 MUST continue to function for cookie binding, registration, and TOTP-relaxation. The `trusted_expiry_dispatcher` and `trusted_expiry_notifier` workers MUST be rewritten to emit an in-app banner via FR-011-302..308 instead of an outbound expiry-warning email.
- **FR-011-402**: Trusted Device records MUST be revoked on the following sensitive account changes (this extends spec/010's revocation surface): admin password reset (FR-011-203), admin self-password reset (FR-011-210), email change (FR-011-305), admin 2FA disable (US5 / FR-011-306). The previous Trusted Device revocation triggers from spec/010 (explicit user revoke, expiry, suspect login) are preserved unchanged.

## Non-functional Requirements

- **NFR-011-001**: After this spec is implemented, the following grep MUST return zero matches outside historical spec/010 documents, this spec, and the test file that codifies the check:
  
  ```
  grep -riE 'resend|mailpit|aiosmtplib|smtplib|SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASSWORD|send_verification_email|send_password_reset_email|send_2fa_reset_magic_link|email_verified_at|EMAIL_VERIFICATION|RESEND_API_KEY|EMAIL_FROM' apps/ scripts/ compose.dev.yaml .env.example apps/api/README.md README.md .github/workflows/ docs/runbook/ apps/api/alembic/
  ```
  
  Bare `smtp` (lowercase) is intentionally **not** in the pattern because the codebase legitimately uses `allow_smtputf8` in email-input validation (RFC 6531 charset support, not mail egress). The narrowed pattern catches every mail-delivery code path while avoiding that false positive. The CI guard test (`apps/api/tests/contract/test_no_email_subsystem_traces.py`, see research.md R12) excludes itself and any test file explicitly named `*_legacy*.py`, but no other test files.
- **NFR-011-002**: Migrations are split. `0021_zero_email_additive` adds: `users.must_change_password`, `users.temp_password_expires_at`, `project_invitations.ownership_transfer_on_accept`, `user_banner_dismissals` table. `0022_email_subsystem_removal` drops: `email_verification_tokens` table, `password_reset_tokens` table, `users.email_verified_at` column. Phase A applies `0021` and lands code that no longer reads or writes the to-be-dropped columns/tables, additionally adding the new ForcedPasswordChange / banner / invitation / bootstrap behavior on top of `0021`. Phase B (next release) applies `0022`. Both migrations are forward-only; their `downgrade` functions raise. Single-host docker compose deploys (the persona default) MAY collapse both phases via the documented stop → migrate → start sequence, applying `0021` then `0022` in order.
- **NFR-011-003**: Invitation token verification MUST follow the existing pattern in `invitation_service`: hashed lookup followed by `hmac.compare_digest` on the HMAC signature; no implementation may introduce a non-constant-time comparison. Email canonicalisation MUST reuse the existing `services.invitation_service.canonicalize_email` (NFKC normalise + casefold).
- **NFR-011-004**: All new authenticated endpoints (Member invitation issue, bulk issue, project bootstrap intended-owner field, banners list, banner dismiss, activity list, admin password reset, forced password change) MUST be gated by `gate_action` per spec/007 with the appropriate ACTION constants and MUST be covered by the existing endpoint-coverage hard-fail test. ACTION constants MUST pass the 9-class coherence test.
  
  The two token-authenticated public endpoints — `GET /web-api/v1/auth/invitations/{token}` and `POST /web-api/v1/auth/invitations/{token}/accept` — are exempt from `gate_action` and MUST be registered in the spec/007 `TOKEN_AUTH_ONLY` allowlist. The two authenticated-self step-up endpoints — `POST /web-api/v1/auth/step-up/begin` and `POST /web-api/v1/auth/step-up/complete` — are also exempt from `gate_action` because they are self-action (the caller mints a step-up token bound to their own session) and MUST be registered in a separate `AUTHENTICATED_SELF_NO_GATE` allowlist (or extended into the existing spec/007 self-action allowlist if one exists). The endpoint-coverage hard-fail MUST classify all four under their respective exemptions; tasks.md MUST include a sub-task to enumerate and register these in `apps/api/echoroo/core/endpoint_allowlist.py`.
- **NFR-011-005**: All new audit-event `action` strings — `project.member.invite_accepted_signup`, `project.member.invite_accepted`, `project.trusted_user.invite_accepted`, `project.ownership.bootstrap_transfer`, `platform.user.password_reset_by_superuser`, `platform.user.password_reset_self`, `auth.login.new_device`, `platform.api_key.revoke`, `platform.user.email_changed`, `platform.user.two_factor_reset_by_superuser`, `auth.trusted_device.revoke_all` — MUST be registered as constants alongside the existing audit-action strings used by `services/audit_service.py` callers (the codebase does not have a single enum module; constants are declared at the call site or in adjacent service-private modules per the existing convention). They MUST be exercised by `tests/security/test_no_email_subsystem_traces.py` siblings to ensure naming uniformity. The `reason` fields of password-reset entries, the `revoke_reason` of invitation rows, and the `pre_transfer_action_summary` JSON in `project.ownership.bootstrap_transfer` MUST be registered with the Phase 17 A-13 operator free-form PII detector before merge.
- **NFR-011-006**: The token-authenticated public endpoints `GET /web-api/v1/auth/invitations/{token}` and `POST .../accept` MUST be rate-limited per-IP at 10 requests/minute and globally at 200 requests/minute, with constant 200–400ms response timing for invalid tokens to deny timing-based existence oracles. Implementation MUST reuse the Phase 17 A-6 rate-limit pattern in `middleware/rate_limit.py`. The bulk-invitation endpoint MUST additionally be subject to a per-issuer global rate-limit (FR-011-114).
- **NFR-011-007**: The `ForcedPasswordChangeMiddleware` (FR-011-204) MUST be placed in the middleware stack at the topological position previously occupied by `EmailVerificationEnforcementMiddleware` (= AuthRouter middleware の後、TwoFactorEnforcement middleware の前、LIFO 内側). The replacement preserves the topological position so middleware-ordering invariants are not perturbed. Note: `gate_action` is a FastAPI `Depends` injection, not a middleware; "before gate_action" is an imprecise description and is intentionally not used in this spec.
- **NFR-011-008**: The bulk-invitation endpoint MUST commit each issued invitation row inside a single database transaction for the whole batch, with `SAVEPOINT` per row so a single-row issuance failure (e.g. unique-constraint conflict from a duplicate-pending) does not invalidate previously-issued rows in the same batch. The "all-or-nothing" semantic of FR-011-111 applies to **validation** failures (malformed email, in-list duplicate), not to per-row issuance outcomes.
- **NFR-011-009**: spec/006 FR-051 is formally superseded by FR-011-103. The existing OpenAPI diff harness `apps/api/tests/contract/test_openapi_diff.py` currently asserts a subset relation against the YAML fixtures under `specs/006-permissions-redesign/contracts/` (no snapshot file, hard-coded source-of-truth directory). This feature MUST extend the harness to also assert against this spec's `specs/011-zero-email-deployment/contracts/` directory. The extension is part of Implementation Plan step 6 (the same PR that lands FR-011-103). Every later step that touches an HTTP endpoint MUST update the relevant YAML in `specs/011-zero-email-deployment/contracts/` and re-run the harness locally before opening its PR; CI runs the harness on every PR.
- **NFR-011-010**: The invitation token signing key MUST follow the env-driven rotation pattern established by Phase 17 A-12 (`TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW` / `..._KID_OLD` + `..._HMAC_KEY` / `..._HMAC_KEY_OLD`). The new env variables are:
  - `INVITATION_TOKEN_KID_NEW` — active signing kid; **required at every boot**.
  - `INVITATION_TOKEN_HMAC_KEY` — HMAC key for the NEW kid; **required at every boot**.
  - `INVITATION_TOKEN_KID_OLD` — dual-verify kid; **required at initial deploy** of this feature (must be set to the legacy kid identifier so that 3-part legacy tokens in flight can be accepted during the grace window); optional after the grace window expires.
  - `INVITATION_TOKEN_HMAC_KEY_OLD` — HMAC key for the OLD kid; **required whenever `INVITATION_TOKEN_KID_OLD` is set**. The application MUST refuse to start (`get_settings()` model-validator) if `INVITATION_TOKEN_KID_OLD` is set without `INVITATION_TOKEN_HMAC_KEY_OLD`, and conversely.
  - `INVITATION_TOKEN_KID_GRACE_HOURS` — grace window beyond TTL during which OLD-kid tokens remain verifiable (default 24).

  The current invitation token envelope is `{token}.{exp}.{mac}` (3-part, no kid; per `apps/api/echoroo/services/invitation_service.py:_b64u_*`, `sign_invitation_token`); this feature extends the envelope to `{token}.{exp}.{kid}.{mac}` (4-part). Verification accepts either: (a) a 4-part envelope whose `kid` matches `INVITATION_TOKEN_KID_NEW` (preferred) or `INVITATION_TOKEN_KID_OLD` (during rotation), or (b) a 3-part legacy envelope whose MAC verifies under `INVITATION_TOKEN_KID_OLD`'s HMAC key (during grace only). During rotation, tokens signed with `INVITATION_TOKEN_KID_OLD` MUST remain verifiable for at least the active invitation TTL (7 days) plus the grace window. Legacy 3-part tokens issued before this feature lands are accepted as grace-window tokens; after the grace window expires they are rejected with the same generic invalid response as any other failure (FR-011-107).

## Success Criteria

- **SC-1**: A naive deployer can complete the README's "Quick start" without ever being *required* to look up, configure, or provision SMTP, Resend, Mailpit, DKIM, or DNS — i.e. no instruction in §1-§5 of `quickstart.md` asks them to set up any of these. The resulting deployment has no Resend / Mailpit / SMTP-relay container in `docker ps`. (Mentioning these terms in audience-framing copy at the document head and in the FAQ section of `quickstart.md` is intentional and explicitly NOT a violation — the success criterion is operational friction, not word-presence.)
- **SC-2**: A lab admin can onboard 20 collaborators to a Restricted project in a single bulk-invitation operation, copy 20 URLs as a CSV, and distribute them through their own channels.
- **SC-3**: A user who has forgotten their password can have it reset by the system superuser and be back to working state in under 5 minutes, with the temporary password never visible to anyone except the resetting superuser (during the click-to-reveal window) and the target user.
- **SC-4**: A system superuser can bootstrap a project intended for a future owner in a single create-project operation and hand off one URL; the future owner's activity view contains a `pre_transfer_action_summary` upon acceptance.
- **SC-5**: The post-implementation test suite passes with the email subsystem fully deleted, including the endpoint-coverage hard-fail (with the `TOKEN_AUTH_ONLY` exemption applied to the two public token endpoints), the OpenAPI contract diff (extended per NFR-011-009 to subset-assert against both `specs/006-permissions-redesign/contracts/` and `specs/011-zero-email-deployment/contracts/` against the live FastAPI app), the 9-class coherence test, and the existing security-test corpus.
- **SC-6**: The spec/010 Trusted Device user stories continue to pass; the additional sensitive-change revocation triggers (FR-011-402) have dedicated tests.

## Removal Plan (Concrete File Paths)

The Trusted Device portion of spec/010 is retained except for the additions in FR-011-401..402. The Email Verification subsystem and email-sending subsystem are removed at the following call-sites and files. List assembled from a full code grep at HEAD `c22ed23e`.

### Backend — models

| Path | Action |
|---|---|
| `apps/api/echoroo/models/email_verification_token.py` | Delete file |
| `apps/api/echoroo/models/password_reset_token.py` | Delete file |
| `apps/api/echoroo/models/__init__.py` | Remove re-exports of `EmailVerificationToken`, `PasswordResetToken` |
| `apps/api/echoroo/models/user.py` | Remove `email_verified_at` field; add `must_change_password BOOLEAN`, `temp_password_expires_at TIMESTAMPTZ` |
| `apps/api/echoroo/models/project.py` | Add `ownership_transfer_on_accept BOOLEAN NOT NULL DEFAULT false` to `ProjectInvitation` |
| `apps/api/echoroo/repositories/email_verification_token.py` | Delete file |
| `apps/api/echoroo/repositories/password_reset_token.py` | Delete file (if exists) |

### Backend — services

| Path | Action |
|---|---|
| `apps/api/echoroo/services/email_verification_service.py` | Delete file |
| `apps/api/echoroo/services/email.py` | Remove Resend SDK initialiser, `send_verification_email`, `send_password_reset_email`, `send_2fa_reset_magic_link`; rewrite `send_login_notification`, `send_email_change_notification`, `send_2fa_reset_dispatched`, `send_api_key_scope_degrade_email`, `send_api_key_revoke_email` to enqueue in-app banner audit events. Optionally rename module to `services/user_event.py`. |
| `apps/api/echoroo/services/auth.py` (lines 292–298, 306) | Remove legacy `verify_email`, `request_password_reset`, `confirm_password_reset`; remove `EmailVerificationService` import; remove magic-link 2FA reset path. |
| `apps/api/echoroo/services/invitation_service.py` | Remove `InvitationMailPayload`, remove `mail_payload` field from `InvitationCreateOutcome`; expose `signed_token_envelope` instead; remove outbox-email enqueue in `trigger_post_commit_side_effects`; modify `accept_invitation` to branch on logged-in / new-user signup, apply `ownership_transfer_on_accept` when set with nested SAVEPOINT; reuse existing `canonicalize_email` for email comparison; honour A-12 kid rotation |
| `apps/api/echoroo/services/user.py` (lines 13–15, 161, 166, 180) | Remove `email_verified_at = None` resets on email change; remove `send_email_change_notification` call (replaced by in-app banner event); add session invalidation + trusted-device revocation on email change |
| `apps/api/echoroo/services/two_factor_reset_service.py` (line 319, line 1334) | Remove `send_2fa_reset_magic_link` call (line 319); replace `send_2fa_reset_dispatched` (line 1334) with banner enqueue; the self-service magic-link reset path is removed entirely |
| (new) `apps/api/echoroo/services/admin_password_reset.py` | Generates temp password, sets `must_change_password`, invalidates sessions, revokes trusted devices, emits audit |
| `apps/api/echoroo/services/step_up_token_service.py` + `apps/api/echoroo/middleware/step_up.py` | **Extend (do not create parallel).** Add a password + 2FA AND-condition issuance path alongside the existing WebAuthn-assertion-only path. Existing WebAuthn callers remain unchanged. New callers for FR-011-201..210 / FR-011-306 require the AND-condition path. Token format and rotation continue to use `web_session_secret`. |
| (new) `apps/api/echoroo/services/user_banner.py` | Banner listing, dismissal, GC; reads `project_audit_log` and `platform_audit_log` (polymorphic over the two tables, see data-model.md §`user_banner_dismissals`) joined against `user_banner_dismissals`. MUST enforce at write time that the dismissed row's `actor_user_id` or `detail.target_user_id` is the authenticated user (anti-impersonation, security review M-2). |

### Backend — middleware

| Path | Action |
|---|---|
| `apps/api/echoroo/middleware/email_verification_enforcement.py` | Delete file |
| `apps/api/echoroo/main.py` (lines 29, 156) | Remove `EmailVerificationEnforcementMiddleware` import + registration |
| (new) `apps/api/echoroo/middleware/forced_password_change.py` | `ForcedPasswordChangeMiddleware` per FR-011-204 + allowlist |
| `apps/api/echoroo/main.py` | Register `ForcedPasswordChangeMiddleware` at the prior position of `EmailVerificationEnforcementMiddleware` (NFR-011-007). Implementation Plan §3 lands the new middleware AND unregisters the old middleware in a single atomic commit; the two MUST NOT both be live gates simultaneously. The old middleware source file remains on disk until step §10 (final cleanup PR). |

### Backend — API routes

| Path | Action |
|---|---|
| `apps/api/echoroo/api/web_v1/auth.py` (line ranges 84–86, 149, 250, 261, 270, 987, 1015, 1066, 1219, 1240, 1289, 1296, 1308; ranges sorted) | Delete `/verify-email`, `/verify-email/resend`, `/password-reset/request`, `/password-reset/confirm`, `/2fa-reset/magic-link*` endpoints and all `EmailVerificationService` call-sites; rate-limit primitives for those flows also removed. |
| `apps/api/echoroo/api/v1/auth.py` (lines 230, 266, 301–324) | Delete v1 mirrors of the above |
| `apps/api/echoroo/api/web_v1/projects/_members.py` (lines 82, 532) | Remove `EmailVerificationService(db).mark_verified_from_same_email_invitation()` calls |
| `apps/api/echoroo/api/web_v1/projects/_members.py` | Add `POST /{project_id}/invitations` (FR-011-101), `POST /{project_id}/invitations/bulk` (FR-011-110); the invitation listing endpoint already exists and is extended to include `kind=member` rows (FR-011-108) |
| `apps/api/echoroo/api/web_v1/trusted.py` (lines 365–368) | Modify response to include `invitation_url`; remove outbox-email enqueue |
| `apps/api/echoroo/api/web_v1/projects/_lifecycle.py` (or the appropriate creation handler) | Add `intended_owner_email` field handling (FR-011-120..125) |
| `apps/api/echoroo/api/web_v1/admin.py` | Add `POST /admin/users/{user_id}/reset-password` (FR-011-201) with step-up gate |
| (new) `apps/api/echoroo/api/web_v1/me.py` (or extend existing) | Add `GET /me/banners`, `POST /me/banners/dismiss`, `GET /me/activity` (FR-011-302..307, 310) |
| `apps/api/echoroo/api/web_v1/auth.py` | Add `POST /web-api/v1/auth/change-password` and `POST /api/v1/auth/change-password` for the forced-change flow (FR-011-204..205) |
| (new) `apps/api/echoroo/api/web_v1/auth.py` | Add `GET /web-api/v1/auth/invitations/{token}` resolver and `POST .../accept` (TOKEN_AUTH_ONLY, FR-011-105) |
| (new) step-up endpoint (location TBD, likely `web_v1/auth.py`) | `POST /web-api/v1/auth/step-up/begin` and `.../complete` per FR-011-206 |

### Backend — settings, config, env

| Path | Action |
|---|---|
| `apps/api/echoroo/core/settings.py` (lines 128, 132, 135) | Remove `RESEND_API_KEY`, `EMAIL_FROM`, `EMAIL_VERIFICATION_ENFORCEMENT_ENABLED`, `EMAIL_VERIFICATION_TOKEN_TTL_SECONDS`; add `INVITATION_TOKEN_KID_NEW` (required), `INVITATION_TOKEN_KID_OLD` (optional), `INVITATION_TOKEN_KID_GRACE_HOURS` (default 24), `INVITATION_TOKEN_HMAC_KEY` (required), `INVITATION_TOKEN_HMAC_KEY_OLD` (optional). Mirrors Phase 17 A-12's `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW` / `..._KID_OLD` / `..._HMAC_KEY` / `..._HMAC_KEY_OLD` naming pattern. |
| `.env.example` (line 64) | Remove `RESEND_API_KEY=` line and any `EMAIL_FROM` entry; add `INVITATION_TOKEN_KID_*` example lines |
| `compose.dev.yaml` (line 132) | Remove `RESEND_API_KEY=${RESEND_API_KEY:-}` line |
| `apps/api/echoroo/core/auth_paths.py` (lines 27–28, 88–89) | Remove `/verify-email` and `/password-reset` and `/2fa-reset/magic-link` paths from `PUBLIC_AUTH_PATHS`. **Do NOT add** `/auth/change-password` to `PUBLIC_AUTH_PATHS`; it stays an authenticated endpoint and is allowed only by the ForcedPasswordChangeMiddleware allowlist. The token-resolver and accept endpoints (`/auth/invitations/{token}` and `.../accept`) MUST be registered in the new `TOKEN_AUTH_ONLY` allowlist per spec/007. |
| `apps/api/echoroo/core/endpoint_allowlist.py` (lines 164, 235, 245) | Remove 3 verify/resend entries; add new endpoints from FR-011-101..308; classify the two `/invitations/{token}*` routes under `TOKEN_AUTH_ONLY` |
| `apps/api/echoroo/core/actions.py` | Add ACTION constants `PROJECT_MEMBER_INVITATION_ISSUE_ACTION`, `ADMIN_USER_RESET_PASSWORD_ACTION`, `USER_BANNER_LIST_ACTION`, `USER_BANNER_DISMISS_ACTION`, `USER_ACTIVITY_LIST_ACTION`. Register against the 9-class coherence test with scope and required-permission per the table below. |

#### ACTION → 9-class coherence summary

| ACTION constant | Scope | Required permission | Superuser-only |
|---|---|---|---|
| `PROJECT_MEMBER_INVITATION_ISSUE_ACTION` | PROJECT | `MANAGE_MEMBERS` | No |
| `ADMIN_USER_RESET_PASSWORD_ACTION` | USER | (n/a — superuser bypass) | Yes |
| `USER_BANNER_LIST_ACTION` | USER (self) | (n/a — self) | No |
| `USER_BANNER_DISMISS_ACTION` | USER (self) | (n/a — self) | No |
| `USER_ACTIVITY_LIST_ACTION` | USER (self) | (n/a — self) | No |

### Backend — schemas

| Path | Action |
|---|---|
| `apps/api/echoroo/schemas/web_v1/auth.py` (lines 33–34, 39, 53–54, 58) | Remove `email_verification_required` field; add `must_change_password` to login response |
| `apps/api/echoroo/schemas/setup.py` (lines 66, 75) | Remove `email_verified_at` from setup schemas |
| `apps/api/echoroo/schemas/user.py` (line 18) | Remove `email_verified_at` from User schema; add `must_change_password` |
| (new) invitation issuance response schema | Field `invitation_url`, response header `Cache-Control: no-store` |

### Backend — workers, dependencies

| Path | Action |
|---|---|
| `apps/api/echoroo/workers/email_verification_dispatcher.py` | Delete file |
| `apps/api/echoroo/workers/celery_app.py` (line 90) | Remove `email_verification_dispatcher` from Celery includes |
| `apps/api/echoroo/workers/login_notification_dispatcher.py` (line 55) | Replace email send with in-app banner audit event enqueue |
| `apps/api/echoroo/workers/trusted_expiry_dispatcher.py` (line 131) | Replace email send with in-app banner audit event enqueue (FR-011-401) |
| `apps/api/echoroo/workers/trusted_expiry_notifier.py` | Remove producer-side outbox-email enqueue; emit banner audit event directly or via the audit/event sink |
| `apps/api/echoroo/workers/api_key_age_check.py` (lines 64–65, 264, 317) | Replace `send_api_key_revoke_email`, `send_api_key_scope_degrade_email` with in-app banner audit events |
| `pyproject.toml` | Remove `resend` from dependencies |

### Database — migrations

| File | Action |
|---|---|
| `apps/api/alembic/versions/0021_zero_email_additive.py` | New. Add: `users.must_change_password`, `users.temp_password_expires_at`, `project_invitations.ownership_transfer_on_accept`, `user_banner_dismissals` table. |
| `apps/api/alembic/versions/0022_email_subsystem_removal.py` | New. Drop: `email_verification_tokens`, `password_reset_tokens`, `users.email_verified_at`. |
| (existing) `0020_add_target_taxa_to_projects.py` | Untouched; `0021` depends on this as `down_revision`. |

### Frontend

| Path | Action |
|---|---|
| `apps/web/src/routes/(auth)/verify-email/` | Delete directory |
| `apps/web/src/routes/(auth)/forgot-password/` | Delete directory |
| `apps/web/src/routes/(auth)/2fa-reset/` (if present, magic-link path) | Delete directory |
| `apps/web/src/routes/(auth)/login/+page.svelte` | Remove any link to `/forgot-password` or `/2fa-reset/magic-link` |
| `apps/web/src/hooks.server.ts` | Remove `email_verified_at` from the session shape and any derived state |
| (new) `apps/web/src/routes/(auth)/change-password/+page.svelte` | Forced-change screen guarded against `must_change_password` |
| (new) `apps/web/src/routes/(auth)/invite/[token]/+page.svelte` | Invitation acceptance / signup page (bound email read-only; branches on auth state per FR-011-105) |
| `apps/web/src/routes/(app)/profile/+page.svelte` | Remove email-verify badge |
| `apps/web/src/routes/(app)/dashboard/+page.svelte` (line 10) | Remove `isEmailVerified` derived; surface banner stack instead |
| `apps/web/src/lib/api/auth.ts` (lines 65–66, 220, 260) | Remove `verifyEmail`, `resendVerification`, `requestPasswordReset` client methods; add `changePassword`, `acceptInvitation`, `acceptInvitationLoggedIn` |
| `apps/web/src/lib/api/web-auth.ts` | Same edits as `auth.ts` if it carries a parallel client surface |
| `apps/web/src/lib/types/index.ts` (lines 190, 867) | Remove `email_verified_at` from `User` and any derived types; add `must_change_password` |
| `apps/web/src/lib/stores/auth.svelte.ts` | Remove `email_verified_at` references; add `must_change_password` derived for route guard |
| `apps/web/src/routes/(app)/projects/[id]/collaborators/+page.svelte` | New / extended: single-invite form + bulk-invite form + invitation list with revoke |
| `apps/web/src/routes/(app)/admin/users/+page.svelte` | Extend: add "Reset password" button + step-up gate + click-to-reveal dialog |
| `apps/web/messages/en.json`, `apps/web/messages/ja.json` | Remove all email-verification keys; add invitation / password-reset / banner / change-password / step-up keys |

### Documentation

| Path | Action |
|---|---|
| `README.md` (quickstart section) | Remove any reference to SMTP / Resend / Mailpit / DKIM / DNS as a setup step |
| `apps/api/README.md` | Same |
| (new) `docs/operations/inviting-users.md` | Single-invite + bulk-invite walkthroughs |
| (new) `docs/operations/admin-recovery-flows.md` | Superuser password reset, 2FA reset, step-up auth |
| (new) `docs/operations/superuser-bootstrap.md` | SU bootstrap workflow with intended_owner_email |

### Tests

| Path | Action |
|---|---|
| `apps/api/tests/security/authentication/test_email_verification_required.py` | Delete file |
| `apps/api/tests/unit/middleware/test_email_verification_enforcement.py` | Delete file |
| `apps/api/tests/unit/core/test_auth_settings_010.py` | Trim verification-only fields |
| `apps/api/tests/integration/test_setup_flow.py` | Remove email-verification assertions |
| `apps/web/src/routes/(auth)/verify-email/verify-email.spec.ts` | Delete file |
| `apps/web/src/routes/(auth)/login/login-trusted-device.spec.ts` | Trim fixture references to `email_verified_at`; preserve the Trusted Device assertions which are still in scope per spec/010 |
| `apps/web/src/routes/(app)/profile/email-verification.spec.ts` | Delete file |
| `apps/web/src/lib/stores/auth.email-verification.test.ts` | Delete file |
| `apps/web/tests/e2e/auth.spec.ts` (or equivalent e2e) | Remove verify-email / forgot-password walkthroughs; add invitation, bulk-invitation, forced-change, banner walkthroughs |
| (new) `apps/api/tests/integration/test_member_invitation_flow.py` | FR-011-101..109 end-to-end (new user + existing user branches) |
| (new) `apps/api/tests/integration/test_bulk_invitation.py` | FR-011-110..115 |
| (new) `apps/api/tests/integration/test_superuser_bootstrap_invitation.py` | FR-011-120..125 + composite audit assertion |
| (new) `apps/api/tests/integration/test_admin_password_reset.py` | FR-011-201..210 + step-up + session/trusted-device invalidation |
| (new) `apps/api/tests/integration/test_must_change_password_middleware.py` | FR-011-204 allowlist matrix incl. v1 mirrors, OPTIONS, health, etc. |
| (new) `apps/api/tests/integration/test_user_banners.py` | FR-011-301..310 |
| (new) `apps/api/tests/security/test_invitation_token_kid_rotation.py` | NFR-011-010 |
| (new) `apps/api/tests/security/test_step_up_required_for_admin_recovery.py` | FR-011-206 enforcement on every admin recovery endpoint |
| (new) `apps/api/tests/security/test_step_up_complete_password_verify_invariant.py` | Verify that `POST /step-up/complete` rejects the request when the supplied `password` does not match the user's stored hash, AND that on success the issued JWT's `factors.password` claim is `true` only when the server actually verified the password. Asserts the contract-level invariant in `contracts/admin-password-reset.yaml` (security review M-1). |
| (new) `apps/api/tests/security/test_user_banner_dismiss_actor_or_target_match.py` | Enumerate the 4 valid combinations (project row by actor / project row by detail.target_user_id / platform row by actor / platform row by detail.target_user_id) and the corresponding cross-user attempts; each cross-user dismissal MUST return 404 (security review M-2). |
| (existing) `apps/api/tests/contract/test_openapi_diff.py` | Extend the hard-coded contracts directory to also include `specs/011-zero-email-deployment/contracts/`. Update affected YAMLs per PR; the harness asserts the subset relation against the live OpenAPI document (no snapshot file). (NFR-011-009) |

## Implementation Plan

Each step is independently mergeable. Migration ordering is enforced: `0021_zero_email_additive` lands as step 1 so that steps 2–9 can use the new columns and tables; `0022_email_subsystem_removal` lands as step 11 after all readers are deleted.

1. **Migration `0021_zero_email_additive`.** Adds `must_change_password`, `temp_password_expires_at`, `ownership_transfer_on_accept`, `user_banner_dismissals`. (NFR-011-002, FR-011-122, FR-011-301)
2. **Replace email helpers with in-app banner events.** Touch `services/email.py`, all workers and services that called the deleted email helpers. Add `services/user_banner.py`, `GET /me/banners` / dismiss / `GET /me/activity` endpoints. (FR-011-008, FR-011-010, FR-011-301..310, FR-011-401)
3. **Swap middleware: add `ForcedPasswordChangeMiddleware`, remove `EmailVerificationEnforcementMiddleware` from the runtime stack in the same PR.** Wire allowlist per FR-011-204. The two middlewares MUST NOT both be live gates simultaneously: the new one is registered and the old one is unregistered (or fully no-op'd) in one atomic commit, eliminating an interim window where email-verification gating could still block requests on a zero-email-direction deployment. The old middleware source file itself remains in the tree until step 10 (deleted with the rest of the email-verification surface). (FR-011-203..205, NFR-011-007)
4. **Extend step-up auth primitive.** Modify `services/step_up_token_service.py` + `middleware/step_up.py` to add the password + 2FA AND-condition issuance and verification path; add new endpoints if missing for admin-recovery callers. Existing WebAuthn-assertion-only path is preserved. (FR-011-206)
5. **Add admin password reset endpoint and UI.** Wire step-up gate, trusted-device revocation, session invalidation. (FR-011-201..210)
6. **Modify `invitation_service` and the Trusted-overlay endpoint** to surface `invitation_url`. Honor A-12 kid rotation per NFR-011-010. (FR-011-102..104, NFR-011-010)
7. **Add Member-kind invitation HTTP endpoint and frontend collaborator UI single-invite form.** Including existing-user accept branch and TOKEN_AUTH_ONLY classification. (FR-011-101, FR-011-105..109, NFR-011-004)
8. **Add bulk-invitation endpoint and UI.** (FR-011-110..115)
9. **Add `intended_owner_email` on project create + `ownership_transfer_on_accept` flag and `accept_invitation` extension with SAVEPOINT-nested transfer + composite audit + `pre_transfer_action_summary`.** (FR-011-120..125)
10. **Delete the email-verification subsystem (backend code, settings, env entries, password-reset endpoints, self-service 2FA magic link, EmailVerificationEnforcementMiddleware) and the frontend mirror (routes, types, i18n, tests).** Update the affected `specs/011-zero-email-deployment/contracts/*.yaml` files for any final endpoint shape adjustments and re-run `apps/api/tests/contract/test_openapi_diff.py` to verify the subset relation against the live OpenAPI document. (FR-011-001..014, NFR-011-009)
11. **Migration `0022_email_subsystem_removal`.** Drops removed columns/tables. (NFR-011-002, FR-011-002..003)
12. **Documentation pass.** README quickstart update, `docs/operations/*.md`, deprecation notes referencing this spec.

## Test Plan

- **Unit**: invitation `accept_invitation` SQL atomicity (FR-011-106 incl. new-user and existing-user branches), ownership-transfer SAVEPOINT (FR-011-123), temp-password generator policy compliance, banner dismissal idempotency, `ForcedPasswordChangeMiddleware` allowlist matrix (paths, methods, ASGI scope), step-up token generation / verification, kid-rotation dual-verify.
- **Contract / OpenAPI diff**: removed routes absent (verify-email, password-reset, forgot-password, 2fa-reset/magic-link), new **API contract** routes present — these are the backend paths that appear in the OpenAPI document: `POST /web-api/v1/projects/{project_id}/invitations`, `POST /web-api/v1/projects/{project_id}/invitations/bulk`, `GET /web-api/v1/me/banners`, `POST /web-api/v1/me/banners/dismiss`, `GET /web-api/v1/me/activity`, `POST /web-api/v1/auth/change-password`, `POST /api/v1/auth/change-password`, `POST /web-api/v1/admin/users/{user_id}/reset-password`, `GET /web-api/v1/auth/invitations/{token}`, `POST /web-api/v1/auth/invitations/{token}/accept`, plus the new step-up issuance / verification endpoints. The frontend-visible routes `/invite/{token}` and `/change-password` are SvelteKit routes, not API contract routes, and do not appear in the OpenAPI document. YAML contracts in `specs/011-zero-email-deployment/contracts/` updated per-PR and verified by `test_openapi_diff.py` (NFR-011-009).
- **Integration**: single-invite acceptance flow (new + existing user branches); bulk-invite incl. validation rollback, in-list duplicate rejection, duplicate-pending row reporting, per-issuer global rate-limit; SU-bootstrap incl. transfer fired vs. transfer skipped + composite audit + pre_transfer_action_summary; admin reset flow incl. step-up gate, forced-change blocking, session invalidation, trusted-device revocation; admin 2FA disable incl. step-up gate, session invalidation, trusted-device revocation, banner; email change incl. cool-off, session invalidation, trusted-device revocation, banner.
- **Security**: invitation token unguessable; `/invite/{token}` does not leak project existence on invalid tokens (timing ±50ms); admin-reset audit never contains the temp password; both new public token routes are rate-limited and timing-padded per NFR-011-006; spec/006 permission gates enforced on all admin routes; bound-email mismatch on acceptance returns the generic invalid page; banner dismiss requires CSRF; step-up enforced on every admin recovery action; kid rotation grace window honoured.
- **Endpoint coverage**: every new authenticated endpoint registered with `gate_action`; the two TOKEN_AUTH_ONLY endpoints registered in the public-token allowlist; asserted by the existing hard-fail.
- **9-class coherence**: new ACTION constants pass the matrix per the table in Removal Plan §Backend.
- **Frontend Playwright**: "no email UI anywhere on a fresh deployment," "admin issues invitation → second browser registers via URL → membership granted at correct role," "admin issues invitation → existing logged-in user accepts → membership granted no duplicate user," "admin bulk-issues 5 invitations → 5 URLs displayed in table → each redeems independently," "superuser creates project with intended_owner_email → second browser accepts → ownership transferred + pre_transfer_action_summary visible," "admin resets password → target user forced through change screen on next login → trusted device record revoked," "admin disables 2FA → target sessions invalidated → re-enroll succeeds."

## Migration / Rollback

The migrations are forward-only. Down-migrations for `0021` and `0022` exist as stubs that raise, consistent with project policy on destructive schema changes.

Two-phase deployment (NFR-011-002):

- **Phase A** (Implementation Plan steps 1–10): run `0021_zero_email_additive`, then deploy code that no longer reads or writes `users.email_verified_at`, `email_verification_tokens`, `password_reset_tokens` while introducing the new ForcedPasswordChange / banner / invitation / bootstrap features.
- **Phase B** (step 11): run `0022_email_subsystem_removal` to drop the removed columns and tables.

Single-host docker compose deploys (the Deployment Persona's default) MAY collapse both phases via stop → migrate → start, applying `0021` then `0022` in order in one window.

Existing dev / preview databases that have already run migration `0019` will lose the `email_verification_tokens` and `password_reset_tokens` tables and the `email_verified_at` column when `0022` runs. This is intentional and acceptable because the product has no external users (per `project-status.md`).

## Open Questions

> **Closeout note (Step 12, 2026-05-23)** — every tentative answer below was preserved unchanged by the as-shipped implementation; no spec edit was triggered by the implementation phase. Per-question grep-verifications recorded inline.

- **Invitation issuer is later removed from project admins** — should that admin's still-pending invitations be auto-revoked, or remain valid until expiry / explicit revoke? *Tentative answer*: remain valid; the issuer was authorised at issuance time and the audit log captures the chain. Operators concerned about this can revoke explicitly. **Closeout (Step 12)**: tentative answer kept. No auto-revoke logic exists in `services/invitation_service.py`; operators handle this via the explicit `DELETE /projects/{id}/invitations/{invitation_id}` endpoint (FR-011-115).
- **Invitation role removed from the project's role catalog (visibility downgrade edge case)** — auto-revoke or fail-at-redemption? *Tentative answer*: fail at redemption with the generic "no longer valid" page; do not auto-revoke, so the admin can investigate. **Closeout (Step 12)**: tentative answer kept. `accept_invitation` returns the generic invalid page when the role is no longer in the catalog; no auto-revoke side-effect on role removal.
- **Forced password change TTL = 24 hours** — confirmed by FR-011-203 and FR-011-209. Open: should the superuser be able to set a shorter or longer TTL per-reset? *Tentative answer*: no, keep the default fixed for now. **Closeout (Step 12)**: tentative answer kept. `services/admin_password_reset.py` declares `TEMP_PASSWORD_TTL_HOURS: Final[int] = 24` as a module-level constant with no per-call override.
- **Activity / banner retention** — `user_banner_dismissals` rows GC'd after 30 days aligned with banner age limit (FR-011-309). `project_audit_log` and `platform_audit_log` themselves are not GC'd by this spec. **Closeout (Step 12, R1 P0-5 correction)**: the as-shipped behaviour enforces retention at **display time** via `DEFAULT_BANNER_MAX_AGE_DAYS: Final[int] = 30` in `services/user_banner.py::list_banners` — banners whose source audit row is older than 30 days are filtered out of the banner feed. **Dismissal rows in `user_banner_dismissals` are NOT GC'd from the database** by spec/011; they persist indefinitely so that re-dismissing a stale audit row remains idempotent (the dedupe key relies on the dismissal row's existence). Audit log GC is unchanged by spec/011. A future hygiene PR may add a Celery sweep to delete dismissal rows whose `audit_log_id` no longer exists in the parent table; this is tracked as an open, non-blocking follow-up (see Step 12c note in `specs/011-zero-email-deployment/tasks.md` if one is filed). The original tentative phrasing ("rows GC'd after 30 days") was inaccurate and is superseded by this clarification.
- **Bulk invitation maximum size** — FR-011-110 caps at 50; per-issuer global cap per hour is 200 (FR-011-114). Open: raise to 100 if adopters request it. **Closeout (Step 12)**: tentative answer kept. `schemas/member_invitations.py::BulkInvitationRequest` enforces `max_length=50` at the Pydantic layer. No real adopter request to raise it has surfaced during implementation.
- **Step-up token rotation** — step-up tokens (FR-011-206) are issued with a 5-minute TTL and signed via `web_session_secret` per the existing `services/step_up_token_service.py` convention. They are **not** subject to the invitation-token `kid` rotation pattern of NFR-011-010 (which applies only to invitation tokens). If `web_session_secret` is rotated during a 5-minute window, in-flight step-up tokens follow the existing session-secret rotation policy (which already supports a dual-verify grace window for sessions); no spec change is required here. **Closeout (Step 12)**: tentative position kept. Step-up token issuance + verification continues to use `web_session_secret`; no kid was added to the step-up envelope and the env-driven kid rotation pattern remains scoped to invitation tokens.

## Out of Scope

- Outbound email of any kind, including opt-in SMTP. Revisit only if multiple real adopters request it.
- User-facing API-key issuance UI.
- Web-push / mobile-push notifications.
- Federated / SSO authentication.
- Self-service password reset, self-service 2FA reset via magic link, or any other recovery flow that does not require admin intervention.
- Shareable multi-use invitation links.
- Project-admin (non-superuser) access to admin password reset.
- Anything in spec/010 outside the explicit Email Verification surface listed in the Removal Plan and the explicit Trusted Device additions in FR-011-401..402.

## References

- `specs/006-permissions-redesign/` — permission model, `ProjectInvitation` baseline, `gate_action` mechanics. FR-051 formally superseded by FR-011-103.
- `specs/007-permission-test-coverage/` — endpoint-coverage hard-fail, 9-class coherence, `TOKEN_AUTH_ONLY` allowlist classification.
- `specs/010-email-verification-trusted-devices/` — predecessor; Trusted Device portion remains active (with FR-011-401/402 extensions), Email Verification portion removed by this spec.
- Phase 17 A-6 — rate-limit pattern reused by NFR-011-006.
- Phase 17 A-11 — admin 2FA reset (referenced by US5, with step-up gate added by FR-011-206).
- Phase 17 A-12 — env-driven kid rotation (referenced by NFR-011-010).
- Phase 17 A-13 — operator free-form PII detector (referenced by NFR-011-005).
- Phase 12 — ownership transfer endpoint (referenced by FR-011-124, US6).
- `docs/reports/email-verification-status-2026-05-21.html` — investigation report that triggered this spec.
- Rev.1 reviews (architect / security / Codex, 2026-05-21) — folded into this revision (migration split, kid rotation, allowlist expansion, existing-user accept path, removed self-service 2FA, step-up upgrade, audit visibility, OpenAPI snapshot, signed_token_envelope rename, trusted-device revocation triggers).
