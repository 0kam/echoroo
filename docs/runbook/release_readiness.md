# Release Readiness Checklist

**Created**: 2026-05-07 (Phase 17 §C close)
**Status**: pre-launch — no external users yet
**Owner**: release driver (human action required for every item below)

This document is the operator-facing checklist that must be completed
before the first production release. Every item requires real
credentials, cost decisions, or a human-in-the-loop call that an
agent cannot make autonomously. The codebase itself is release-ready
as of main `c31f02dd` + the open follow-up PRs.

## Code-side release blocker status

The Phase 17 backlog tracked the security-implementation residuals.
As of 2026-05-07 every release-blocker has merged or is in flight:

| Backlog | Status | PR / commit |
|---------|--------|-------------|
| A-1 .. A-13 | DONE | merged in earlier batches |
| B-1 (response filter) | DONE | #32 (`17645e9f`) |
| B-2 (upload EXIF + S3 metadata) | DONE | #33 (`c31f02dd`) |
| §C-0 .. §C-7 (CI burn-down) | DONE | merged (#25, #26, #27, #28, #29, #30, #31) |
| §C residual (PR-A / PR-C / PR-D) | OPEN | #34, #35, #36 (CI green pending) |

After #34, #35, #36 merge the only remaining backlog items are
`continue-on-error` removal (D), runbook E2E (E), and the FR-011a
traceability orphan (F). None of those are user-facing release
blockers.

## Live-infrastructure provisioning (HUMAN ACTION REQUIRED)

The application code reads every external dependency from environment
variables; provisioning the actual resources is **not** automated.
This is the step that requires real cost decisions and AWS / DNS
access.

### 1. AWS KMS — four CMKs

The application requires four distinct CMKs (alias-isolated per
`scripts/lint_kms_isolation.py` strict mode). All in the same region.

- `alias/echoroo-totp-dek` — `KeyUsage=ENCRYPT_DECRYPT`,
  `KeySpec=SYMMETRIC_DEFAULT`. Wraps each user's TOTP DEK.
- `alias/echoroo-pii-hash-hmac` — `KeyUsage=GENERATE_VERIFY_MAC`,
  `KeySpec=HMAC_256`. Keyed PII hash for audit lookups (FR-091a/b).
- `alias/echoroo-audit-chain-hmac` — `KeyUsage=GENERATE_VERIFY_MAC`,
  `KeySpec=HMAC_256`. Hash chain for project / platform audit tables.
- `alias/echoroo-invitation-hmac` — `KeyUsage=GENERATE_VERIFY_MAC`,
  `KeySpec=HMAC_256`. Token signing for project invitations and the
  2FA reset confirmation flow.

Rotation runbooks already exist:
[docs/runbook/cmk_rotation.md](cmk_rotation.md),
[docs/runbook/dek_rewrap.md](dek_rewrap.md),
[docs/runbook/two_factor_confirmation_key_rotation.md](two_factor_confirmation_key_rotation.md).

Wire the alias names into the deployment env via
`AWS_KMS_CMK_2FA_ALIAS`, `AWS_KMS_CMK_PII_HASH_ALIAS`,
`AWS_KMS_CMK_AUDIT_CHAIN_ALIAS`,
`AWS_KMS_CMK_INVITATION_HMAC_ALIAS`. Rotation-grace pairs
(`*_NEW` / `*_OLD`) are runtime-only; leave unset until a rotation
window opens.

### 2. PostgreSQL (managed RDS or equivalent)

- PostgreSQL **16+** with the `pgvector` extension installed.
  CI uses `pgvector/pgvector:pg16` for parity.
- Application role `echoroo_app` with `LOGIN`, full table /
  sequence privileges. The DDL trigger
  `prevent_last_superuser_deletion` (alembic 0013) gates against
  this role specifically.
- Backup policy: at minimum point-in-time recovery for 30 days.
  The DEK rewrap runbook explicitly assumes a recent snapshot exists
  before rotating CMKs.
- `DATABASE_URL` in deployment env is `postgresql+asyncpg://...`.

### 3. Redis (managed ElastiCache or equivalent)

- Redis 7+ with TLS (the dev compose stack uses self-signed certs in
  `config/redis/tls/`; production should use AWS-managed certs).
- Used for rate limiting, Celery broker, and 2FA failure counters.
- `REDIS_URL` in deployment env.

### 4. S3 bucket (uploads + audit log archive)

- One bucket for audio uploads. CORS configured for the production
  origin. Object lifecycle policy aligned with the project / dataset
  retention contract.
- One bucket (or prefix) with **Object Lock** enabled in
  governance/compliance mode for the audit log export
  (`workers/audit_log_export.py`).
- IAM role: PutObject / GetObject / DeleteObject on the upload
  bucket; PutObject (with Object Lock) on the audit bucket.
- Wire via `S3_BUCKET`, `S3_PUBLIC_ENDPOINT_URL` (presigned URL
  base), `S3_AUDIT_BUCKET`.

### 5. Email — Resend

- Resend API key with the production domain verified.
- `RESEND_API_KEY` in deployment env.
- The `services/email.py` wrapper logs failures but does NOT
  re-raise — verify a sample reset-password / 2FA-reset email
  reaches the inbox before opening signups.

### 6. Turnstile (Cloudflare CAPTCHA)

- Turnstile site + secret keys for the production hostname.
- `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY`. Dev uses the
  Cloudflare always-pass test keys (`1x...AA`); production needs
  real keys.

### 7. JWT secret + web session secret

- 32+ char strong random values per environment.
- `JWT_SECRET_KEY` (refresh token signing) and `web_session_secret`
  (HMAC of the cookie session). Rotate together; the validator in
  `core/settings.py::validate_production_secrets` rejects defaults /
  short values when `ENVIRONMENT=production`.

### 8. DNS + TLS

- Public hostname for the API (`api.echoroo.app` or equivalent).
- ACM cert (or Let's Encrypt via the reverse proxy) terminating TLS
  at the load balancer.
- Reverse proxy adds the standard security headers (HSTS, X-Frame-
  Options, etc.). The application is hardened to assume TLS upstream
  of the worker pods.

### 9. Monitoring / alerting

- CloudWatch (or Grafana) board for:
  - request latency p95 (`tests/performance/test_auth_permission_p95.py`
    pins the target)
  - audit log write throughput (chain-hash advisory lock contention)
  - KMS error rate per CMK (a spike here usually means a rotation
    misconfig — see `docs/runbook/cmk_rotation.md`)
  - Celery queue depth (worker / worker-cpu queues)
- Alert on:
  - any 5xx > 1% sustained
  - audit log advisory-lock timeout
  - 2FA reset queue stalled (> 24h dispatch delay = the runbook in
    `apps/api/echoroo/services/two_factor_reset_service.py` is
    designed around this SLA)

### 10. Bootstrap

- Run `apps/api/echoroo/scripts/init_superuser.py` against the
  production DB to seed the first superuser. The script is
  idempotent and writes a TOTP DEK under the live KMS alias.
- Verify `scripts/check_wipe_guard.py` returns exit 0 (clear for
  wipe) — exit 1 means the genesis rows are present and a wipe was
  performed; exit > 1 is a misconfig (e.g., missing AWS creds).

## CI / observability hardening (NOT release-blocking)

These improve operational quality but do not block first launch:

- **D-Mutation testing**: PHASE17_BACKLOG §D — promote `mutmut` from
  PR-label trigger to every-push, raise score to ≥ 80% on the 11
  permission-critical modules.
- **E-Runbook E2E**: PHASE17_BACKLOG §E — provision a CI job that
  boots the live compose stack and runs `wipe_database` / `init_iucn_sync`
  / `seed_moe_rdb` end-to-end against real KMS / S3 / IUCN.
- **F-Traceability orphan**: PHASE17_BACKLOG §F — decide whether
  FR-011a is retired or renamed; trace doc currently has 1 orphan.
- **Hard gate promotion**: once the 5-test residual cluster lands
  (PR-A/C/D) and CI is green for ~3 sequential merges, remove
  `continue-on-error: true` from the `backend-tests` and
  `security-tests` jobs in `.github/workflows/ci.yml`.

## Release ritual

1. Tag main at the chosen commit (`git tag -s v0.1.0 -m "..."`).
2. Verify the migration head matches `alembic heads` against the
   target DB; run `alembic upgrade head` from the worker host.
3. Smoke-test login → 2FA enroll → file upload → search end-to-end
   through the production hostname.
4. Open signups (toggle `restricted_config.allow_*` per project as
   needed; the platform-level signup gate lives in the auth router
   and is `True` by default in production env).
5. Schedule a rotation window for each CMK at +30d (the rotation
   runbooks bake the calendar reminder into their checklist
   templates).

---

This document is the **only** thing standing between the codebase and
launch as of 2026-05-07. Each numbered item under "Live-infrastructure
provisioning" is a human task that should be reviewed and stamped by
the release driver before tag.
