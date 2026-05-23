# Inviting Users — Single and Bulk Walkthrough

**Audience**: Project admins on a Restricted project (per spec/006) who
need to grant access to one or more collaborators.

**Prerequisite**: You are logged in as a user with role
`ADMIN`, `OWNER`, or system-superuser AND have completed 2FA enrollment
(spec/006 FR-024, spec/011 NFR-011-007 — 2FA required for member
invitation issuance).

**Why this matters**: Echoroo is **zero-email** by design (spec/011).
The application sends no email under any circumstance — every
invitation URL is returned directly to you (the issuer) so you can hand
it off through your own channel (lab Slack, institutional email,
Discord, in-person, printed QR, etc.).

---

## 1. Single-invite walkthrough

### Via UI

1. Open the project's **Collaborators** screen.
2. Click **Issue invitation**.
3. Fill the form:
   - **Email**: the collaborator's contact email (this is the *bound*
     email — the invitation will be redeemable only by a user who logs
     in with this exact address; the comparison is NFKC + casefold per
     FR-011-205).
   - **Role**: `VIEWER`, `MEMBER`, or `ADMIN`. (Owner role transfer
     uses the separate ownership-transfer flow — see
     `docs/operations/superuser-bootstrap.md`.)
4. Click **Submit**. The response panel displays the one-shot
   `invitation_url` exactly once. Copy it immediately — the URL is
   NOT persisted in any view you can revisit, and the response carries
   `Cache-Control: no-store` so browser back-cache will not surface it.
5. Hand the URL to the collaborator through your own channel.

The invitation:
- Is valid for **7 days** (default TTL).
- Is single-use — once accepted, subsequent attempts return the generic
  "invitation no longer valid" page (FR-011-104).
- May be revoked any time before acceptance via
  `DELETE /web-api/v1/projects/{project_id}/invitations/{invitation_id}`
  (Step 8 / FR-011-115).

### Via API (cURL)

```bash
# Replace SESSION_COOKIE / CSRF_TOKEN / STEP_UP_TOKEN with the values
# from your authenticated session.
curl -X POST "https://<host>/web-api/v1/projects/${PROJECT_ID}/invitations" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "X-Step-Up-Token: ${STEP_UP_TOKEN}" \
  -d '{
    "email": "collaborator@example.org",
    "role": "MEMBER"
  }'
```

Response (HTTP 201) — `MemberInvitationIssueResponse` per
`apps/api/echoroo/schemas/member_invitations.py`:

```json
{
  "invitation_id": "<invitation_id>",
  "invitation_url": "https://<host>/invite/<4-part-signed-envelope>",
  "expires_at": "2026-05-30T10:00:00Z",
  "bound_email_hash": "<sha256-hash-of-canonical-email>"
}
```

(`role` is the role you submitted in the request body; it is not
echoed in this response — the issuing admin already knows it. The
audit row `project.member.invitation_issued` records it for
forensics.)

Headers:

```
Cache-Control: no-store, no-cache, must-revalidate, private
```

---

## 2. Bulk-invite walkthrough

For onboarding more than a handful of collaborators (the canonical
scenario: a 20-person research group), use bulk mode.

### Via UI

1. Open the project's **Collaborators** screen → **Bulk invite** tab.
2. Paste the emails (one per line, comma-separated, or
   tab-separated).
3. Choose **one role** to apply to every entry. (Bulk mode does not
   support per-row roles — issue separate batches if you need mixed
   roles.)
4. Click **Submit**. The response table lists every email with its
   per-row status:
   - `issued` — invitation created; the row carries the
     `invitation_url`.
   - `duplicate_in_batch` — the email appeared twice in the same
     submission; only the first row was issued.
   - `already_pending` — an unexpired invitation for that email
     already exists on this project; you may revoke the existing one
     first if you need to re-issue.
   - `already_member` — the email already maps to a current project
     member; no invitation needed.
   - `invalid_email` — the address failed NFKC + canonicalisation
     validation.
5. Click **Copy all as CSV** to grab every `issued` row at once, then
   hand them to your collaborators.

### Per-issuer rate cap

- **Max batch size**: 50 emails per submission (FR-011-110).
- **Per-issuer global cap**: 200 issued invitations per rolling hour
  (FR-011-114). If you exceed this, the response returns
  `429 Too Many Requests` with `Retry-After`.

### Via API (cURL)

```bash
curl -X POST "https://<host>/web-api/v1/projects/${PROJECT_ID}/invitations/bulk" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "X-Step-Up-Token: ${STEP_UP_TOKEN}" \
  -d '{
    "role": "MEMBER",
    "emails": [
      "alice@example.org",
      "bob@example.org",
      "carol@example.org"
    ]
  }'
```

