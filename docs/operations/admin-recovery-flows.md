# Admin Recovery Flows — Password Reset & 2FA Disable

**Audience**: System superusers (`users.is_superuser = true`)
operating an Echoroo deployment. End-users who lost access ask their
superuser; the superuser performs recovery from inside the admin
panel — **no self-service email-driven recovery exists** (spec/011
Non-Goals, FR-011-201..210).

**Prerequisite**: You are logged in as a system superuser AND you have
completed a **step-up authentication challenge** in the last 5 minutes.
The challenge requires BOTH your current password AND a successful 2FA
challenge (TOTP code or WebAuthn assertion) — password-only re-entry
is insufficient (FR-011-206).

---

## 1. Password reset (FR-011-201..210)

### When to use

- User reports they forgot their password.
- User's account is locked due to repeated failed login attempts and
  you have verified their identity out-of-band (call, in-person, lab
  Slack DM with a known-good identity).
- You need to reset your own superuser password (the self-reset path
  uses the same flow with `target_user_id = your_user_id`).

### Procedure — UI

1. Open **Admin → Users**.
2. Locate the target user (search by email).
3. If your step-up window has expired, the **Reset password** button
   triggers a step-up challenge first. Complete password + 2FA.
4. Click **Reset password**. Optionally fill the **Reason** field
   (recorded in the audit log).
5. The response panel shows the **temporary password** exactly once
   in a click-to-reveal field. Copy it immediately — it is shown only
   to you during the click-to-reveal window and to the target user
   when they first log in.
6. Hand the temporary password to the target user through your own
   channel.
7. Tell the target user: log in with the temporary password; the
   forced-password-change middleware will redirect them to
   `/auth/change-password` on first request. They must set a new
   password within 24 hours (FR-011-203 — `temp_password_expires_at`
   default).

### Procedure — API (cURL)

> **Step-up token surface — spec/011 status (Step 12 R1 P1-1).** The
> dedicated `POST /web-api/v1/auth/step-up/*` endpoints (referred to
> as T300 / T301 in `specs/011-zero-email-deployment/tasks.md`) that
> would mint an `admin_recovery`-scoped token via an explicit
> password + 2FA AND-condition challenge are **NOT YET
> IMPLEMENTED** in this build. The helper
> `echoroo.services.step_up_token_service.issue_admin_recovery_step_up_token`
> exists and is wired through the
> `require_step_up_token(SCOPE_ADMIN_RECOVERY)` gate on the
> password-reset endpoint, but no HTTP route currently calls it. A
> follow-up PR (filed as a spec/011 carry-over task) will land the
> begin/complete pair.
>
> Until then, the only way to obtain a step-up token in production is
> the **WebAuthn challenge completion path** —
> `POST /web-api/v1/auth/2fa/webauthn/challenge` returns a
> `SCOPE_ADMIN_DESTRUCTIVE` token on success. That scope is accepted
> by the destructive admin endpoints (`reset-2fa`, the PATCH email
> change, etc.) but **NOT** by the password-reset endpoint, which is
> explicitly gated on `SCOPE_ADMIN_RECOVERY`. The operator workaround
> in the interim is to mint the token in-process (test fixture or
> short-lived admin script invoking the helper directly) and inject
> the resulting JWT via the `X-Step-Up-Token` header. Production
> operators should track the follow-up PR and rely on the UI flow
> (which uses the same backend helper internally) until the endpoint
> ships.

Once the begin/complete endpoints land, the operator-facing flow will
mirror the existing `/2fa/webauthn/challenge` shape — the
`X-Step-Up-Token` header carrying the issued JWT is the contract.

```bash
# Step 1: complete a step-up challenge to obtain X-Step-Up-Token.
# Today: use the existing WebAuthn challenge endpoint
# (POST /web-api/v1/auth/2fa/webauthn/challenge — see auth.py).
# Future (spec/011 T300/T301 follow-up): a dedicated
# POST /web-api/v1/auth/step-up/begin + .../complete pair will mint
# an admin_recovery-scoped token via an explicit password + 2FA
# AND-condition challenge.

# Step 2: reset the target user's password.
curl -X POST "https://<host>/web-api/v1/admin/users/${TARGET_USER_ID}/reset-password" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "X-Step-Up-Token: ${STEP_UP_TOKEN}" \
  -d '{
    "reason": "User reported forgotten password — confirmed identity via lab Slack DM"
  }'
```

