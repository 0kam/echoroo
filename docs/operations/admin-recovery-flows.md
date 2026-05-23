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

```bash
# Step 1: initiate step-up challenge (password + 2FA)
curl -X POST "https://<host>/web-api/v1/auth/step-up/initiate" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -d '{
    "scope": "admin_recovery",
    "current_password": "<your-current-password>",
    "second_factor": {"type": "totp", "code": "123456"}
  }'

# Response carries an X-Step-Up-Token header (5-min TTL).

# Step 2: reset the target user's password
curl -X POST "https://<host>/web-api/v1/admin/users/${TARGET_USER_ID}/reset-password" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "X-Step-Up-Token: ${STEP_UP_TOKEN}" \
  -d '{
    "reason": "User reported forgotten password — confirmed identity via lab Slack DM"
  }'
```

Response (HTTP 200):

```json
{
  "target_user_id": "<uuid>",
  "temporary_password": "<short-readable-string>",
  "temp_password_expires_at": "2026-05-24T10:00:00Z"
}
```

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
curl -X POST "https://<host>/web-api/v1/admin/users/${TARGET_USER_ID}/two-factor/disable" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "X-Step-Up-Token: ${STEP_UP_TOKEN}" \
  -d '{
    "reason": "User lost phone — verified identity in-person",
    "confirmation_token": "<from-confirmation-email-OR-out-of-band>"
  }'
```

(See `apps/api/echoroo/api/web_v1/admin.py` `/two-factor/disable` for
the live signature; the spec/011 change is the addition of the
step-up requirement on top of the existing A-11 confirmation token.)

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
