# Runbook: 2FA Reset Confirmation HMAC Key Rotation (Phase 17 A-12)

This runbook documents the operational procedure for rotating the
dedicated HMAC signing key used by the admin two-factor reset
confirmation token (`POST /web-api/v1/admin/users/{userId}/reset-2fa`,
`confirmation_token` field).

The key is **decoupled** from `web_session_secret` so a leak or
compromise of the generic session signing key does NOT also forge
admin-reset confirmation tokens (FR-091b / OWASP A02 Cryptographic
Failures). Each token carries a `kid` claim; both the kid embedded in
new tokens and the kid accepted from previously issued tokens during
the rotation grace window are configured **entirely via environment
variables** — no source-code change is required to rotate.

Code references:

- `apps/api/echoroo/services/two_factor_confirmation_token.py`
  (`_current_kid`, `_signing_key_for`)
- `apps/api/echoroo/core/settings.py`
  (`two_factor_reset_confirmation_hmac_key{,_old}`,
  `two_factor_reset_confirmation_hmac_kid_{new,old}`)

## When to rotate

Trigger a rotation when ANY of the following holds:

- Suspected compromise of the current key (audit-log evidence,
  leaked secrets manager bundle, departed personnel with key access).
- Annual rotation cadence reached (recommended).
- Personnel change with prior key access (within 7 days of departure).

## Convention

The kid string is a free-form opaque token; this project uses the
sequence `v1`, `v2`, `v3`, ... where the integer is bumped on each
rotation. The "current v" is determined entirely by
`TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW`.

## Procedure (env-only — no source change required)

### 1. Generate the new secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The output is URL-safe and well above the 32-char minimum enforced by
`Settings.validate_production_secrets` for both the `_NEW` and `_OLD`
slots.

### 2. Confirm the pre-rotation env

Assume the deployment is currently issuing `kid="v1"` tokens:

| Env var | Value |
|---|---|
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY` | `<secret_a>` |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW` | `v1` |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD` | (unset) |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD` | (unset) |

### 3. Stage the rotation in the secrets manager

Update all four env vars atomically (bumping `v1` → `v2`):

| Env var | New value | Meaning |
|---|---|---|
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY` | `<secret_b>` (new) | NEW signing key |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW` | `v2` | NEW kid embedded in newly issued tokens |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD` | `<secret_a>` (was NEW) | Previous signing key |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD` | `v1` | Previous kid (matches in-flight tokens) |

The `_OLD` slot lets the verifier accept tokens minted under the
prior key for the duration of the rotation grace window. Tokens
already in flight (each with a 5-minute TTL) keep working without an
operator-facing 401.

> **Strong-secret guard**: in `production` / `staging`, both
> `_HMAC_KEY` AND `_HMAC_KEY_OLD` (when set) are validated against the
> dev default literal and a `len >= 32` floor. A weak `_OLD` would
> otherwise become a live signing key for the duration of the grace
> window. The guard fires at startup; a misconfigured deploy will
> refuse to boot.

### 4. Roll out the deploy

Restart all API workers (Docker / k8s rolling restart). New tokens
now carry `kid="v2"` and are signed by `secret_b`; in-flight `kid="v1"`
tokens still verify via the `_OLD` slot.

### 5. Wait for the grace window to elapse

Wait at least **24 hours** before unsetting `_OLD`. Even though the
token TTL is only 5 minutes, the longer wait absorbs:

- clock skew between application instances,
- delayed retries from operator browser tabs,
- any in-flight email magic-link redemptions.

Operationally, leave `_OLD` set for as long as it takes to be sure
all magic links emailed before step 4 have either been redeemed or
expired (30 min email TTL today, see ``MAGIC_LINK_TTL`` in
``services/two_factor_reset_service.py``; verify against
``magic_link.expires_at`` distribution in your fleet metrics).

### 6. Close the grace window

Unset BOTH:

- `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD`
- `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD`

Restart the API workers a second time. The verifier will now reject
any further `kid="v1"` tokens with
`ConfirmationTokenInvalidError("token kid 'v1' is unknown or no
longer accepted")`.

> **Both envs together**: the verifier requires BOTH `_KID_OLD` AND
> `_KEY_OLD` to be set simultaneously to honour a legacy kid. Leaving
> just one set does NOT enable a half-configured grace path; it is
> equivalent to "grace closed".

## Rollback

If the new key proves problematic before step 6:

- **Symmetry option** — swap the `_NEW` and `_OLD` env values (key +
  kid) and redeploy. Both keys remain in service; the previous key is
  now the issuer again. No tokens are invalidated mid-flight.
- **Hard rollback** — revert the env update entirely (restore the
  step-2 state) and unset both `_OLD` envs. In-flight tokens issued
  under the new key during steps 3-4 will fail with
  `ConfirmationTokenInvalidError`; affected operators must request a
  new magic link.

## In-flight token caveat

During the brief window between step 3 (env update) and step 4
(rolling restart) — typically ~30 s — workers may briefly run mixed
configurations. Tokens issued by an upgraded worker carry
`kid="v2"` and are signed with `secret_b`. A pre-restart verifier
that has not yet picked up the new env will reject those tokens with
"unknown kid". Affected operators see a single 401 and can simply
re-request the magic link. This is by design — fallback to
`web_session_secret` was intentionally removed in Phase 17 A-12 to
maintain the key-separation guarantee against session-secret
compromise.

### First-ever deploy of A-12

Tokens minted before A-12 shipped do NOT carry a `k` (kid) claim.
The first deploy after A-12 will reject any kid-less token with
`ConfirmationTokenInvalidError("token is missing kid claim")`.
Affected operators (within the 5-minute TTL window of the deploy)
must request a new magic link. The 5 min TTL caps the blast radius.

## Why the kid is env-driven (Round 2 design note)

An earlier draft of this contract used hard-coded module-level
constants (`KID_CURRENT = "v1"` and `KID_LEGACY = "v_old"`). This
turned out to be subtly broken: a real env-only rotation that bumped
the secret but kept source code unchanged would issue tokens still
labelled `kid="v1"` even though they were signed by the new secret —
and pre-rotation tokens (also `kid="v1"`) would route to the new
secret on the verifier side and fail signature compare. Codex Round 1
flagged this; the fix is the env-driven mapping documented here.

## Long-form rotation cadence

Subsequent rotations follow the same recipe — there is no special
case once you are past `v1`:

| Rotation | `_KID_NEW` | `_HMAC_KEY` | `_KID_OLD` | `_HMAC_KEY_OLD` |
|---|---|---|---|---|
| 1st (initial) | `v1` | `secret_a` | (unset) | (unset) |
| 2nd | `v2` | `secret_b` | `v1` | `secret_a` |
| 3rd | `v3` | `secret_c` | `v2` | `secret_b` |
| ... | `vN` | `secret_N` | `v(N-1)` | `secret_(N-1)` |

Source code is never touched.

## Related runbooks

- `cmk_rotation.md` — KMS CMK rotation (audit chain, PII hash, TOTP DEK,
  invitation HMAC). Different key management substrate (KMS vs local
  HMAC) but identical operational pattern.
