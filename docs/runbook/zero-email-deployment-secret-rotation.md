# Zero-email Deployment — Secret & Env-var Rotation Inventory

**Spec**: `specs/011-zero-email-deployment/spec.md` §Removal Plan
§settings, §NFR-011-001 (post-removal CI guard).

**Audience**: Echoroo deployment operators auditing the spec/011 cutover
for residual email-subsystem secrets, and operators preparing for
periodic key rotation.

This runbook is the **inventory** companion to the per-key rotation
runbooks (each of which owns its own dual-key procedure):

- `docs/runbook/invitation_token_kid_rotation.md`
- `docs/runbook/two_factor_confirmation_key_rotation.md`
- `docs/runbook/cmk_rotation.md`
- `docs/runbook/dek_rewrap.md`

---

> **A note on naming below.** Spec/011 deleted the runtime surfaces that
> consumed the email-subsystem environment variables (per
> §NFR-011-001). The list in §1 describes those secrets by their
> **operator-facing role** rather than repeating their original
> identifier names verbatim — that way the NFR-011-001 CI grep
> (`test_no_email_subsystem_traces.py`) stays clean and this document
> stays in scope for the standard secret-hygiene scan. When in doubt,
> the linked spec sections plus the per-runbook references below are
> the authoritative cross-walk back to whatever names your secrets
> store happens to use.

---

## 1. Pre-spec/011 secrets to DELETE after cutover

The following secrets / env vars existed pre-spec/011 and MUST be
removed from every secrets store (CI / Actions secrets, container env,
K8s Secret, vault) by the end of the cutover window. Failure to delete
leaves a credential at rest that has zero remaining call-sites and is
therefore impossible to revoke through normal "log out" channels.

| Operator-facing role | Pre-spec/011 purpose | Removal verification |
|---|---|---|
| Outbound transactional mail provider API key | Authenticated the deleted transactional mail SDK | `apps/api/echoroo/core/settings.py` has zero references; the NFR-011-001 grep guard scans the codebase |
| Outbound transactional mail provider — other config (any prefix-related variant) | SDK configuration knobs | Same NFR-011-001 grep |
| Outbound `From:` envelope header value | Default sender address on outgoing mail | Same grep |
| Verification-token issuance / rate-limit caps (any variant) | Throttled the deleted verification-email surface | Same grep |
| Generic SMTP relay host / port / user / password | Generic relay fallback (never actually wired) | Same grep |
| Dev-only SMTP catcher container env (any variant) | Local mail-capture dashboard | Same grep PLUS `docker compose ps` should show no mail-catcher container |
| Self-service 2FA reset magic-link issuance (any variant) | Self-service flow, now admin-only per FR-011-306 | Same grep — the helper symbol is in the NFR-011-001 regex |

