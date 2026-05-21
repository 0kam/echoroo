# Phase 1 Data Model — Zero-email Deployment (Rev.2)

**Date**: 2026-05-21
**Spec**: `specs/011-zero-email-deployment/spec.md` (Rev.3.2)
**Research**: `specs/011-zero-email-deployment/research.md` (Rev.2)

This document enumerates every database-layer change for the feature. Two Alembic migrations are split per NFR-011-002:

- **`0021_zero_email_additive`** — additive only. Lands in Phase A together with the code that uses the new columns/tables.
- **`0022_email_subsystem_removal`** — destructive only. Lands in Phase B after all readers of the removed columns/tables have been deleted.

## Notes on existing audit infrastructure (verified by grep)

Echoroo's audit substrate is the pair `project_audit_log` and `platform_audit_log` (see `apps/api/echoroo/services/audit_service.py:122-196`). The `AuditLogService.write_project_event` / `write_platform_event` write rows with an `action` string and an optional `detail` JSON; sanitisation is performed by `echoroo/core/audit.py:AuditLogSanitizer`. There is no `audit_events` table; the earlier Rev.0 draft referred to a non-existent name.

Audit-action strings follow a `prefix.subject.verb` 3-segment or `prefix.subject_verb_with_underscores` 2-segment convention. Examples in the existing codebase:

- `auth.login_failed`, `auth.password_reset_completed`, `auth.trusted_device_bypass_accepted`
- `platform.audit_log.chain_verify`, `platform.project.archive`, `platform.project.restore`

This spec follows the same convention for new strings (NFR-011-005, spec.md Rev.3.2).

---

## Entities — Net Additions

### `users` (existing table, modified)

| Column | Type | Constraints | Migration | Purpose |
|---|---|---|---|---|
| `must_change_password` | `BOOLEAN` | `NOT NULL DEFAULT false` | 0021 add | Set true by admin password reset; ForcedPasswordChangeMiddleware (FR-011-204) blocks all non-allowlist routes while true. |
| `temp_password_expires_at` | `TIMESTAMPTZ` | `NULL` | 0021 add | Wall-clock expiry of the temporary password (default `now() + 24h` on reset; FR-011-203). NULL when not in a forced-change cycle. |
| `email_change_cooldown_until` | `TIMESTAMPTZ` | `NULL` | 0021 add | 24-hour cool-off after `change_email` succeeds (FR-011-305). While `now() < email_change_cooldown_until`, additional `change_email` and `change_password` requests for this user are rejected. NULL when no cool-off in effect. |
| `email_verified_at` | `TIMESTAMPTZ` | (existing) | **0022 drop** | Removed entirely (FR-011-002). No replacement. |

**Indexes**: none added; the two new columns are not query keys.

**Application-level invariants**:

- `temp_password_expires_at IS NOT NULL IMPLIES must_change_password = true`. Set together by `services/admin_password_reset.reset_password`; cleared together on successful change.
- A successful password change clears both fields and invalidates all of the user's other active sessions and revokes all trusted-device records (FR-011-205, FR-011-402).

**Migration notes (0021)**:

```python
op.add_column("users", sa.Column(
    "must_change_password", sa.Boolean(),
    nullable=False, server_default=sa.text("false"),
))
op.add_column("users", sa.Column(
    "temp_password_expires_at", sa.DateTime(timezone=True), nullable=True,
))
```

**Migration notes (0022)**:

```python
op.drop_column("users", "email_verified_at")
```

### `project_invitations` (existing table, modified)

| Column | Type | Constraints | Migration | Purpose |
|---|---|---|---|---|
| `ownership_transfer_on_accept` | `BOOLEAN` | `NOT NULL DEFAULT false`, **CHECK** `(ownership_transfer_on_accept = false OR kind = 'member')` | 0021 add | Set true only when a system superuser bootstraps a project for a future owner (FR-011-121). On acceptance, triggers FR-011-123 ownership transfer in the same TX. |

**Application-level guard**: `services/invitation_service.create_invitation` MUST raise `InvitationStateError("ownership_transfer_on_accept_invalid_for_kind")` if a caller passes `ownership_transfer_on_accept=True` together with `kind != ProjectInvitationKind.MEMBER`, before INSERT, so the CHECK constraint is never triggered at runtime (it remains as defence-in-depth). `accept_invitation` raises the same error if it encounters such a row (e.g. via a hand-written migration or out-of-band INSERT).

