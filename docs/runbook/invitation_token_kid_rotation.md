# Invitation Token Kid Rotation Runbook

**Spec**: `specs/011-zero-email-deployment/spec.md` §NFR-011-010,
§research.md R3.

**Pattern**: env-driven dual-key rotation mirroring Phase 17 A-12 (the
2FA confirmation HMAC rotation runbook —
`docs/runbook/two_factor_confirmation_key_rotation.md`).

**Audience**: Echoroo deployment operators who need to rotate the HMAC
signing key for invitation tokens, either as planned hygiene or as an
emergency response to a suspected key compromise.

---

## 1. Wire envelope recap

The invitation token envelope is a **4-part** dot-delimited string:

```
{token}.{exp}.{kid}.{mac_b64u}
```

Where:

- `{token}` — opaque random invitation id.
- `{exp}` — Unix epoch seconds of token expiry.
- `{kid}` — short URL-safe id of the HMAC key that signed this token
  (matches `[A-Za-z0-9_-]+`).
- `{mac_b64u}` — base64url HMAC-SHA-256 of `token + "." + exp + "." + kid`
  using the secret stamped under `{kid}`.

Verification accepts:

1. A 4-part envelope whose `{kid}` matches
   `INVITATION_TOKEN_KID_NEW` → verify under
   `INVITATION_TOKEN_HMAC_KEY` (preferred path).
2. A 4-part envelope whose `{kid}` matches
   `INVITATION_TOKEN_KID_OLD` → verify under
   `INVITATION_TOKEN_HMAC_KEY_OLD` (grace window).
3. A 3-part legacy envelope (pre-spec/011 deploys; `{token}.{exp}.{mac}`)
   → tail-comparison fallback under
   `INVITATION_TOKEN_HMAC_KEY_OLD` during the grace window only.

After the grace window expires, paths (2) and (3) are removed by
unsetting both `_OLD` env vars.

---

## 2. Settings checklist

| Env var | Required at every boot? | Purpose |
|---|---|---|
| `INVITATION_TOKEN_KID_NEW` | Yes (non-empty in every environment) | Active kid stamped on newly issued tokens |
| `INVITATION_TOKEN_HMAC_KEY` | Yes (non-empty in every environment; min 32 chars in prod/staging) | HMAC secret for the NEW kid |
| `INVITATION_TOKEN_KID_OLD` | Only during a rotation grace window OR initial spec/011 deploy | Previous kid accepted during grace window |
| `INVITATION_TOKEN_HMAC_KEY_OLD` | MUST be paired with `_KID_OLD` (both set or both unset) | HMAC secret for the OLD kid |
| `INVITATION_TOKEN_KID_GRACE_HOURS` | Optional (default 24) | Hours past invitation TTL during which `_OLD` kid tokens remain verifiable |

**Boot-time guards** (enforced by
`apps/api/echoroo/core/settings.py::Settings.validate_production_secrets`):

- `INVITATION_TOKEN_KID_NEW` empty → boot rejected.
- `INVITATION_TOKEN_HMAC_KEY` empty → boot rejected.
- `_KID_OLD` set without `_HMAC_KEY_OLD` (or vice versa) → boot
  rejected.
- `_KID_OLD == _KID_NEW` → boot rejected.
- Prod / staging: HMAC key < 32 chars → boot rejected.

---

## 3. Planned rotation procedure

**Goal**: rotate the invitation token HMAC key during normal
operations with zero impact on in-flight invitations.

### Step 1 — Generate the new kid + key

```bash
# Generate a strong random kid (10 chars URL-safe).
new_kid=$(python3 -c "import secrets; print(secrets.token_urlsafe(8)[:10])")
# Generate a strong HMAC key (32 bytes base64).
new_hmac_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "new_kid=${new_kid}"
echo "new_hmac_key=${new_hmac_key}"
```

Record both values in your secrets store.

### Step 2 — Promote current → OLD, install new → NEW

Edit the operator-facing secrets layer (CI / Actions secrets, container
env, K8s Secret, etc.) so that:

- Old `INVITATION_TOKEN_KID_NEW` value → moves to
  `INVITATION_TOKEN_KID_OLD`.
- Old `INVITATION_TOKEN_HMAC_KEY` value → moves to
  `INVITATION_TOKEN_HMAC_KEY_OLD`.
