# Phase 0 Research — Zero-email Deployment (Rev.2)

**Date**: 2026-05-21
**Spec**: `specs/011-zero-email-deployment/spec.md` (Rev.3.2)

This document resolves the NEEDS-CLARIFICATION items surfaced by the three-way review of Rev.1 and Rev.2 of the spec, plus the small "deferred to plan" items in Rev.3, plus the codebase-fact errors caught by the plan-phase three-way review of Rev.3 (architect / security / Codex). Rev.2 of this document replaces Rev.0 — all decisions are anchored to **grep-verified existing implementations**, not to hypothetical structures.

---

## R1. Step-up token: extend existing JWT, no Redis

**Context**: FR-011-206 (spec.md Rev.3.1) requires a step-up authentication challenge (password + 2FA AND-condition) with a 5-minute TTL, re-usable for sensitive actions within the window. The Rev.0 draft of this document proposed a Redis-backed opaque token with `(user_id, session_id, scope_set)` binding — this was rejected by the architect plan-phase review (C-1) because it conflicted with the existing implementation.

**Existing implementation (grep-verified)**: `apps/api/echoroo/services/step_up_token_service.py` (Phase 16 Batch 6g-3) mints an HS256 JWT signed with `settings.web_session_secret`. Payload: `{sub, type='step_up', scope, ss, aid, jti, iat, exp}`. The token is transmitted via the `X-Step-Up-Token` header and decoded by `middleware/step_up.py:require_step_up_token`. The `ss` claim binds the token to the user's `security_stamp` at issuance time; rotating `security_stamp` (which already happens on password reset and 2FA reset per existing behaviour) immediately invalidates outstanding step-up tokens. **No Redis state**.

**Decision**: extend the existing JWT payload in-place:

1. **New claim** `factors: { password: bool, second_factor: 'totp' | 'webauthn' | null }`.
2. **New scope value** `admin_recovery` alongside the existing `admin_destructive`. The verifier in `middleware/step_up.py` distinguishes the two so the new admin-recovery callers (FR-011-201..210, FR-011-306) can refuse webauthn-only step-up tokens that were issued for `admin_destructive`.
3. **Verifier change**: when scope is `admin_recovery`, require `factors.password == true AND factors.second_factor != null`.
4. **Issuer change**: new helper `issue_admin_recovery_step_up_token(user, password_verified, second_factor)` alongside the existing `issue_step_up_token`. Both share the encoding logic; only the payload differs.

The `security_stamp`-based revocation continues to provide immediate token invalidation on the target user's password reset / 2FA reset / email change. No new revocation primitive is needed.

**Rationale**: extending the existing service touches one file (`services/step_up_token_service.py` + matching test) plus the verifier (`middleware/step_up.py`). It reuses the WebAuthn ceremony's session binding (the existing `aid` claim) and the well-understood JWT plumbing. Redis-backed opaque would have added a new TTL-bound state surface and a new revocation race; both are avoided.

**Alternatives considered (and rejected)**:

- **Redis-backed opaque token** (Rev.0 draft): rejected — conflicts with existing implementation and adds new state surface without forensic benefit.
- **Dedicated new module** (`services/step_up_auth.py`): rejected — duplicates the existing service.

---

## R2. NFR-011-001 grep target expansion

**Context**: The Rev.2 security review noted the spec's grep target list missed `.github/workflows/` and `docs/runbook/`. The plan-phase review also flagged that `apps/api/alembic/` was outside the grep target.

**Decision**:

1. NFR-011-001's grep target list (spec.md Rev.3.1) MUST include `.github/workflows/`, `docs/runbook/`, and `apps/api/alembic/`.
2. The CI guard test (`apps/api/tests/contract/test_no_email_subsystem_traces.py`, see R12) excludes itself (`tests/contract/test_no_email_subsystem_traces.py`) and any file named `*_legacy*.py`; no other test files are excluded. The previously over-broad `**/test_*.py` exclude is removed.
3. Implementation Plan step 10 includes a sub-task that audits `.github/workflows/*.yml` for `RESEND_API_KEY`, `EMAIL_FROM`, `SMTP_*` references and removes them; generates `docs/runbook/zero-email-deployment-secret-rotation.md` listing every Actions secret to be rotated/deleted by the operator after deploy.

**Rationale**: a CI guard test catches drift on every PR; the regex lives in one place; the runbook tells the operator what to delete in their own deployment.

---

## R3. Invitation token kid rotation — env naming aligned with Phase 17 A-12