**Migration notes (0021)**:

```python
op.add_column("project_invitations", sa.Column(
    "ownership_transfer_on_accept", sa.Boolean(),
    nullable=False, server_default=sa.text("false"),
))
op.create_check_constraint(
    "ck_project_invitations_ownership_transfer_kind_member",
    "project_invitations",
    "ownership_transfer_on_accept = false OR kind = 'member'",
)
```

### `user_banner_dismissals` (new table)

Tracks per-user dismissal of in-app banners (FR-011-301..310). The banner content itself is a row in either `project_audit_log` or `platform_audit_log`; this table is the dismissal join, polymorphic over the two audit tables.

| Column | Type | Constraints |
|---|---|---|
| `user_id` | `UUID` | `NOT NULL`, `REFERENCES users(id) ON DELETE CASCADE` |
| `audit_table` | `TEXT` | `NOT NULL`, `CHECK (audit_table IN ('project_audit_log', 'platform_audit_log'))` |
| `audit_log_id` | `UUID` | `NOT NULL` |
| `dismissed_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT now()` |
| **PK** | `(user_id, audit_table, audit_log_id)` | composite primary key |

**Indexes**: the composite PK is sufficient; banner queries lookup by `(user_id, audit_table, audit_log_id)`.

**Polymorphic FK**: PostgreSQL does not natively support polymorphic foreign keys, and per-table foreign keys cannot be conditioned on a discriminator column. Instead:

- The CHECK constraint above bounds `audit_table` to the two known values.
- `services/user_banner.py` MUST validate at write time that (a) `(audit_table, audit_log_id)` resolves to an existing row (a one-row SELECT before INSERT), AND (b) the resolved row's `actor_user_id == authenticated_user.id` OR the row's `detail.target_user_id == authenticated_user.id` (anti-impersonation, security review M-2). Mismatch returns 404 — same response status, body, and timing as "row not found" (anti-enumeration, per `me-banners-activity.yaml` dismiss 404 description). The test `tests/security/test_user_banner_dismiss_actor_or_target_match.py` enumerates every combination (project row by actor, project row by detail.target, platform row by actor, platform row by detail.target, all four with cross-user attempts).
- Audit-log GC by this spec is not performed (Open Questions in spec.md). When GC is added by a future spec, the dismissal table's same-window cleanup is required to prevent FR-011-309 re-surface.

**Migration notes (0021)**:

```python
op.create_table(
    "user_banner_dismissals",
    sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("audit_table", sa.Text(), nullable=False),
    sa.Column("audit_log_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column("dismissed_at", sa.DateTime(timezone=True),
              server_default=sa.text("now()"), nullable=False),
    sa.PrimaryKeyConstraint("user_id", "audit_table", "audit_log_id"),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    sa.CheckConstraint(
        "audit_table IN ('project_audit_log', 'platform_audit_log')",
        name="ck_user_banner_dismissals_audit_table",
    ),
)
```

**GC** (operational, FR-011-309): rows whose `dismissed_at < now() - interval '30 days'` MAY be deleted by a Celery beat task scheduled daily. Implementation lives in `docs/operations/admin-recovery-flows.md`; the spec leaves this as best-effort.

---

## Entities — Net Removals (0022 only)

### `email_verification_tokens` (entire table)

Dropped by `0022`. All readers removed in Phase A (FR-011-002..004). No replacement.

```python
op.drop_table("email_verification_tokens")
```

### `password_reset_tokens` (entire table)

Dropped by `0022`. All readers removed in Phase A (FR-011-002..003, FR-011-005). No replacement (admin-mediated reset uses no token table; the temp password lives on `users.password_hash` directly).

```python
op.drop_table("password_reset_tokens")
```

---

## Domain Models

### Step-up token (existing HS256 JWT, extended)

The existing `services/step_up_token_service.py` (Phase 16 Batch 6g-3) mints an HS256 JWT signed with `settings.web_session_secret`. Payload today:

```json
{
  "sub": "<user_id uuid>",
  "type": "step_up",
  "scope": "admin_destructive",
  "ss":   "<security_stamp at issuance>",
  "aid":  "<assertion_id uuid issued by webauthn_service>",
  "jti":  "<random uuid>",
  "iat":  <unix_ts>,
  "exp":  <unix_ts + 300>
}
```