> The identifier names that USED to live in each row above are
> documented in `specs/011-zero-email-deployment/spec.md` §Removal
> Plan §settings (the spec/* tree is the only place the deleted names
> may legally appear — that scope exclusion is hard-coded into the
> NFR-011-001 guard). Operators rotating an existing deployment can
> grep the spec for the names they need to look up in their secrets
> store, then delete the corresponding entries.

### Verification command

```bash
# From the repo root.
docker exec echoroo-backend sh -c \
  'cd /app && /opt/venv/bin/python -m pytest --no-cov \
   apps/api/tests/contract/test_no_email_subsystem_traces.py -v'
```

Expected: **passed** (0 violations).

### CI / Actions secrets audit

GitHub Actions secrets (organisation + repository scope) MUST be
manually audited via:

```
Settings → Secrets and variables → Actions
```

Delete any of the entries in the role table above. The Echoroo
workflows under `.github/workflows/` reference only
`secrets.GITHUB_TOKEN` post-spec/011 — anything else mail-related is
dead code in your secrets vault.

---

## 2. Secrets to ROTATE on the spec/011 schedule

These secrets remain ACTIVE post-spec/011 and have dedicated rotation
runbooks. List them here so an operator can see the full inventory at
a glance.

| Env var | Purpose | Rotation runbook | Default rotation cadence |
|---|---|---|---|
| `INVITATION_TOKEN_HMAC_KEY` / `_OLD` | Sign 4-part invitation envelope MAC | `invitation_token_kid_rotation.md` | Annually OR on suspected compromise |
| `INVITATION_TOKEN_KID_NEW` / `_OLD` | Kid stamp + dual-verify routing | Same | Same |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY` / `_OLD` | Sign 2FA reset confirmation token (Phase 17 A-12) | `two_factor_confirmation_key_rotation.md` | Annually |
| `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW` / `_OLD` | Kid stamp + dual-verify routing | Same | Same |
| `AWS_KMS_CMK_PII_HASH_ALIAS` (+ `_V2` for rotation) | PII-hash KMS CMK | `cmk_rotation.md` | KMS-managed (annual auto-rotate) + manual `_V2` dual-key when re-keying |
| `AWS_KMS_CMK_2FA_DEK_ALIAS_NEW` / `_OLD` | 2FA secret DEK envelope encryption | `cmk_rotation.md` + `dek_rewrap.md` | Annually + on key compromise |
| `JWT_SECRET_KEY` | API session JWT signing key | Manual (no automated runbook yet) | Annually (downtime: in-flight sessions invalidated) |
| `web_session_secret` (`WEB_SESSION_SECRET`) | Web session cookie + step-up token signing key | Manual | Annually |

### Strength requirements (prod / staging)

The `Settings.validate_production_secrets` model_validator enforces:

- `JWT_SECRET_KEY` ≥ 32 chars and not in the weak-defaults list.
- `web_session_secret` ≥ 32 chars and not equal to
  `"dev-web-session-secret-change-in-production"`.
- `INVITATION_TOKEN_HMAC_KEY` ≥ 32 chars (prod/staging only).
- `INVITATION_TOKEN_HMAC_KEY_OLD` ≥ 32 chars when set.
- `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY` ≥ 32 chars (prod/staging
  only).
- `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD` ≥ 32 chars when set.

A boot with any weaker value is rejected before the FastAPI app
finishes constructing.

---

## 3. Sentry / telemetry secret (optional, spec/011 T710)

| Env var | Purpose | Lifecycle |
|---|---|---|
| `SENTRY_DSN` | Sentry SDK DSN for out-of-process telemetry | Optional. Unset → telemetry disabled (zero-email default). Set → `apps/api/echoroo/observability/sentry.py::init_sentry` installs the spec/011 redaction `before_send` hook. |
| `SENTRY_RELEASE` | Sentry release tag for filtering events by deploy | Optional. Defaults to `APP_VERSION`. |

**Rotation**: rotate `SENTRY_DSN` whenever the upstream Sentry project
is recreated or the project's auth token is rotated. The DSN itself is
not a secret per se (it identifies the project endpoint) but treat it
as one for hygiene.

**Verification that redaction is wired**:

```bash
docker exec echoroo-backend sh -c \
  'cd /app && /opt/venv/bin/python -m pytest --no-cov \
   apps/api/tests/security/test_telemetry_scrubs_sensitive_fields.py -v'
```

Expected: every assertion passes — the four `SENSITIVE_FIELDS` plus
the registered sensitive request / response headers (including
`x-step-up-token`, `authorization`, `cookie`, `set-cookie`, and
`x-csrf-token`) are scrubbed across both the Sentry hook and the
structured-log filter.

---

## 4. CI / GitHub Actions secrets list (current)

After spec/011 the canonical list of Actions secrets referenced by
`.github/workflows/` is:

| Secret | Workflow | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | `publish_docker.yml`, `ci.yml`, others | Auto-provisioned by GitHub Actions; used for GHCR push, CI artifact upload |

No other secret is referenced. If your operator runbook tells you to
configure a transactional-mail provider key or a `From:` envelope
sender value as an Actions secret, the runbook is stale — delete that
step.

Note: `permissions-fixture-drift.yml` is a workflow whose job exists
solely to detect drift in the permission fixture artifact and does
not consume any custom secret.

---

## 5. Container env vars to remove from `compose.dev.yaml` / `.env.example`

spec/011 Step 10 cleaned `compose.dev.yaml` + `.env.example` of every
email-subsystem reference (verified by the NFR-011-001 grep). If you
maintain a local override (`compose.override.yaml` / `.env.local`),
audit and remove:

- Any mail-provider API-key, sender-envelope, or verification-token
  cap definition
- Any SMTP relay configuration (host / port / user / password)
- Any dev-only mail-catcher service definition and the associated
  volume / port mapping

After removal:

```bash
docker compose -f compose.dev.yaml ps
# Should show only echoroo-* containers — no mail-catcher container.
```

---

## 6. Operational rotation calendar (recommended)

| Frequency | Tasks |
|---|---|
| **On suspected compromise** | Emergency rotate the affected key (see per-key runbook); revoke outstanding artifacts; forensic sweep |
| **Quarterly** | Run `test_no_email_subsystem_traces.py` to catch any drift; review Sentry redaction test; audit GitHub Actions secrets |
| **Annually** | Rotate `INVITATION_TOKEN_HMAC_KEY` (planned); rotate `TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY`; rotate `JWT_SECRET_KEY` (during a maintenance window — in-flight sessions invalidated); rotate `web_session_secret` (same caveat) |
| **KMS-managed** | `AWS_KMS_CMK_PII_HASH_ALIAS` and `AWS_KMS_CMK_2FA_DEK_ALIAS_NEW` auto-rotate via AWS KMS annual rotation; trigger a dual-key window via `_V2` / `_OLD` slot if you re-key under operator control |

---

## 7. Spec references

- spec/011 §Removal Plan §settings — full deleted-secret inventory
  (the only document in the repo permitted to spell out the deleted
  identifier names verbatim)
- spec/011 §NFR-011-001 — CI grep guard
- spec/011 §NFR-011-010 — invitation token kid rotation pattern
- spec/011 §FR-011-206 — step-up token / `web_session_secret`
  rotation policy
- Phase 17 A-2 — PII hash key dual-write rotation
- Phase 17 A-8 — DEK rewrap + KMS isolation
- Phase 17 A-12 — env-driven kid rotation pattern (the canonical
  template followed by spec/011)