**Context**: NFR-011-010 mandates `kid` rotation for invitation token signing. The Rev.0 draft used `INVITATION_TOKEN_KID_ACTIVE` / `INVITATION_TOKEN_KID_VERIFY_ALSO`; the architect plan-phase review (C-2) noted that Phase 17 A-12 uses `_NEW` / `_OLD` and that consistency matters. Codex review (H3) additionally noted the existing envelope is 3-part (`{token}.{exp}.{mac}`) with no `kid` slot, so kid is a structural addition, not a re-keying.

**Existing implementation (grep-verified)**: `apps/api/echoroo/services/invitation_service.py:sign_invitation_token` (line 449) produces `{raw_token_b64u}.{exp_unix_ts}.{mac_b64u}` where the MAC is URL-safe base64 encoded via the module's `_b64u_encode` helper (line 300). There is no `kid` field. The env-naming pattern of Phase 17 A-12 (`apps/api/echoroo/core/settings.py:332-410`) is `..._KID_NEW` / `..._KID_OLD` and `..._HMAC_KEY` / `..._HMAC_KEY_OLD`.

**Decision**:

1. **Env vars** (mirrors A-12, spec.md Rev.3.1 NFR-011-010, data-model.md §Settings):
   - `INVITATION_TOKEN_KID_NEW` (required)
   - `INVITATION_TOKEN_KID_OLD` (optional, set during rotation or initial migration from legacy 3-part envelopes)
   - `INVITATION_TOKEN_KID_GRACE_HOURS` (default `24`)
   - `INVITATION_TOKEN_HMAC_KEY` (required)
   - `INVITATION_TOKEN_HMAC_KEY_OLD` (optional)
2. **Envelope format change**: 3-part `{token}.{exp}.{mac}` → 4-part `{token}.{exp}.{kid}.{mac}`. The MAC is computed over `token + "." + exp + "." + kid`.
3. **Verification order** (`services/invitation_service.verify_invitation_token`):
   1. 4-part split. `kid == NEW` → verify under NEW. `kid == OLD` AND within grace → verify under OLD. Otherwise reject.
   2. 3-part split (legacy). Within grace AND `OLD` env set → verify under OLD. Otherwise reject.
4. **Initial deploy**: operator sets both `INVITATION_TOKEN_KID_NEW` and `INVITATION_TOKEN_KID_OLD` to a single value (the legacy secret), and `INVITATION_TOKEN_HMAC_KEY_OLD` to the legacy HMAC key. Existing 3-part tokens issued before this feature deployed verify under OLD during the grace window. **If `INVITATION_TOKEN_HMAC_KEY_OLD` is unset on initial deploy, the application MUST refuse to start** (`get_settings()` validation), because legacy 3-part tokens would otherwise be silently invalidated mid-flight (a UX regression for pending invitations). The runbook (`docs/runbook/invitation_token_kid_rotation.md`) covers this initial-deploy step as the first checklist item.
5. **Planned rotation**: assign a new kid + secret to `NEW`, move the previous values to `OLD`. Wait TTL (7d) + `GRACE_HOURS`. Unset `OLD`.
6. **Emergency rotation**: assign a new kid + secret to `NEW`. **Do not set `OLD`**. All outstanding tokens signed with the previous kid are immediately invalid. Operator must re-issue any active invitations through normal endpoints.

**Runbook**: `docs/runbook/invitation_token_kid_rotation.md` documents both planned and emergency procedures with explicit env var sequences and the forensic query for impacted invitations.

**Rationale**: aligns with the existing Phase 17 A-12 operator vocabulary so the runbook is recognisable. Choosing a 4-part envelope (rather than embedding kid inside the b64u token) preserves the simple `split('.')` parser semantics already in `invitation_service`.

---

## R4. OpenAPI diff harness extension (multi-spec)