**This spec extends the payload, in-place** (FR-011-206, Rev.3.2):

```diff
   {
     "sub": "<user_id uuid>",
     "type": "step_up",
-    "scope": "admin_destructive",
+    "scope": "admin_destructive" | "admin_recovery",
     "ss":   "<security_stamp at issuance>",
     "aid":  "<assertion_id uuid issued by webauthn_service>",
     "jti":  "<random uuid>",
     "iat":  <unix_ts>,
-    "exp":  <unix_ts + 300>
+    "exp":  <unix_ts + 300>,
+    "factors": {
+      "password": <bool>,
+      "second_factor": "totp" | "webauthn" | null
+    }
   }
```

- The new `admin_recovery` scope is required for FR-011-201..210 / FR-011-306; the verifier in `middleware/step_up.py` MUST reject tokens whose scope is `admin_destructive` for these endpoints (the converse is also true: existing destructive admin endpoints keep their current scope).
- The `factors` claim MUST be `{password: true, second_factor: ('totp' | 'webauthn')}` for `admin_recovery`-scoped tokens. Tokens without these factors are rejected with `step_up_token_invalid` (matching the existing error code pattern).
- `security_stamp` rotation invalidates outstanding tokens automatically (existing behaviour). Password reset / 2FA reset / email change all rotate `security_stamp`, so a compromised step-up token expires the moment the targeted user's security_stamp rotates.
- No Redis state, no new module. Token transport is the existing `X-Step-Up-Token` header.

### Invitation token (existing 3-part envelope, extended to 4-part)

The existing envelope, defined in `services/invitation_service.sign_invitation_token` (line 449), is:

```
{raw_token_b64u}.{exp_unix_ts}.{mac_b64u}
```

where `mac_b64u = _b64u_encode(HMAC-SHA-256(secret, raw_token_b64u + "." + exp_unix_ts))`. The MAC is URL-safe base64 encoded (matches the existing `_b64u_encode` helper used elsewhere in `services/invitation_service.py`).

**This spec extends the envelope to 4-part** (NFR-011-010, Rev.3.2):

```
{raw_token_b64u}.{exp_unix_ts}.{kid}.{mac_b64u}
```

where `mac_b64u = _b64u_encode(HMAC-SHA-256(secret_for(kid), raw_token_b64u + "." + exp_unix_ts + "." + kid))`. The `kid` is the value of `INVITATION_TOKEN_KID_NEW` at issuance time. Verification:

1. Try 4-part split first.
   - If the embedded `kid == INVITATION_TOKEN_KID_NEW`: verify under the active secret.
   - If `kid == INVITATION_TOKEN_KID_OLD` AND we are within the grace window: verify under the old secret.
   - Otherwise reject.
2. If the envelope is 3-part (legacy): verify under `INVITATION_TOKEN_KID_OLD` only, and only during the grace window. Otherwise reject.

The grace window begins when an `INVITATION_TOKEN_KID_OLD` env var is set on the running app and ends `INVITATION_TOKEN_KID_GRACE_HOURS` (default 24) after the application reload. Legacy 3-part tokens issued before this feature is deployed are accepted as grace-window tokens by virtue of the operator setting `INVITATION_TOKEN_KID_OLD` to the legacy secret on the first deploy.

### Invitation acceptance state machine

Existing state machine from `project_invitations` (spec/006 Phase 11) is unchanged. The new branches are on the acceptance handler:

```
[pending] ─accept (new user signup, email match)─→ [accepted]  + create user + membership row
[pending] ─accept (existing logged-in user, email match)─→ [accepted]  + membership row only
[pending] ─accept (email mismatch)─→ [pending]  (generic invalid response, FR-011-107)
[pending] ─accept (already-member case)─→ [pending]  (409, no row changes)
[pending] ─expire/revoke─→ [expired]/[revoked]
[pending] ─bootstrap accept (member kind + ownership_transfer)─→ [accepted] + membership + Project.owner_id transferred + prior owner demote + composite audit
```

The decisive SQL pattern (FR-011-106):

```sql
UPDATE project_invitations
SET status = 'accepted', accepted_at = now()
WHERE id = :id AND status = 'pending' AND expires_at > now()
RETURNING *;
```

