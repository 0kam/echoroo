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

## 1. Secrets to DELETE after spec/011 cutover

The following secrets / env vars existed pre-spec/011 and MUST be
removed from every secrets store (CI / Actions secrets, container env,
K8s Secret, vault) by the end of the cutover window. Failure to delete
leaves a credential at rest that has zero remaining call-sites and is
therefore impossible to revoke through normal "log out" channels.

| Env var / secret name | Pre-spec/011 owner | Removal verification |
|---|---|---|
| `RESEND_API_KEY` | Outbound transactional email (now removed) | `apps/api/echoroo/core/settings.py` has zero references; `apps/api/tests/contract/test_no_email_subsystem_traces.py` greps the codebase and asserts 0 matches |
| `RESEND_*` (any other `RESEND_` prefixed var) | Resend SDK config | Same grep |
| `EMAIL_FROM` | Outbound `From:` header | Same grep |
| `EMAIL_VERIFICATION_*` (any variant — `RESEND_ACTIVE_TOKEN_CAP`, etc.) | Email verification token issuance / rate-limit caps | Same grep |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` | Generic SMTP relay fallback (never actually wired) | Same grep |
| `MAILPIT_*` (any variant) | Dev-only Mailpit catcher container | Same grep + `docker compose ps` should show no Mailpit container |
| `2FA_RESET_MAGIC_LINK_*` (any variant) | Self-service 2FA reset via magic link (now admin-only per FR-011-306) | Same grep — `send_2fa_reset_magic_link` is in the NFR-011-001 regex |

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

Delete any of the names in the table above. The Echoroo workflows
under `.github/workflows/` reference only `secrets.GITHUB_TOKEN`
post-spec/011 — anything else email-related is dead code in your
secrets vault.

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

Expected: **17 passed** (the four `SENSITIVE_FIELDS` + the
`x-step-up-token` header are scrubbed across Sentry hook + structured-
log filter).

---

## 4. CI / GitHub Actions secrets list (current)

After spec/011 the canonical list of Actions secrets referenced by
`.github/workflows/` is:

| Secret | Workflow | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | `publish_docker.yml`, `ci.yml`, others | Auto-provisioned by GitHub Actions; used for GHCR push, CI artifact upload |

No other secret is referenced. If your operator runbook tells you to
configure `RESEND_API_KEY` or `EMAIL_FROM` as Actions secrets, the
runbook is stale — delete that step.

Note: `permissions-fixture-drift.yml` is a workflow whose job exists
solely to detect drift in the permission fixture artifact and does
not consume any custom secret.

---

## 5. Container env vars to remove from `compose.dev.yaml` / `.env.example`

spec/011 Step 10 cleaned `compose.dev.yaml` + `.env.example` of every
email-subsystem reference (verified by the NFR-011-001 grep). If you
maintain a local override (`compose.override.yaml` / `.env.local`),
audit and remove:

- Any `RESEND_*`, `SMTP_*`, `MAILPIT_*`, `EMAIL_*` definition
- Any `mailpit` service definition
- Any Mailpit volume / port mapping

After removal:

```bash
docker compose -f compose.dev.yaml ps
# Should show only echoroo-* containers — no mailpit container.
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
- spec/011 §NFR-011-001 — CI grep guard
- spec/011 §NFR-011-010 — invitation token kid rotation pattern
- spec/011 §FR-011-206 — step-up token / `web_session_secret`
  rotation policy
- Phase 17 A-2 — PII hash key dual-write rotation
- Phase 17 A-8 — DEK rewrap + KMS isolation
- Phase 17 A-12 — env-driven kid rotation pattern (the canonical
  template followed by spec/011)
