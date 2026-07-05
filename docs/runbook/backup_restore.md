# Backup & Restore Runbook

**Created**: 2026-07-06 (W5-6 operational readiness)
**Status**: pre-launch — development / evaluation stack
**Owner**: release driver (human action required for every item below)

This runbook covers backing up and restoring the three stateful stores in
the Echoroo stack: **PostgreSQL** (all relational data), **S3 / object
storage** (audio recordings), and the **KMS key material** that those two
depend on. Redis is covered last because it is (almost entirely) ephemeral.

It is grounded in the shipped development stack (`compose.dev.yaml`):

| Store | Service / container | Image | Volume | Notes |
|-------|--------------------|-------|--------|-------|
| PostgreSQL | `echoroo-db` | `pgvector/pgvector:pg16` | `echoroo-dev-db` | pgvector enabled |
| Object storage | `echoroo-localstack` | LocalStack (S3 + KMS) | `./.data/localstack` (`ECHOROO_LOCALSTACK_DATA`) | bucket `echoroo` |
| Redis | `echoroo-redis` | `redis:7-alpine` | `echoroo-dev-redis` | TLS + AUTH + ACL |

> **The three stores are NOT independent.** A Postgres snapshot taken at
> time *T* is only restorable together with the S3 objects and the **KMS
> key material** that existed at *T*. Read the "KMS caveat" section before
> planning any restore — restoring Postgres alone will silently break 2FA,
> audit-chain verification, and invitation tokens.

---

## 1. PostgreSQL

All relational data lives in the `echoroo` database on the `echoroo-db`
container: users, projects, datasets, recordings metadata, annotations,
detections, embeddings (pgvector), audit log, and the **wrapped TOTP DEKs**
(encrypted per-user 2FA secrets — see the KMS caveat).

Defaults come from `.env`: `POSTGRES_USER` (default `postgres`),
`POSTGRES_DB` (default `echoroo`), `POSTGRES_PASSWORD` (required).

### Backup — `pg_dump`

Custom format (`-Fc`) is preferred: it is compressed and restores with
`pg_restore` (parallelism, selective restore).

```bash
# Dump to a file on the host (custom format, compressed).
docker exec -t echoroo-db \
  pg_dump -U postgres -d echoroo -Fc \
  > "echoroo-$(date +%F_%H%M%S).dump"
```

Plain-SQL alternative (human-readable, restore with `psql`):

```bash
docker exec -t echoroo-db \
  pg_dump -U postgres -d echoroo --no-owner --no-privileges \
  | gzip > "echoroo-$(date +%F_%H%M%S).sql.gz"
```

### Restore — `pg_restore`

Restore into a **fresh** database. The `pgvector` extension is created by
`scripts/init-db.sql` on first container init; if you restore into a
manually-created DB, run `CREATE EXTENSION IF NOT EXISTS vector;` first.

```bash
# Copy the dump into the container, then restore (drops + recreates objects).
docker cp echoroo-2026-07-06_120000.dump echoroo-db:/tmp/restore.dump
docker exec -t echoroo-db \
  pg_restore -U postgres -d echoroo --clean --if-exists --no-owner \
  /tmp/restore.dump
docker exec -t echoroo-db rm -f /tmp/restore.dump
```

Plain-SQL restore:

```bash
gunzip -c echoroo-2026-07-06_120000.sql.gz \
  | docker exec -i echoroo-db psql -U postgres -d echoroo
```

### Cron example

Nightly dump at 02:30, retaining 14 days, on the Docker host:

```cron
# /etc/cron.d/echoroo-pg-backup
30 2 * * * root docker exec -t echoroo-db pg_dump -U postgres -d echoroo -Fc > /var/backups/echoroo/pg-$(date +\%F).dump 2>>/var/log/echoroo-backup.log && find /var/backups/echoroo -name 'pg-*.dump' -mtime +14 -delete
```

Store backups off-host (they contain PII and wrapped secrets). Encrypt at
rest.

---

## 2. S3 / object storage (audio recordings)

### What lives in S3

Uploaded audio is stored in S3, **not** on the local filesystem. Each
recording's `path` column in Postgres is the S3 object key, shaped as:

```
recordings/{project_id}/{dataset_id}/{recording_id}.wav
```

In the dev stack this is LocalStack bucket `echoroo` at
`http://localhost:4566`. `AudioService.ensure_file_local()` lazily
downloads objects from S3 to a local cache; the cache is **derived** and
does not need backing up — only the bucket does.

### Backup — `aws s3 sync`

Point the AWS CLI at the configured endpoint. Dev credentials are
`echoroo` / `echoroo-dev` (`S3_ACCESS_KEY` / `S3_SECRET_KEY`); real AWS
uses your IAM credentials and drops `--endpoint-url`.

```bash
AWS_ACCESS_KEY_ID=echoroo AWS_SECRET_ACCESS_KEY=echoroo-dev \
aws --endpoint-url http://localhost:4566 \
  s3 sync s3://echoroo ./backup/s3/echoroo
```

Alternatively, back up the LocalStack persistence volume directly
(`PERSISTENCE=1` writes to `./.data/localstack`, overridable via
`ECHOROO_LOCALSTACK_DATA`). **Important:** that same directory also holds
the LocalStack **KMS** key material — backing it up as a whole unit keeps
S3 objects and KMS keys consistent (see caveat). Stop LocalStack or quiesce
writes before copying the volume to get a consistent snapshot.