Zero rows returned = abort with generic invalid response.

---

## Audit Events

New audit-action strings introduced by this spec. Each row identifies which existing table the action is written into and the responsible service module.

| Action string | Table | Actor | Target | Free-form fields | Notes |
|---|---|---|---|---|---|
| `project.member.invite_accepted_signup` | `project_audit_log` | accepting user | project | — | New user signup via member-kind invitation |
| `project.member.invite_accepted` | `project_audit_log` | accepting user | project | — | Existing user accepts member-kind invitation |
| `project.trusted_user.invite_accepted` | `project_audit_log` | accepting user | project | — | Existing or new user accepts trusted-kind invitation |
| `project.ownership.bootstrap_transfer` | `project_audit_log` | accepting user (new owner) | project | `pre_transfer_action_summary` (JSON, R6 redaction policy) | SU-bootstrap composite |
| `platform.user.password_reset_by_superuser` | `platform_audit_log` | superuser | target user id (in `detail`) | `reason` (A-13 detector) | Step-up required |
| `platform.user.password_reset_self` | `platform_audit_log` | superuser | superuser (self) | `reason` (A-13 detector) | Step-up required |
| `platform.user.email_changed` | `platform_audit_log` | user or admin | user | old/new email hash | Triggers session invalidation + trusted-device revoke + cool-off |
| `platform.user.two_factor_reset_by_superuser` | `platform_audit_log` | superuser | target user | `reason` (A-13 detector) | Step-up required; existing path with new audit-action name |
| `auth.login.new_device` | `platform_audit_log` | user | user (self) | device fingerprint hash | New banner trigger |
| `platform.api_key.revoke` | `platform_audit_log` | admin or user | api_key (in `detail`) | — | Already an audit event pattern; consolidated under this string |
| `auth.trusted_device.revoke_all` | `platform_audit_log` | system (admin password reset / self-reset / email change / 2FA disable triggers) | user | reason code (`password_reset`, `password_reset_self`, `email_change`, `2fa_disable`) | Emitted by `TrustedDeviceService.revoke_all_for_user` per FR-011-402 / R10. Surfaces in the banner list (see `me-banners-activity.yaml` BannerItem enum) so the affected user notices the trusted-device wipe. |

Existing audit-action strings used elsewhere (e.g. `auth.trusted_device_bypass_accepted`, `platform.project.archive`) are not modified by this spec.

The `pre_transfer_action_summary` JSON shape (FR-011-123, R6):

```json
{
  "summary": [
    {
      "action": "project.config.update",
      "occurred_at": "2026-05-21T11:50:00Z"
    },
    {
      "action": "dataset.delete",
      "occurred_at": "2026-05-21T11:52:00Z",
      "target_id": "dataset-uuid-here"
    }
  ]
}
```

The `occurred_at` field (not `timestamp` or `timestamp_iso`) mirrors the `project_audit_log.occurred_at` / `platform_audit_log.occurred_at` column naming. Action strings use the existing codebase `verb.noun.verb` convention (e.g. `dataset.delete`, not `dataset.deleted`).

`target_id` is preserved **only** for actions in the `DESTRUCTIVE_ACTIONS` allowlist defined in `services/audit_service.py` (R6):

```python
DESTRUCTIVE_ACTIONS: Final[frozenset[str]] = frozenset({
    "project.delete",
    "dataset.delete",
    "recording.delete",
    "project.acl.update",          # role grants / revocations
    "project.permission.elevate",  # admin role grants
    "project.visibility.update",   # public ⇄ restricted
})
```

(The exact existing-name spellings are reconciled at implementation time by grepping `services/` for current verbs; the table above is the canonical target. Any name that does not currently exist in the codebase is added in the same PR that introduces the corresponding audit call site.)

All other entries in `pre_transfer_action_summary` carry `{action, occurred_at}` only; the A-13 detector test enumerates this allowlist and asserts no other action leaks `target_id`.

---

## ACTION Constants (9-class coherence)

Per FR-011-310 / spec/007. Added to `apps/api/echoroo/core/actions.py`.