Response (HTTP 201) — `list[BulkInvitationResultItem]` per
`apps/api/echoroo/schemas/member_invitations.py`. The body is a
**top-level array** (no `{"results": [...]}` envelope); each entry
carries a `status` discriminator from the enum
`issued | duplicate_pending | rate_limited | internal_error`:

```json
[
  {
    "email": "alice@example.org",
    "status": "issued",
    "invitation_id": "<uuid-1>",
    "invitation_url": "https://<host>/invite/<4-part-envelope-1>",
    "expires_at": "2026-05-30T10:00:00Z",
    "error_message": null
  },
  {
    "email": "bob@example.org",
    "status": "duplicate_pending",
    "invitation_id": null,
    "invitation_url": null,
    "expires_at": null,
    "error_message": "An unexpired invitation already exists for this email on this project."
  },
  {
    "email": "carol@example.org",
    "status": "issued",
    "invitation_id": "<uuid-3>",
    "invitation_url": "https://<host>/invite/<4-part-envelope-3>",
    "expires_at": "2026-05-30T10:00:00Z",
    "error_message": null
  }
]
```

Status discriminator values:

| Value | Meaning |
|---|---|
| `issued` | Invitation created; `invitation_id`, `invitation_url`, and `expires_at` are populated |
| `duplicate_pending` | An unexpired invitation already exists for this email + project; revoke and re-issue if you need to override |
| `rate_limited` | Per-issuer hourly cap reached for this row (other rows in the same batch may still have been issued before the cap tripped); `error_message` carries the human-readable reason |
| `internal_error` | Per-row infra fault (Redis unavailable, transient DB error); `error_message` carries a short human-readable reason — never a stack trace |

Note: malformed input (e.g. an `emails` list above the 50-entry cap
or any single invalid email) is rejected with HTTP 422 for the whole
batch BEFORE any per-row processing — the per-row `internal_error`
status covers transient infrastructure failures, not validation
failures.

Headers:

```
Cache-Control: no-store, no-cache, must-revalidate, private
```

---

## 3. What the recipient sees

When the collaborator opens the URL:

- **New user**: they reach a signup form prefilled with the bound
  email (read-only) and the role they will receive. After completing
  signup (password + 2FA enrollment) they are added to the project at
  the invitation's role and the invitation is marked accepted.
- **Existing user, NOT logged in**: they are prompted to sign in with
  the bound email; once signed in the form becomes a one-click
  "Accept this invitation" confirmation.
- **Existing user, ALREADY logged in with the bound email**: a
  one-click confirmation is shown immediately. No new user is created.
- **Mismatch** (logged in as a different email, or submits a
  different signup email): the request is rejected with a *generic*
  invitation-invalid message. The error copy is intentionally
  indistinguishable from "expired", "revoked", or "never existed" to
  prevent enumeration (FR-011-104, FR-011-106).

---

## 4. Audit log

Every issuance produces an audit row in `project_audit_log`:

| Field | Value |
|---|---|
| `action` | `project.member.invitation_issued` |
| `actor_user_id` | Your user id |
| `target_user_id` | NULL (the recipient has no user yet) |
| `detail` | `{"email_hash": "<sha256>", "role": "MEMBER", "invitation_id": "<uuid>", "kid": "<active-kid>"}` |

The plaintext email and the `invitation_url` are NEVER stored in the
audit log — only the SHA-256 `email_hash` (PII hash) and the kid stamp.
This is enforced by the spec/011 telemetry redaction registry
(`echoroo/observability/__init__.py::SENSITIVE_FIELDS`).

---

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `403 step_up_required` | Step-up token expired (5 min TTL) or 2FA not completed | Re-complete a step-up challenge via the existing WebAuthn challenge path (`POST /web-api/v1/auth/2fa/webauthn/challenge`) — see `docs/operations/admin-recovery-flows.md` §1 for the spec/011 step-up endpoint status — then retry with the fresh `X-Step-Up-Token` header |
| `409 already_pending` | Unexpired invitation exists for this email + project | Revoke the existing invitation first, or wait for it to expire |
| `409 already_member` | The email is already a project member | No invitation needed; share project URL directly |
| `429 too_many_requests` | Per-issuer hourly cap (200 invitations / hour) hit | Wait for the rate-limit window to elapse — see `Retry-After` header |
| Recipient sees "invitation no longer valid" | Expired, revoked, already redeemed, mismatched email, OR never existed (anti-enumeration unifies these) | Re-issue from the Collaborators screen |

---

## See also

- `docs/operations/admin-recovery-flows.md` — password reset, 2FA
  recovery
- `docs/operations/superuser-bootstrap.md` — SU bootstrap workflow
- `docs/runbook/invitation_token_kid_rotation.md` — invitation token
  signing key rotation
- `specs/011-zero-email-deployment/spec.md` — full spec
