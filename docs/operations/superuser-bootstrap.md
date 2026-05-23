# Superuser Project Bootstrap

**Audience**: System superusers (`users.is_superuser = true`) creating
a project on behalf of a future owner who is not yet on the platform
(or is already on the platform but has never operated a project).

**Why this exists**: In the canonical Echoroo deployment a research-lab
PI (the system superuser) hosts the instance for their collaborators.
Often the PI needs to spin up a project for a postdoc / grad student
who:

- Is not yet registered, AND
- Will eventually own the project autonomously.

The SU bootstrap flow solves this in a single create-project operation
(US7 / FR-011-121..125): the SU creates the project, names the future
owner via `intended_owner_email`, hands the resulting invitation URL
off, and the future owner's acceptance atomically transfers ownership
to them.

**Prerequisite**: You are logged in as a system superuser AND have
completed a step-up challenge in the last 5 minutes (FR-011-206).

---

## 1. End-to-end walkthrough

### Step 1 — Create the project + intended owner invitation

> **Step-up token surface — spec/011 status (Step 12 R1 P1-1).** The
> dedicated `POST /web-api/v1/auth/step-up/*` begin/complete
> endpoints (T300 / T301) are not yet implemented. Today the only way
> to obtain a step-up token is the existing WebAuthn challenge path
> (`POST /web-api/v1/auth/2fa/webauthn/challenge`). See
> `docs/operations/admin-recovery-flows.md` §1 "Procedure — API" for
> the full status note and operator workaround.

```bash
# Step 1a: complete a step-up challenge (existing /2fa/webauthn/challenge
# path today) to obtain X-Step-Up-Token.

# Step 1b: create the project, naming the intended owner. Note the path
# is /web-api/v1/projects/ (no admin/ prefix) — the bootstrap branch is
# triggered by the optional intended_owner_email field, which the route
# silently drops for non-superuser callers (FR-011-125
# anti-enumeration).
curl -X POST "https://<host>/web-api/v1/projects/" \
  -H "Content-Type: application/json" \
  -H "Cookie: echoroo_session=${SU_SESSION_COOKIE}" \
  -H "X-CSRF-Token: ${CSRF_TOKEN}" \
  -H "X-Step-Up-Token: ${STEP_UP_TOKEN}" \
  -d '{
    "name": "Mt. Tsukuba 2026 Spring Survey",
    "description": "Acoustic monitoring of Aves on Mt. Tsukuba.",
    "visibility": "restricted",
    "intended_owner_email": "future-owner@example.org"
  }'
```

Response (HTTP 201) — `ProjectCreateResponse` (`apps/api/echoroo/
schemas/project.py`) which extends `ProjectResponse` with **flat**
`invitation_url` + `invitation_id` fields at the top level. There is
no nested `project` / `invitation` envelope; the bootstrap fields ride
alongside the project fields on every create response (both `null`
for the non-bootstrap branch — same shape, FR-011-125):

```json
{
  "id": "<project-uuid>",
  "name": "Mt. Tsukuba 2026 Spring Survey",
  "description": "Acoustic monitoring of Aves on Mt. Tsukuba.",
  "target_taxa": null,
  "visibility": "restricted",
  "license": "CC-BY-NC-SA-4.0",
  "restricted_config": { "...": "policy snapshot" },
  "restricted_config_version": 1,
  "status": "active",
  "dormant_since": null,
  "archived_since": null,
  "owner": {
    "id": "<your-superuser-uuid>",
    "display_name": "Lab PI"
  },
  "created_at": "2026-05-23T10:00:00Z",
  "updated_at": "2026-05-23T10:00:00Z",
  "current_user_role": "owner",
  "invitation_url": "https://<host>/invite/<4-part-signed-envelope>",
  "invitation_id": "<invitation-uuid>"
}
```

Headers:

```
Cache-Control: no-store, no-cache, must-revalidate, private
```

Notes:

- The project is created with `owner_id = superuser.id` initially.
- An invitation is atomically issued with
  `kind = member`, `role = ADMIN`, and
  `ownership_transfer_on_accept = true` (FR-011-121).
- The check constraint
  `ownership_transfer_on_accept = false OR kind = 'member'` (migration
  `0021_zero_email_additive`) enforces that ownership transfer flags
  are only ever set on member-kind invitations.

### Step 2 — Hand the invitation URL to the future owner

The `invitation_url` is one-shot and shown to you exactly once.
Hand it off through your usual channel (lab Slack, email, in-person).

### Step 3 — The future owner accepts

When the future owner opens the URL:

1. **If they are not yet registered**: they sign up with the bound
   email + password + 2FA enrollment. Upon signup completion the
   acceptance transaction:
   - Creates the new user (`User.id = NEW_UUID`).
   - Adds the new user to the project at role `OWNER` (NOT `ADMIN`
     — see "ownership transfer" below).
   - Atomically transfers ownership: `projects.owner_id = NEW_UUID`.
   - Removes the superuser from the project membership (they no
     longer need access unless explicitly re-invited).
   - Emits a composite audit row (see §2).