- New kid → `INVITATION_TOKEN_KID_NEW`.
- New HMAC key → `INVITATION_TOKEN_HMAC_KEY`.
- Optionally bump `INVITATION_TOKEN_KID_GRACE_HOURS` if you want a
  longer dual-verify window (default 24h is sufficient for the 7-day
  invitation TTL — 7d + 24h = 8d total verification window).

### Step 3 — Deploy

Roll the new env into production. From this moment:

- Newly issued tokens stamp the new kid.
- In-flight tokens (issued under the old kid) continue to verify
  successfully via the `_OLD` slot.

### Step 4 — Observe the grace window

Wait at least `7d` (invitation TTL) plus
`INVITATION_TOKEN_KID_GRACE_HOURS`. By the end of this window, every
invitation still in circulation that was signed under the old kid
will have expired naturally.

### Step 5 — Verify zero old-kid traffic

Run the forensic query (§5) to confirm no old-kid verification
attempts arrive after the grace window.

### Step 6 — Close the rotation

Unset both `INVITATION_TOKEN_KID_OLD` and
`INVITATION_TOKEN_HMAC_KEY_OLD`. Redeploy.

The old kid + key are now retired. Destroy the values in your secrets
store.

---

## 4. Emergency rotation procedure

**Trigger**: confirmed compromise of the current
`INVITATION_TOKEN_HMAC_KEY` value (committed to a public repo, leaked
in a vendor incident, etc.). Every outstanding invitation is now a
forged-token risk.

### Step 1 — Generate new kid + key (same as planned §3.1)

### Step 2 — Decide between FORENSIC and IMMEDIATE-INVALIDATE postures

Two configurations exist, distinguished by their effect on the two
acceptance paths (§1 paths (2) and (3)):

**Posture A — IMMEDIATE INVALIDATE (the canonical emergency response).**
To kill every outstanding 4-part `_OLD`-kid envelope on the next HTTP
turn, **unset both `_OLD` env vars**:

```
INVITATION_TOKEN_KID_OLD=          # unset
INVITATION_TOKEN_HMAC_KEY_OLD=     # unset
```

This relies on the verifier's routing rule (see
`apps/api/echoroo/services/invitation_service.py::verify_invitation_token`):
a 4-part envelope whose `{kid}` matches `INVITATION_TOKEN_KID_OLD` is
ACCEPTED only when that env var is set; with the env unset, the
verifier falls through to `unknown kid` and rejects on the spot. The
3-part legacy fallback also rejects (it requires
`INVITATION_TOKEN_HMAC_KEY_OLD` to be set). This is **not** governed
by `INVITATION_TOKEN_KID_GRACE_HOURS` — that setting only sizes the
3-part legacy grace window past `expires_at` and has no effect on
4-part `_OLD`-kid routing at all.

**Posture B — FORENSIC READABILITY.** If you need to keep classifying
incoming old-kid traffic as "signed under the leaked key" for a short
window (e.g. while the audit log catches up), retain the `_OLD`
values AND shrink the 3-part legacy grace window:

```
INVITATION_TOKEN_KID_OLD=<compromised-kid>
INVITATION_TOKEN_HMAC_KEY_OLD=<compromised-key>
INVITATION_TOKEN_KID_GRACE_HOURS=0
```

In this posture the 4-part `_OLD`-kid envelope STILL verifies (the
verifier routes by kid and checks the MAC under the compromised key).
The `GRACE_HOURS=0` clamp narrows the 3-part legacy fallback so any
token whose envelope `expires_at` has already passed is dead on
arrival, but a 4-part token with future `expires_at` issued under the
leaked key would still successfully verify. **Posture B does NOT
fully invalidate `_OLD`-kid traffic — you must combine it with the
mass-revoke SQL in Step 3 to ensure no compromised token can be
accepted.**

> Pick Posture A unless you have a specific forensic requirement to
> keep the leaked-key path live. The defensive default is to unset
> both `_OLD` env vars.

### Step 3 — Revoke every outstanding invitation

```sql
-- One-shot revocation of every still-pending invitation. The next
-- HTTP turn for any of these tokens will get the generic
-- invitation-invalid page.
UPDATE project_invitations
SET revoked_at = now(),
    revoked_by_user_id = '<your-superuser-uuid>',
    revoke_reason = 'EMERGENCY_KID_ROTATION_2026-05-23'
WHERE accepted_at IS NULL
  AND revoked_at IS NULL
  AND expires_at > now();
```

