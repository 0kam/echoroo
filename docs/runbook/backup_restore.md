# Backup & Restore Runbook

**Created**: 2026-07-06 (W5-6 operational readiness)
**Status**: pre-launch — development / evaluation stack
**Owner**: release driver (human action required for every item below)

This runbook covers backing up and restoring the stateful stores in the
Echoroo stack: **PostgreSQL** (all relational data), the **POSIX storage tree**
(recordings and artifacts), and the **KMS key material** those two depend on.
Redis is covered last because it is (almost entirely) ephemeral.

It is grounded in the shipped development stack (`compose.dev.yaml`):

| Store | Service / container | Image | Volume / path | Notes |
|-------|--------------------|-------|--------|-------|
| PostgreSQL | `echoroo-db` | `pgvector/pgvector:pg16` | `echoroo-dev-db` | pgvector enabled |
| POSIX storage | API + workers | Echoroo containers | Lustre host path → `/data/storage` | `STORAGE_ROOT`; recordings and artifacts |
| KMS | `echoroo-localstack` (dev) | LocalStack KMS | `./.data/localstack` (`ECHOROO_LOCALSTACK_DATA`) | AWS KMS in production |
| Redis | `echoroo-redis` | `redis:7-alpine` | `echoroo-dev-redis` | TLS + AUTH + ACL |

> **The durable stores are NOT independent.** A Postgres snapshot taken at
> time *T* is only restorable together with the storage tree and the **KMS key
> material** that existed at *T*. Read the "KMS caveat" section before
> planning any restore — restoring Postgres alone will silently break 2FA,
> audit-chain verification, invitation tokens, and recording playback.

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

## 2. POSIX storage tree (recordings and artifacts)

### What lives under `STORAGE_ROOT`

Uploaded audio and other large application files live on the Lustre-backed
POSIX tree. Each recording's `path` column in Postgres is the storage key,
shaped as:

```
recordings/{project_id}/{dataset_id}/{recording_id}.wav
```

The same relative keys are resolved below `STORAGE_ROOT` in the API and every
worker. The OGG playback cache under `COMPRESSED_CACHE_DIR` is derived and may
be regenerated; the storage tree itself must be backed up.

### Backup — copy the Lustre tree

Quiesce API and workers, or take a filesystem snapshot that gives the
database and storage a common point in time. Copy the complete provisioned
storage tree, including `audit-log/`, with metadata preserved:

```bash
rsync -aHAX --numeric-ids \
  /data/storage/ /backup/echoroo/storage/
```

Do not treat the compressed cache as the source of recordings. It can be
omitted from the backup or copied separately as a disposable cache.

The PostgreSQL dump, storage-tree copy, and KMS backup must be labelled and
retained as one set from the same point in time. The database can reference a
storage key that does not exist yet if these are captured independently.

### Restore

```bash
rsync -aHAX --numeric-ids \
  /backup/echoroo/storage/ /data/storage/
```

Before starting the application, verify that the restored tree is owned by
UID/GID 1000, has the `.echoroo-storage` marker, and is readable and writable
by the application identity. Run the storage provisioner on an empty tree;
for a restored tree, use it to run the full readiness probe after confirming
that the marker is present.

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

In dev, LocalStack stores the KMS material in the separate
`ECHOROO_LOCALSTACK_DATA` volume. A fresh KMS volume must not be paired with
an old database: newly created keys cannot decrypt data written under the
previous keys. Therefore:

- **Back up the LocalStack KMS material together with Postgres and the
  storage tree**, as one consistent set.
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
4. **A recording plays (exercises storage)** — open a project, open a
   recording, confirm audio streams and the spectrogram renders. This proves
   the storage key in Postgres resolves to a real file in the restored tree.
5. **Audit chain verifies** — perform one audited action (e.g. an
   annotation) and confirm it is written without a chain error, proving the
   audit-chain HMAC key restored correctly.

If steps 3–5 fail while step 1 passes, the most likely cause is a
Postgres / storage / KMS snapshot mismatch — restore all three from the
**same point in time**.

---

## Related runbooks

- `docs/runbook/release_readiness.md` — pre-launch provisioning checklist.
- `docs/runbook/cmk_rotation.md` — rotating the KMS CMKs.
- `docs/runbook/dek_rewrap.md` — re-wrapping DEKs after key rotation.
- `CONFIGURATION.md` — environment variable reference.