### Restore

```bash
AWS_ACCESS_KEY_ID=echoroo AWS_SECRET_ACCESS_KEY=echoroo-dev \
aws --endpoint-url http://localhost:4566 \
  s3 sync ./backup/s3/echoroo s3://echoroo
```

The bucket is created idempotently by `scripts/init-localstack.sh` on
LocalStack boot; create it manually (`aws s3 mb s3://echoroo`) if restoring
into a fresh instance before the init hook runs.

For real AWS S3, prefer **bucket versioning** + lifecycle rules and/or
cross-region replication over ad-hoc syncs.

---

## 3. KMS key material — read this before restoring (CRITICAL)

Encryption is wired through **envelope encryption backed by KMS**. Four
isolated CMKs are provisioned by `scripts/init-localstack.sh`:

- `alias/echoroo-totp-dek` — wraps each user's TOTP **data encryption key
  (DEK)**. The *wrapped* DEK is stored in **Postgres**; the *unwrapping
  key* lives only in KMS.
- `alias/echoroo-pii-hash-hmac` — keyed HMAC for PII hashing.
- `alias/echoroo-audit-chain-hmac` — keyed HMAC for audit-log tamper chain.
- `alias/echoroo-invitation-hmac` — signs invitation tokens.

**Why this matters for restore:** Postgres holds ciphertext (wrapped TOTP
DEKs, PII hashes, audit-chain MACs) that can only be decrypted / verified
with the **same** KMS key material that was live when the data was written.

> **If the KMS keys are lost or re-created, a Postgres restore is
> useless for the encrypted columns:**
> - Every user's TOTP secret becomes undecryptable → **2FA breaks for
>   everyone** (and 2FA is mandatory).
> - The audit-log chain no longer verifies.
> - Invitation tokens signed under the old key fail validation.

In dev, LocalStack re-runs `init-localstack.sh` on a fresh volume and
creates **brand-new CMKs with new key IDs** — these cannot decrypt data
written under the previous keys. This exact failure happened once when the
LocalStack KMS DEKs were wiped and took the whole app down. Therefore:

- **Back up the LocalStack KMS material together with Postgres and S3**, as
  one consistent set. It lives in the same `./.data/localstack`
  (`ECHOROO_LOCALSTACK_DATA`) volume as the S3 objects.
- **Never wipe `./.data/localstack` without a matching Postgres reset.**
- In **production**, use real AWS KMS: the CMKs are managed AWS resources
  and survive a Postgres restore automatically. Guard them with deletion
  protection and a strict key policy; do NOT schedule key deletion. Key
  rotation is handled by the dedicated runbooks
  (`docs/runbook/cmk_rotation.md`, `docs/runbook/dek_rewrap.md`) — do not
  improvise it during a restore.

---

## 4. Redis — mostly ephemeral

Redis (`echoroo-redis`, volume `echoroo-dev-redis`) is used for:

- **Rate-limit counters** — ephemeral, self-heal.
- **Login backoff / attempt state** — ephemeral (in-memory recorder in dev;
  restarting the backend clears it).
- **Celery broker + result backend** (DBs 0 and 1) — in-flight task queue
  and results. Losing these drops queued/running background jobs; they are
  not a durable system of record.
- **Session material** handed out to clients.

**Nothing in Redis is a system of record.** A restore does **not** require
Redis backup. Accept that:

- In-flight Celery jobs at the moment of failure are lost and must be
  re-triggered (uploads, imports, taxon sync, classifier training).
- Active user sessions are dropped; users log in again.

Do **not** run `redis-cli FLUSHALL` as an operational step — it destroys
sessions and live Celery data with no benefit. If you must reset Redis,
restart the `echoroo-redis` service and let clients reconnect.

---

## 5. Restore verification checklist

After a restore, verify the full path end-to-end (do not stop at "the
container is up"):

1. **App boots** — `./echoroo.sh status` shows `echoroo-backend` healthy;
   `curl -s http://localhost:8002/health` returns `{"status":"healthy"}`
   and `curl -s http://localhost:8002/health/ready` returns HTTP 200 with
   every dependency `"ok"`.
2. **Migrations current** — `./echoroo.sh migrate` reports no pending
   revisions (schema matches code).
3. **Login works (exercises KMS)** — log in with a real 2FA account in the
   browser. A successful TOTP challenge proves the wrapped TOTP DEK
   decrypted against the restored KMS key material. If login fails at the
   2FA step, the KMS keys and Postgres are out of sync (see §3).
4. **A recording plays (exercises S3)** — open a project, open a recording,
   confirm audio streams and the spectrogram renders. This proves the S3
   object key in Postgres resolves to a real object in the restored bucket.
5. **Audit chain verifies** — perform one audited action (e.g. an
   annotation) and confirm it is written without a chain error, proving the
   audit-chain HMAC key restored correctly.

If steps 3–5 fail while step 1 passes, the most likely cause is a
Postgres / S3 / KMS snapshot mismatch — restore all three from the **same
point in time**.

---

## Related runbooks

- `docs/runbook/release_readiness.md` — pre-launch provisioning checklist.
- `docs/runbook/cmk_rotation.md` — rotating the KMS CMKs.
- `docs/runbook/dek_rewrap.md` — re-wrapping DEKs after key rotation.
- `CONFIGURATION.md` — environment variable reference.