Notify your project admins (out-of-band) that they will need to
re-issue invitations.

### Step 4 — Deploy the new env

Same as planned §3.3.

### Step 5 — Forensic sweep (§5)

Run the forensic queries to identify any old-kid acceptance attempts
**before** rotation, to scope the exposure. Cross-reference with
external logs (CDN, WAF, application access logs) to detect any
suspect activity that may indicate the leaked key was actually used.

### Step 6 — Close the rotation

Once you are confident no further old-kid traffic is arriving (the
audit log should show zero), unset
`INVITATION_TOKEN_KID_OLD` and `INVITATION_TOKEN_HMAC_KEY_OLD`,
restore `INVITATION_TOKEN_KID_GRACE_HOURS=24` (the default — only
relevant for any future 3-part legacy fallback grace window; has no
effect on 4-part `_OLD`-kid routing), and redeploy.

(If you chose Posture A in Step 2, the `_OLD` env vars are already
unset and only the `GRACE_HOURS` restore remains.)

---

## 5. Forensic queries

### Find every invitation issued under a given kid

```sql
SELECT
  i.id,
  i.email_hash,
  i.project_id,
  i.role,
  i.created_at,
  i.expires_at,
  i.accepted_at,
  i.revoked_at,
  a.detail->>'kid' AS issuance_kid
FROM project_invitations i
JOIN project_audit_log a
  ON a.detail->>'invitation_id' = i.id::text
WHERE a.action = 'project.member.invitation_issued'
  AND a.detail->>'kid' = '<old-kid-value>'
ORDER BY i.created_at;
```

### Find every acceptance attempt under a given kid in the last 24h

```sql
SELECT
  a.actor_user_id,
  a.target_user_id,
  a.detail->>'invitation_id' AS invitation_id,
  a.detail->>'kid' AS verification_kid,
  a.detail->>'verification_outcome' AS outcome,
  a.created_at
FROM project_audit_log a
WHERE a.action IN (
  'project.member.invitation_accepted_signup',
  'project.member.invitation_accepted_existing_user',
  'auth.invitation.verification_failed'
)
  AND a.detail->>'kid' = '<old-kid-value>'
  AND a.created_at > now() - interval '24 hours'
ORDER BY a.created_at DESC;
```

### Confirm zero old-kid traffic after grace window

```sql
SELECT COUNT(*) AS old_kid_verifications_post_grace
FROM project_audit_log
WHERE detail->>'kid' = '<old-kid-value>'
  AND created_at > (
    -- Last "grace ends" timestamp = rotation start + 7d invitation TTL
    -- + grace_hours. Substitute your actual rotation start time below.
    '<rotation-start>'::timestamptz + interval '7 days' + interval '24 hours'
  );
-- Expect 0. If non-zero, investigate before closing the rotation.
```

---

## 6. Test fixtures

The invitation token signing service is exercised by:

- `apps/api/tests/integration/test_invitation_token_kid_rotation.py`
- `apps/api/tests/security/test_invitation_token_kid_rotation.py`

These tests fixture both kid slots and verify the 4-part new envelope,
the 4-part old-kid envelope, the 3-part legacy fallback, and the
boot-time co-presence guards. Run them before AND after any rotation.

---

## 7. Related rotation runbooks

- `docs/runbook/two_factor_confirmation_key_rotation.md` — Phase 17
  A-12 (the pattern this runbook mirrors)
- `docs/runbook/cmk_rotation.md` — KMS CMK rotation
- `docs/runbook/dek_rewrap.md` — DEK rewrap for envelope encryption
- `docs/runbook/zero-email-deployment-secret-rotation.md` — full
  spec/011 secret inventory

---

## 8. Spec references

- spec/011 §NFR-011-010 — kid rotation requirement
- spec/011 §research.md R3 §4 — initial-deploy `_OLD` slot mandate
- spec/011 §data-model.md §Settings — env var inventory
- `apps/api/echoroo/services/invitation_service.py` —
  `sign_invitation_token` / `verify_invitation_token` implementation
- `apps/api/echoroo/core/settings.py` — boot-time validators
