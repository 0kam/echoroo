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
| B-2 (upload EXIF + file metadata) | DONE | #33 (`c31f02dd`) |
| §C-0 .. §C-7 (CI burn-down) | DONE | merged (#25, #26, #27, #28, #29, #30, #31) |
| §C residual (PR-A / PR-C / PR-D) | OPEN | #34, #35, #36 (CI green pending) |

After #34, #35, #36 merge the only remaining backlog items are
`continue-on-error` removal (D), runbook E2E (E), and the FR-011a
traceability orphan (F). None of those are user-facing release
blockers.

## Live-infrastructure provisioning (HUMAN ACTION REQUIRED)

The application code reads every external dependency from environment
variables; provisioning the actual resources is **not** automated. This is the
step that requires real deployment access and operator decisions.

### 1. Local keyring

Provision the file-backed keyring before starting the API or workers. Follow
[docs/runbook/keyring.md](keyring.md) for the admin service commands, file
permissions, selectors, activation barrier, offline backup, and rotation
procedures.

- Create the ring outside the application storage tree and select one key for
  TOTP wrapping, one for PII HMACs, and one for the audit chain.
- Copy the whole keyring file and selector configuration to the maintainer's
  offline password manager before activating it. Never store that copy with a
  database or storage backup.
- Exclude `/etc/echoroo` from file-level and VM backups, and confirm the host
  snapshot policy does not capture the keyring unexpectedly.
- Recreate `backend`, `worker`, and `worker-cpu`, then run
  `keyring_activation_check --expected-workers N` before opening traffic.

### 2. PostgreSQL (managed RDS or equivalent)

- PostgreSQL **16+** with the `pgvector` extension installed.
  CI uses `pgvector/pgvector:pg16` for parity.
- Application role `echoroo_app` with `LOGIN`, full table /
  sequence privileges. The DDL trigger
  `prevent_last_superuser_deletion` (alembic 0013) gates against
  this role specifically.
- Backup policy: at minimum point-in-time recovery for 30 days. The keyring
  runbook requires a recent database and storage snapshot before a TOTP
  rewrap.
- `DATABASE_URL` in deployment env is `postgresql+asyncpg://...`.

### 3. Redis (managed ElastiCache or equivalent)

- Redis 7+ with TLS (the dev compose stack uses self-signed certs in
  `config/redis/tls/`; production should use AWS-managed certs).
- Used for rate limiting, Celery broker, and 2FA failure counters.
- `REDIS_URL` in deployment env.

### 4. Lustre storage tree (recordings + audit log archive)

- Mount the production Lustre filesystem on the host. Use
  `/lustre/echoroo/storage` as the documented example host directory and
  bind-mount it as `/data/storage` for `STORAGE_ROOT` in the API and every
  worker. The host directory must be owned by UID/GID 1000 with mode `0750`.
- From the deployment host, run the provisioner inside the backend container
  so it runs as UID/GID 1000 against the mounted path and performs the full
  readiness probe:

  ```bash
  docker compose -f compose.dev.yaml run --rm backend uv run python -m \
    echoroo.scripts.provision_storage /data/storage
  ```

  The provisioner creates `.echoroo-storage` and runs `ensure_ready(full=True)`
  on the Lustre mount, including the atomic publication checks. Do this before
  the first API or worker start and after any mount replacement.
- The weekly audit log export writes write-once files under
  `STORAGE_ROOT/audit-log/`; operational immutability is covered by the
  [audit log archive runbook](audit_log_archive.md).

### 5. Email — removed (spec/011 zero-email deployment)

Echoroo no longer ships an outbound-email integration. Self-service
account recovery is replaced by admin-mediated flows; collaborator
onboarding uses invitation URLs handed off out-of-band by the issuing
admin. No transactional-email infrastructure is required for
production deployment (see `specs/011-zero-email-deployment/spec.md`).

### 5a. Trusted-device rollout gates

These flags default off and should be enabled in order:

1. Deploy schema, services, workers, and UI with
   `TRUSTED_DEVICE_REGISTRATION_ENABLED=false` and
   `TRUSTED_DEVICE_BYPASS_ENABLED=false`.
2. Enable trusted-device registration only after cookie attributes,
   hash-only storage, list/revoke, and five-device cap checks pass.
3. Enable trusted-device bypass only after admin no-bypass, revocation,
   and high-risk step-up checks pass.

Operational references:
[docs/runbook/trusted_devices.md](trusted_devices.md).

### 6. JWT secret + web session secret

- 32+ char strong random values per environment.
- `JWT_SECRET_KEY` (refresh token signing) and `web_session_secret`
  (HMAC of the cookie session). Rotate together; the validator in
  `core/settings.py::validate_production_secrets` rejects defaults /
  short values when `ENVIRONMENT=production`.

### 7. DNS + TLS

- Public hostname for the API (`api.echoroo.app` or equivalent).
- ACM cert (or Let's Encrypt via the reverse proxy) terminating TLS
  at the load balancer.
- Reverse proxy adds the standard security headers (HSTS, X-Frame-
  Options, etc.). The application is hardened to assume TLS upstream
  of the worker pods.

### 8. Monitoring / alerting

- CloudWatch (or Grafana) board for:
  - request latency p95 (`tests/performance/test_auth_permission_p95.py`
    pins the target)
  - audit log write throughput (chain-hash advisory lock contention)
  - keyring load and activation failures (a mismatch usually means a
    selector or rotation configuration error — see `docs/runbook/keyring.md`)
  - Celery queue depth (worker / worker-cpu queues)
- Alert on:
  - any 5xx > 1% sustained
  - audit log advisory-lock timeout
  - 2FA reset queue stalled (> 24h dispatch delay = the runbook in
    `apps/api/echoroo/services/two_factor_reset_service.py` is
    designed around this SLA)
  - trusted-device bypass rejection spike by normalized reason
  <!-- spec/011 Step 10 (zero-email deployment): the legacy
       verification-email outbox + provider-bounce alerts were removed
       alongside the deleted email subsystem (FR-011-001..010). -->


### 9. Bootstrap

- Apply the current migration set with `./echoroo.sh migrate`. Then compare
  the output of these commands; the current revision must equal the head
  reported by the second command:

  ```bash
  docker compose -f compose.dev.yaml exec -T backend uv run alembic current
  docker compose -f compose.dev.yaml exec -T backend uv run alembic heads
  ```

  Do not require revision `0001` here. That is the wipe guard's baseline,
  while a normally migrated deployment is at the current head (currently
  `0038` in this repository).
- Only after the migrations are at head, run
  `python -m echoroo.scripts.init_superuser --confirm` in the API container
  against the production DB to seed the first superuser. The command writes a
  TOTP DEK under the selected keyring key.
- Verify both bootstrap rows and the signed audit history with the shared
  verifier:

  ```bash
  docker compose -f compose.dev.yaml exec -T backend \
    uv run python -m echoroo.scripts.verify_audit_chain \
    --table both --check-detects-deleted-row
  ```

  Require exit `0`; exit `1` means the chain is invalid or verification could
  not complete, including an unavailable audit key. The deletion probe is
  skipped (still exit `0`) for a table with fewer than three rows, and a chain
  holding only bootstrap rows verifies without using the audit key, so run this
  after the superuser bootstrap has written signed rows.

### Wipe-only guard (not a release gate)

The actual wipe checker is the module
`python -m echoroo.scripts.check_wipe_guard`. It is only for the destructive
wipe ritual, and its Alembic check is intentionally hard-coded to baseline
revision `0001`; do not use its exit `0` as evidence that a normally migrated
database is current.

Its CLI exit codes are:

- `0` — the checker passed its wipe-state checks.
- `10` — a `wipe_guard` row already exists.
- `11` — `alembic_version` is not `0001`.
- `12` — `audit-log/genesis/marker.json` is missing or incorrect.
- `20` — settings, database, or storage infrastructure error.

## CI / observability hardening (NOT release-blocking)

These improve operational quality but do not block first launch:

- **D-Mutation testing**: PHASE17_BACKLOG §D — promote `mutmut` from
  PR-label trigger to every-push, raise score to ≥ 80% on the 11
  permission-critical modules.
- **E-Runbook E2E**: PHASE17_BACKLOG §E — provision a CI job that
  boots the live compose stack and runs `wipe_database` / `init_iucn_sync`
  / `seed_moe_rdb` end-to-end against real storage / IUCN dependencies.
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
5. Schedule the first keyring rotation review at +30d (the keyring runbook
   defines the maintenance-window and offline-backup procedure).

---

This document is the **only** thing standing between the codebase and
launch as of 2026-05-07. Each numbered item under "Live-infrastructure
provisioning" is a human task that should be reviewed and stamped by
the release driver before tag.