| Name | Scope | Required permission | Superuser-only | spec/007 9-class |
|---|---|---|---|---|
| `PROJECT_MEMBER_INVITATION_ISSUE_ACTION` | PROJECT | `MANAGE_MEMBERS` | No | project-action |
| `ADMIN_USER_RESET_PASSWORD_ACTION` | USER | (n/a) | Yes | superuser-action |
| `USER_BANNER_LIST_ACTION` | USER (self) | (n/a) | No | self-action |
| `USER_BANNER_DISMISS_ACTION` | USER (self) | (n/a) | No | self-action |
| `USER_ACTIVITY_LIST_ACTION` | USER (self) | (n/a) | No | self-action |

The `TOKEN_AUTH_ONLY` allowlist (per spec/007) gains two entries (no ACTION, no gate_action):

- `GET /web-api/v1/auth/invitations/{token}`
- `POST /web-api/v1/auth/invitations/{token}/accept`

The endpoint-coverage hard-fail test classifies them under this exemption.

---

## Settings — Net Additions

| Setting | Type | Default | Purpose |
|---|---|---|---|
| `INVITATION_TOKEN_KID_NEW` | `str` | (operator-set, required at every boot) | Active kid for invitation token HMAC signing. NFR-011-010. Mirrors the `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW` env-var naming pattern from Phase 17 A-12. |
| `INVITATION_TOKEN_KID_OLD` | `str \| None` | `None` (but **required at initial deploy** of this feature; can be unset after grace window expires) | Previous kid for dual-verify during rotation. Mirrors A-12's `..._KID_OLD`. |
| `INVITATION_TOKEN_KID_GRACE_HOURS` | `int` | `24` | Grace window beyond TTL during which old-kid tokens remain verifiable. |
| `INVITATION_TOKEN_HMAC_KEY` | `str` | (operator-set, required at every boot) | HMAC key for the NEW kid. Mirrors A-12's `..._HMAC_KEY`. |
| `INVITATION_TOKEN_HMAC_KEY_OLD` | `str \| None` | `None` (but **required whenever `INVITATION_TOKEN_KID_OLD` is set**; `get_settings()` `model_validator(mode="after")` refuses to start otherwise, matching the existing A-12 co-presence validator pattern in `core/settings.py:516-528`) | HMAC key for the OLD kid. Mirrors A-12's `..._HMAC_KEY_OLD`. |

The deletions are listed in spec.md Removal Plan §settings; they are also enforced by the CI guard test (R12).

---

## Constraints, Invariants

### Application-level (services)

- A `ProjectInvitation` with `ownership_transfer_on_accept = true` and `kind != 'member'` MUST be rejected at both `create_invitation` (before INSERT) and `accept_invitation` (defence-in-depth), raising `InvitationStateError("ownership_transfer_on_accept_invalid_for_kind")`. The DB CHECK constraint is the final fallback (R5).
- A `users.temp_password_expires_at IS NOT NULL` MUST imply `users.must_change_password = true`. Set together at reset; cleared together on change. `services/admin_password_reset.reset_password` MUST set both columns in the same `UPDATE` statement (atomic). The test `test_admin_password_reset_atomicity` asserts this.
- A successful password change MUST invalidate all other active sessions of the user and revoke all of the user's trusted-device records via the existing `TrustedDeviceService.revoke_all_for_user` (FR-011-205, FR-011-402, R10).
- An email change MUST trigger: audit + banner enqueue + session invalidation + trusted-device revocation + 24h cool-off (FR-011-305, FR-011-402).

### Cross-system

- Banner queries (`GET /me/banners`) MUST scope to authenticated user; never expose other users' audit rows.
- Activity queries (`GET /me/activity`) MUST scope similarly; no cross-user leak.
- `pre_transfer_action_summary` MUST preserve `target_id` **only** for actions in `DESTRUCTIVE_ACTIONS`; the A-13 detector test asserts this.
- `user_banner_dismissals.audit_log_id` is NOT enforced via FK (polymorphism); `services/user_banner.py` MUST validate the referenced audit row exists at write time and return 404 if not.

---

## Schema Evolution Order

`0019_email_verification_trusted_devices` (existing) → `0020_add_target_taxa_to_projects` (existing) → **`0021_zero_email_additive`** (new, additive) → **`0022_email_subsystem_removal`** (new, destructive).

Both new migrations have `downgrade()` stubs that raise (forward-only policy, NFR-011-002).