**Context**: NFR-011-009 mandates that the OpenAPI contract drift be detected. The Rev.0 draft assumed a snapshot-file regeneration model. The Codex review (Critical, by extension architect's C-4) revealed that `apps/api/tests/contract/test_openapi_diff.py` does not use a snapshot file at all — it asserts a subset relation between the YAML files under `specs/006-permissions-redesign/contracts/` and the live FastAPI app's `openapi.json`. The harness is hard-coded to that single source-of-truth directory.

**Decision**:

1. Extend `test_openapi_diff.py` (in Implementation Plan step 6, the same PR as FR-011-103) so it asserts the subset relation against **both** `specs/006-permissions-redesign/contracts/` and `specs/011-zero-email-deployment/contracts/`. Implementation: change the hard-coded constant to a list of directories.
2. Every PR after step 6 that touches an HTTP endpoint MUST update the relevant YAML in `specs/011-zero-email-deployment/contracts/` to match the live FastAPI app's exposed shape. The harness re-runs in CI on every PR; mismatches fail the build.
3. There is no separate "snapshot regeneration commit"; the commit that changes the endpoint also changes the YAML.

**Rationale**: harness extension is one-line (a list of directories instead of one); the workflow is unchanged for contributors. The earlier "regenerate snapshot" framing is fiction and is removed.

**Alternatives considered**:

- **Add to spec/006 contracts directly**: rejected. spec/006 is fixed-scope; spec/011 contracts belong with spec/011.
- **Move to a third "live" directory**: rejected. Same source-of-truth-vs-live confusion as a snapshot model.

---

## R5. Invitation kind guard for `ownership_transfer_on_accept`

**Context**: Defence-in-depth for the SU-bootstrap invariant: `ownership_transfer_on_accept = true` only makes sense for `kind = 'member'`. The architect Rev.2 review M-2 and Rev.3 plan-phase confirmed this.

**Decision**:

1. **Schema CHECK** (data-model.md §`project_invitations`): `(ownership_transfer_on_accept = false OR kind = 'member')`. Migration `0021_zero_email_additive`.
2. **Application guard at `create_invitation`**: BEFORE INSERT, if `ownership_transfer_on_accept=True AND kind != ProjectInvitationKind.MEMBER`, raise `InvitationStateError("ownership_transfer_on_accept_invalid_for_kind")`. The 400 response avoids depending on the IntegrityError 500 that the CHECK would raise.
3. **Application guard at `accept_invitation`**: same error if the row somehow encodes the impossible combination (e.g. through a hand-written SQL migration or out-of-band INSERT).
4. **Test**: `apps/api/tests/security/test_invitation_kind_guard.py` exercises all three cases — direct INSERT (CHECK rejects), create_invitation (Python rejects), accept_invitation (Python rejects).

**Rationale**: matches Phase 17 A-13's CHECK + Python guard pattern. Three independent points of enforcement; future migrations cannot accidentally drop all three at once.

---

## R6. Destructive-action preservation in `pre_transfer_action_summary`

**Context**: FR-011-123 emits a composite audit row `project.ownership.bootstrap_transfer` whose `pre_transfer_action_summary` JSON lists the prior owner's project-scoped audit history. The Rev.2 security review (Low 3.3) noted that wholesale A-13 redaction is too aggressive — the new owner needs to know which entities the prior owner destroyed for incident response.

**Decision**: define `DESTRUCTIVE_ACTIONS` in `services/audit_service.py` (the existing audit module; the Rev.0 draft incorrectly proposed `core/audit.py`, which is the sanitiser, not the action constants):

```python
DESTRUCTIVE_ACTIONS: Final[frozenset[str]] = frozenset({
    "project.delete",
    "dataset.delete",
    "recording.delete",
    "project.acl.update",
    "project.permission.elevate",
    "project.visibility.update",
})
```

For audit-action strings in this set, `pre_transfer_action_summary` preserves the `target_id` (e.g. dataset / recording UUID extracted from the source audit row's `detail.target_id` or equivalent) in plaintext. All other entries carry only `{action, occurred_at}`. Canonical JSON shape (also reflected in data-model.md §Audit Events):

```json
{
  "summary": [
    {"action": "project.config_updated", "occurred_at": "2026-05-21T11:50:00Z"},
    {"action": "dataset.delete", "occurred_at": "2026-05-21T11:52:00Z", "target_id": "dataset-uuid-here"}
  ]
}
```

The A-13 detector test enumerates this allowlist and asserts no other action leaks `target_id`. The `occurred_at` key (NOT `timestamp_iso`) matches the existing `project_audit_log.occurred_at` / `platform_audit_log.occurred_at` column naming.

The exact spelling of each allowlist entry MUST be reconciled against the codebase at implementation time — if `project.delete` does not exist today, the PR introducing the matching destructive call MUST add the audit-action string and include it in the allowlist in the same commit.

**Rationale**: forensic value for destructive operations + tight allowlist for everything else. The placement in `services/audit_service.py` matches the existing convention (audit-related constants live next to the writer).

**Alternatives considered**:

- **Preserve all target ids**: rejected. PII risk too broad.
- **Preserve none**: rejected. Alice would be unable to identify what to recover.

---

## R7. ProjectInvitation reuse vs new table (recap)

**Decision**: Reuse the existing `project_invitations` table. Add `ownership_transfer_on_accept` via `0021_zero_email_additive`. No new invitation table.

**Rationale**: avoids ~1300 lines of duplicated invitation service code, preserves the existing PII hash (A-2), kid-rotation work (A-12, see R3), PII detector (A-13), and rate-limit (FR-056) plumbing.

---

## R8. ForcedPasswordChangeMiddleware vs EmailVerificationEnforcementMiddleware swap (recap)

**Decision**: Single-PR atomic swap in Implementation Plan step 3. The new middleware is registered AND the old middleware is unregistered in the same commit. The old middleware source file remains on disk until step 10 (cleanup PR). This eliminates the interim "both live gates" risk identified by the Rev.2 Codex review and reinforced by the plan-phase architect review (H-2).

The spec.md Removal Plan middleware row (`apps/api/echoroo/main.py`) was updated in Rev.3.1 to match this rule.

---

## R9. `services/email.py` — reduce, do not rename

**Decision**: Retain the file. Delete the Resend SDK initialiser and three helpers (`send_verification_email`, `send_password_reset_email`, `send_2fa_reset_magic_link`). Rewrite the remaining five helpers (`send_login_notification`, `send_email_change_notification`, `send_2fa_reset_dispatched`, `send_api_key_scope_degrade_email`, `send_api_key_revoke_email`) to enqueue banner audit rows instead of attempting any mail transport. If implementation discovers an additional banner-eligible helper not in this list, it is added to the rewrite set in the same PR without an additional research-block change (treat as obvious follow-on, document in PR description). Do not rename the module.

**Rationale**: renaming forces edits across all importers without functional benefit. Comments and docstrings will be updated to reflect that the helpers are banner-event emitters, not mail senders.

---

## R10. Trusted Device revocation — reuse existing service

**Context**: FR-011-402 requires trusted-device revocation on sensitive account changes. The Rev.0 research said "centralize in a new helper"; the architect plan-phase review (H-1) noted that `TrustedDeviceService.revoke_all_for_user` already exists.

**Existing implementation (grep-verified)**: `apps/api/echoroo/services/trusted_device_service.py:100` defines `async def revoke_all_for_user(self, *, user) -> int:` and six call-sites currently use it (`services/user.py`, `services/two_factor_service.py`, `api/web_v1/auth.py`, `services/user_deletion_service.py`, `api/web_v1/account/trusted_devices.py`).

**Decision**: Reuse the existing `TrustedDeviceService.revoke_all_for_user`. The new call-sites for FR-011-402 are:

- `services/admin_password_reset.reset_password` (FR-011-203)
- `services/admin_password_reset.self_reset` (FR-011-210)
- `services/user.change_email` (FR-011-305) — call-site already exists for some paths; verify and wire the missing branch
- `services/two_factor_service` admin-disable path (FR-011-306) — likely already calls it; verify

The new helper text in plan.md / Removal Plan that said "add `revoke_all_for_user` helper" was a misreading and is corrected to "wire existing helper to new callers" in the Rev.2 plan.

**Idempotency**: the existing implementation marks all of the user's trusted device rows as revoked; calling it twice in the same TX is a no-op on the second call (the second UPDATE matches zero pending rows). A unit test in `tests/security/test_trusted_device_revoke_idempotent.py` MUST cover this.

---

## R11. Existing-user invitation accept branch (recap)

**Decision**: `accept_invitation` branches on the authentication state of the caller:

- **Unauthenticated**: existing signup path runs (user creation, 2FA enrollment, password policy).
- **Authenticated**: skip signup; validate `canonicalize_email(authenticated_user.email) == canonicalize_email(invitation.email)` using the existing `services.invitation_service.canonicalize_email` (NFKC normalise + casefold); if match, apply role/overlay; if already a member, return 409.

Implementation: a single `accept_invitation` callable with a `caller_state` argument carrying either `NewUserPayload` or `AuthenticatedUser`. The HTTP handler at `POST /web-api/v1/auth/invitations/{token}/accept` decides which case to construct based on session presence.

**Rationale**: keeps the transaction boundary as one DB session, satisfies FR-011-106 SQL atomicity, avoids a separate "auth'd accept" endpoint.

---

## R12. CI guard test for NFR-011-001

**Decision**: a new pytest `apps/api/tests/contract/test_no_email_subsystem_traces.py` codifies NFR-011-001:

```python
import re, subprocess

_PATTERN = re.compile(
    r"resend|mailpit|aiosmtplib|smtplib|"
    r"SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASSWORD|"
    r"send_verification_email|send_password_reset_email|"
    r"send_2fa_reset_magic_link|email_verified_at|"
    r"EMAIL_VERIFICATION|RESEND_API_KEY|EMAIL_FROM",
    re.IGNORECASE,
)

_SEARCH_PATHS = [
    "apps/", "scripts/",
    "compose.dev.yaml", ".env.example",
    "apps/api/README.md", "README.md",
    ".github/workflows/", "docs/runbook/",
    "apps/api/alembic/",
]

_EXCLUDE_PATHS = [
    "specs/",
    "docs/reports/",
    "apps/api/tests/contract/test_no_email_subsystem_traces.py",  # self
]
_EXCLUDE_GLOB = ["*_legacy*.py"]  # explicitly named legacy fixtures only
```

CI runs this test on every PR. Lives at `apps/api/tests/contract/test_no_email_subsystem_traces.py`.

**Rationale**: codifies the NFR as a check; the regex is updatable in one place; prevents regression by future PRs. The narrow exclude list resolves the Rev.2 security review M4 finding (`**/test_*.py` was too broad).

---

## R13. Telemetry redaction surface for temp password and step-up token

**Context**: The plan-phase security review (H2) flagged that `temporary_password` and `step_up_token` are MUST-scrub in contract, but no enumeration of where to scrub exists.

**Decision**: redaction is applied in three places, with paths pinned (grep-verified: `apps/api/echoroo/observability/` directory does NOT exist today; Sentry integration is not present in the codebase):

1. **Sentry `before_send` hook** — create new module `apps/api/echoroo/observability/sentry.py` (and the `observability/__init__.py` package marker). If the project later adopts a different telemetry vendor, the hook lives in the same file with a vendor-neutral name (`apps/api/echoroo/observability/redaction.py`). For this spec's scope, the file is created **only when** the operator opts into Sentry by setting `SENTRY_DSN` — otherwise the file's `init_sentry()` is a no-op. The hook scrubs request bodies and response bodies whose key matches `temporary_password`, `step_up_token`, `invitation_url`, or `signed_token_envelope`; also scrubs request headers matching `X-Step-Up-Token`.
2. **FastAPI middleware** — create new file `apps/api/echoroo/middleware/redaction.py`. Do **not** extend `middleware/audit_logging.py` (separate concerns: audit_logging records *intentional* audit rows, redaction strips secrets from observability output). The new middleware reads the response payload, drops the listed fields before structured-log emission.
3. **Nginx/reverse-proxy access logs**: redact `X-Step-Up-Token` request header via `log_format` directive (deployment-time config). Example snippet in `docs/operations/admin-recovery-flows.md` (operator-side; not application-test enforced).

A unit test `tests/security/test_telemetry_scrubs_sensitive_fields.py` verifies (1) and (2). The Nginx config example is operator-side and not enforced by application tests.

**Rationale**: addresses the security gap before tasks generation. The 3-layer redaction matches the OWASP A02 / A09 expectation that secrets never appear in third-party telemetry.

---

## R14. Quickstart §11 SC-1 reconciliation

**Context**: The plan-phase Codex review (H7) noted that `quickstart.md` §11 lists `Resend / Mailpit / DKIM / SMTP / DMARC / DNS` ("What you do NOT need"), violating the literal reading of SC-1 ("naive deployer never sees those words").

**Decision**: SC-1 in spec.md Rev.3.1 is interpreted as "naive deployer never NEEDS to set or look up those concepts to bring up Echoroo", not "the words must never appear anywhere in their reading material". To make this unambiguous:

1. Move §11 of quickstart.md to a separate section appended **after** the deployer's main "you're done" line, marked "FAQ — common misconceptions". Naive deployers stop reading after the "you're done" line.
2. Keep the §11 content (it has real value for deployers wondering whether they need to set anything up). The section's content is unchanged; only its position and heading move.

**Rationale**: SC-1's intent is friction-free onboarding, not word-policing. The structural move is enough.

---

## Open Items Carried Forward to tasks.md

- Per-endpoint OpenAPI YAML edit + harness re-run in the same PR (R4).
- Runbook artefacts (`docs/runbook/invitation_token_kid_rotation.md`, `docs/runbook/zero-email-deployment-secret-rotation.md`).
- The CI guard test `test_no_email_subsystem_traces.py` (R12).
- The redaction test `test_telemetry_scrubs_sensitive_fields.py` (R13).
- Per-implementation-step audit-action string registration and `DESTRUCTIVE_ACTIONS` allowlist updates (R6).