Response (HTTP 200) — shape `AdminPasswordResetResponse` per
`apps/api/echoroo/schemas/admin.py`:

```json
{
  "temporary_password": "<short-readable-string>",
  "expires_at": "2026-05-24T10:00:00Z"
}
```

(The actor / target ids are derived from the URL path + the
authenticated session cookie; the response body is intentionally
narrow to keep the one-shot credential surface minimal.)

Headers:

```
Cache-Control: no-store, no-cache, must-revalidate, private
```

### Side effects

- `users.must_change_password = true` is set.
- `users.security_stamp` is rotated — all outstanding sessions and
  step-up tokens for the target user are invalidated (FR-011-206
  closing paragraph).
- Trusted Device records for the target user are revoked
  (FR-011-402 — extends spec/010's revocation surface).
- An audit row is emitted with action
  `platform.user.password_reset_by_superuser` (or
  `platform.user.password_reset_self` when actor == target).

### What gets logged where

| Field | Audit log | Application logs | Telemetry (Sentry) |
|---|---|---|---|
| `actor_user_id` | Yes | Yes | Yes (tag) |
| `target_user_id` | Yes | Yes | Yes (tag) |
| `reason` | Yes | No | No |
| `temporary_password` | **NEVER** | **NEVER** (redacted by `RedactionMiddleware` filter) | **NEVER** (redacted by `before_send` hook) |
| `X-Step-Up-Token` | No | **NEVER** (redacted) | **NEVER** (redacted) |

---

## 2. 2FA disable / reset (US5, FR-011-306 — Phase 17 A-11)

### When to use

User lost their 2FA device (phone, security key) and cannot complete
the 2FA challenge required to reach the in-app "Disable 2FA" screen
themselves.

### Procedure

The spec/011 step-up requirement (FR-011-206) means the SU disabling
another user's 2FA must themselves have a *fresh* step-up token. The
operator-facing flow is the existing Phase 17 A-11 endpoint:

```bash
curl -X POST "https://<host>/web-api/v1/admin/users/${TARGET_USER_ID}/reset-2fa" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "X-Step-Up-Token: ${STEP_UP_TOKEN}" \
  -d '{
    "support_ticket_id": "SUP-2026-05-23-001",
    "reason": "User lost phone — verified identity in-person",
    "skip_delay": false,
    "confirmation_token": "<value-from-/auth/confirm-identity-for-2fa-reset>"
  }'
```

Body fields (see `apps/api/echoroo/schemas/admin.py::ResetTwoFactorRequest`):

| Field | Required | Notes |
|---|---|---|
| `support_ticket_id` | Yes | Operator-PII Annotated string; PII reject gate at the boundary (Phase 17 A-13) |
| `reason` | Yes | Operator-PII Annotated string; rejected if it carries email / phone / national identifier patterns |
| `skip_delay` | No (default `false`) | When `true`, opens an M-of-N approval ticket (two co-signers); when `false`, the row enters `pending_delay` and Celery beat dispatches after the 24h delay (FR-072) |
| `confirmation_token` | Yes | Short-lived HMAC token from `POST /web-api/v1/auth/confirm-identity-for-2fa-reset/redeem`; bound to the target `user_id` and consumed exactly once. Replay / mismatch / expired → HTTP 409 |

Response: HTTP 202 Accepted on success — the reset is *queued* (or
queued-pending-approval when `skip_delay=true`); it does not execute
synchronously. The Celery worker performs the actual 2FA reset after
the delay / approval-quorum gate clears, at which point the audit log
records the dispatch.

The route lives at `POST /web-api/v1/admin/users/{user_id}/reset-2fa`
(see `apps/api/echoroo/api/web_v1/admin.py` `reset_two_factor`
handler). The step-up requirement uses `SCOPE_ADMIN_DESTRUCTIVE`
(satisfied by the WebAuthn challenge path), distinct from the
password-reset endpoint which requires `SCOPE_ADMIN_RECOVERY`.

### Side effects

- `users.security_stamp` is rotated — invalidating outstanding
  sessions / step-up tokens for the target user.
- `users.two_factor_enrolled = false`; the target user is required to
  re-enroll 2FA before their next sensitive action (FR-011-401 — 2FA
  enrollment is mandatory app-wide).
- Trusted Device records for the target user are revoked
  (FR-011-402).
- An audit row is emitted with action `platform.user.two_factor_reset`.

---

## 3. Email address change (FR-011-305)

When a user requests an email change (e.g. they switched institutions),
the operator updates `users.email` directly via:

```bash
curl -X PATCH "https://<host>/web-api/v1/admin/users/${TARGET_USER_ID}" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "X-Step-Up-Token: ${STEP_UP_TOKEN}" \
  -d '{
    "email": "new-address@example.org",
    "reason": "User changed institutions"
  }'
```

### Side effects

- `users.email` is updated.
- `users.security_stamp` is rotated (existing sessions / step-up
  tokens invalidated).
- Trusted Device records for the target user are revoked
  (FR-011-402).
- An audit row is emitted with action `auth.user.email_changed`.

No verification email is sent (spec/011 zero-email default). The
operator is responsible for confirming the new address out-of-band
before performing the change.

---

## 4. Operator-side proxy / nginx config — log redaction

**Why**: Echoroo's in-process redaction
(`echoroo.middleware.redaction.RedactionMiddleware`,
`echoroo.observability.sentry`) handles structured-log envelopes and
out-of-process telemetry. Your reverse proxy's access log is a
separate channel — if you do not configure it, the `X-Step-Up-Token`
header value (a 5-min-TTL credential) MAY land in the proxy's log.

**T713** — recommended nginx `log_format` for an Echoroo deployment
behind nginx:

```nginx
# /etc/nginx/conf.d/echoroo.conf

# Default Combined Log Format augmented with explicit step-up-token
# redaction. The `step_up=<redacted>` field is a constant string — the
# proxy NEVER captures the actual header value.
log_format echoroo_safe '$remote_addr - $remote_user [$time_local] '
                         '"$request" $status $body_bytes_sent '
                         '"$http_referer" "$http_user_agent" '
                         'step_up=<redacted>';

# Apply to the Echoroo upstream.
server {
    listen 443 ssl http2;
    server_name echoroo.example.org;

    access_log /var/log/nginx/echoroo.access.log echoroo_safe;
    error_log  /var/log/nginx/echoroo.error.log warn;

    location / {
        proxy_pass http://echoroo_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
        # Echoroo MUST receive the step-up token unchanged; we only
        # redact in the proxy's OWN access log, not in the upstream
        # request.
        proxy_pass_request_headers on;
    }
}
```

### Why this matters

- The `X-Step-Up-Token` header carries a JWT signed with
  `web_session_secret`. It is short-lived (5 min) but still confers
  the ability to perform any admin-recovery action.
- A reverse-proxy access log that captures `$http_x_step_up_token`
  (e.g. via a too-curious custom `log_format`) is a credential leak
  surface NOT covered by Echoroo's in-process redaction.
- The `echoroo_safe` format above explicitly does NOT reference the
  variable — the proxy log simply records that some request carried a
  step-up header without ever recording its value.

### Other proxy products

For Apache, Caddy, or ALB / Cloudflare, the equivalent principle is:
never include `%{X-Step-Up-Token}i` (Apache), `{header.X-Step-Up-Token}`
(Caddy), or `req_x_step_up_token` (ALB) in the access log format
template. Refer to your proxy's log-format syntax — the rule is the
same.

---

## 5. Audit log forensics

To find every recovery action performed in the last 24 hours:

```sql
SELECT
  actor_user_id,
  target_user_id,
  action,
  detail,
  created_at
FROM platform_audit_log
WHERE action IN (
  'platform.user.password_reset_by_superuser',
  'platform.user.password_reset_self',
  'platform.user.two_factor_reset',
  'auth.user.email_changed'
)
  AND created_at > now() - interval '24 hours'
ORDER BY created_at DESC;
```

To find every step-up challenge initiated in the last hour (useful
during a suspected credential-stuffing investigation):

```sql
SELECT
  actor_user_id,
  detail->>'scope' AS scope,
  detail->>'factors' AS factors,
  created_at
FROM platform_audit_log
WHERE action = 'auth.step_up.issued'
  AND created_at > now() - interval '1 hour'
ORDER BY created_at DESC;
```

---

## See also

- `docs/operations/inviting-users.md` — collaborator onboarding
- `docs/operations/superuser-bootstrap.md` — SU project bootstrap
- `docs/runbook/zero-email-deployment-secret-rotation.md` — secret /
  env-var rotation
- `specs/011-zero-email-deployment/spec.md` — full spec (FR-011-201..210
  + FR-011-306 + FR-011-402)