2. **If they are already registered AND their authenticated email
   matches the bound email**: a one-click "Accept this invitation"
   confirmation is shown. The same ownership transfer steps run.

### Step 4 — Verify the transfer

```sql
SELECT id, name, owner_id FROM projects WHERE id = '<project-uuid>';
-- → owner_id should now be the future owner's user id
```

The future owner's `/profile/activity` view will show a
`pre_transfer_action_summary` banner (FR-011-122) — see §2.

---

## 2. `pre_transfer_action_summary` — what the future owner sees

Per FR-011-122 + R10, when an SU bootstraps a project for an intended
owner, any actions the SU performs **between project creation and
invitation acceptance** are summarised into a single composite audit
row that the new owner sees on first login.

This handles the scenario where the SU does setup work (creates
datasets, uploads fixtures, configures recording site metadata) on
behalf of the future owner; the new owner has a right to know what
was done in their project before they assumed ownership.

### Audit row shape

| Field | Value |
|---|---|
| `action` | `project.ownership.bootstrap_transfer` |
| `actor_user_id` | The superuser's user id |
| `target_user_id` | The new owner's user id |
| `project_id` | The project id |
| `detail` | `{"pre_transfer_action_summary": {"summary": [...]}}` |

### `pre_transfer_action_summary.summary` element shape

Each entry in the `summary` array has:

```json
{
  "action": "project.dataset.created",
  "occurred_at": "2026-05-23T10:15:00Z",
  "target_id": "<dataset-uuid-only-when-destructive>"
}
```

- `target_id` is preserved ONLY for actions in
  `services/audit_service.DESTRUCTIVE_ACTIONS` so a hostile SU cannot
  hide a deletion behind a generic summary line. Non-destructive
  actions surface only `action` + `occurred_at`.
- The summary is a one-time, ordered snapshot — subsequent audit
  events after the transfer go into the normal `project_audit_log`
  stream.

### Where the new owner sees it

The future owner's first login after acceptance surfaces a banner via
`GET /web-api/v1/me/banners` carrying:

```json
{
  "audit_table": "project_audit_log",
  "audit_log_id": "<bootstrap-row-uuid>",
  "event_type": "project.ownership.bootstrap_transfer",
  "occurred_at": "2026-05-23T11:00:00Z",
  "detail": {
    "pre_transfer_action_summary": {
      "summary": [
        { "action": "project.created", "occurred_at": "2026-05-23T10:00:00Z" },
        { "action": "project.dataset.created", "occurred_at": "2026-05-23T10:15:00Z" },
        { "action": "project.recording_site.created", "occurred_at": "2026-05-23T10:20:00Z" }
      ]
    }
  }
}
```

The banner is dismissable. The full history remains accessible via
`/profile/activity`.

---

## 3. Edge cases

| Scenario | Behaviour |
|---|---|
| Future owner is already on the platform with a 2FA-enrolled account using the bound email | One-click acceptance → ownership transferred → SU removed from membership. |
| Future owner has a platform account but signs up via the URL with a DIFFERENT email | Generic invitation-invalid page (anti-enumeration). Re-issue with the correct email. |
| SU tries to bootstrap with `ownership_transfer_on_accept = true` but `kind = trusted` | DB CHECK constraint rejects: 400 "ownership_transfer_on_accept requires kind=member". |
| Future owner declines (never opens the URL, invitation expires) | Project remains owned by the SU. SU may revoke the project or re-issue an invitation. |
| SU bootstraps for the SU's own email | Invitation acceptance is a no-op transfer (SU stays as owner). The audit row records the attempted transfer. |
| SU bootstraps the same email twice for the same project | Second issuance returns `409 already_pending`. Revoke the first invitation if you need to re-issue. |

---

## 4. Audit log forensics

To find every bootstrap-transfer performed in the last 7 days:

```sql
SELECT
  actor_user_id      AS superuser_id,
  target_user_id     AS new_owner_id,
  project_id,
  detail->'pre_transfer_action_summary'->'summary' AS pre_transfer_summary,
  created_at
FROM project_audit_log
WHERE action = 'project.ownership.bootstrap_transfer'
  AND created_at > now() - interval '7 days'
ORDER BY created_at DESC;
```

To find every still-pending SU-issued ownership-transfer invitation:

```sql
SELECT
  i.id              AS invitation_id,
  i.email_hash,
  i.project_id,
  i.expires_at,
  i.created_at,
  u.id              AS issuer_user_id,
  u.email           AS issuer_email
FROM project_invitations i
JOIN users u ON u.id = i.created_by_user_id
WHERE i.ownership_transfer_on_accept = true
  AND i.accepted_at IS NULL
  AND i.revoked_at IS NULL
  AND i.expires_at > now()
ORDER BY i.expires_at;
```

---

## See also

- `docs/operations/inviting-users.md` — regular collaborator
  onboarding (non-ownership flow)
- `docs/operations/admin-recovery-flows.md` — password / 2FA recovery
- `specs/011-zero-email-deployment/spec.md` — US7 + FR-011-121..125 +
  FR-011-122 audit shape
