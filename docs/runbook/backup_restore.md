# Backup & Restore Runbook

**Created**: 2026-07-06 (W5-6 operational readiness)
**Status**: pre-launch — development / evaluation stack
**Owner**: release driver (human action required for every item below)

This runbook covers backing up and restoring the stateful stores in the
Echoroo stack: **PostgreSQL** (all relational data), the **POSIX storage tree**
(recordings and artifacts), and the **local keyring** used to decrypt and
authenticate protected data. Redis is covered last because it is almost
entirely ephemeral.

It is grounded in the shipped development stack (`compose.dev.yaml`):

| Store | Service / container | Image | Volume / path | Notes |
|-------|--------------------|-------|--------|-------|
| PostgreSQL | `echoroo-db` | `pgvector/pgvector:pg16` | `echoroo-dev-db` | pgvector enabled |
| POSIX storage (dev) | API + workers | Echoroo containers | Compose `backend-data` named volume → `/data/storage` | `STORAGE_ROOT`; recordings and artifacts |
| POSIX storage (production example) | API + workers | Echoroo containers | `/lustre/echoroo/storage` → `/data/storage` | Example Lustre host directory; `STORAGE_ROOT` |
| Local keyring | `keyring-admin` plus runtime consumers | Echoroo API image | `/etc/echoroo/echoroo-keyring.json` on the host | Backed up offline, never with the database |
| Redis | `echoroo-redis` | `redis:7-alpine` | `echoroo-dev-redis` | TLS + AUTH + ACL |

> **The durable stores are related but are not backed up identically.** The
> PostgreSQL dump and POSIX storage tree must describe the same point in time.
> The matching keyring file and selector configuration are retrieved separately
> from the maintainer's offline password manager. Never place the keyring in a
> database backup, storage archive, or routine VM backup.

---

## 1. PostgreSQL

All relational data lives in the `echoroo` database on the `echoroo-db`
container: users, projects, datasets, recordings metadata, annotations,
detections, embeddings (pgvector), audit log, and the **wrapped TOTP DEKs**
(encrypted per-user 2FA secrets).

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
rest. Label the dump with the matching POSIX storage-tree snapshot time, but
keep the keyring backup in the maintainer's password manager.

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

### Backup — development named volume

In the development stack, `/data/storage` exists inside the Compose
`backend-data` named volume; `/data/storage` is not a host directory. Run the
following on the Docker host from the directory where the backup should be
written. The volume is named `echoroo-dev-data` (`volumes.backend-data.name`
in `compose.dev.yaml`), independent of the Compose project name.

```bash
docker run --rm \
  -v "echoroo-dev-data:/data:ro" \
  -v "$PWD:/backup" \
  alpine:3.20 tar -C /data/storage --numeric-owner -czf \
  /backup/echoroo-storage-$(date +%F_%H%M%S).tar.gz .
```

### Backup — production Lustre host directory

Quiesce API and workers, or take a filesystem snapshot that gives the
database and storage a common point in time. Copy the complete provisioned
storage tree, including `audit-log/`, with metadata preserved:

```bash
rsync -aHAX --numeric-ids \
  /lustre/echoroo/storage/ /backup/echoroo/storage/
```

Do not treat the compressed cache as the source of recordings. It can be
omitted from the backup or copied separately as a disposable cache.

The PostgreSQL dump and storage-tree copy must be labelled and retained as one
set from the same point in time. The matching keyring epoch is restored from
the offline password-manager copy, never from that set.

### Restore

#### Development named volume

Stop the backend and workers on the Docker host first. Then, still on the
Docker host, restore into the named volume `echoroo-dev-data`
(`volumes.backend-data.name` in `compose.dev.yaml`); the archive contents
become `/data/storage` inside the containers.

```bash
docker run --rm \
  -v "echoroo-dev-data:/data" \
  -v "$PWD:/backup" \
  alpine:3.20 sh -c \
  'mkdir -p /data/storage && tar -xzf /backup/echoroo-storage-2026-07-06_120000.tar.gz -C /data/storage'
```

#### Production Lustre host directory

On the production Docker host, after the application is quiesced and the
example Lustre directory is mounted at `/lustre/echoroo/storage`:

```bash
rsync -aHAX --numeric-ids \
  /backup/echoroo/storage/ /lustre/echoroo/storage/
```

Before starting the application, verify that the restored tree is owned by
UID/GID 1000, has the `.echoroo-storage` marker, and is readable and writable
by the application identity. Run the storage provisioner inside the backend
container on an empty dev tree, or use the production compose service against
the mounted Lustre path, so it runs as UID 1000 and performs the full
readiness probe after confirming that the marker is present:

```bash
cd /path/to/echoroo
docker compose -f compose.dev.yaml run --rm backend uv run python -m \
  echoroo.scripts.provision_storage /data/storage
```

---

## 3. Local keyring — read this before restoring (CRITICAL)

The local keyring contains the selected material for TOTP wrapping, PII HMACs,
and the audit chain. The database stores wrapped TOTP DEKs, keyed hashes, and
audit MACs that depend on the matching key epochs. Read
[keyring.md](keyring.md) for provisioning, selectors, rotation, activation,
loss handling, and the complete restore procedure.

The backup rule is deliberately separate from the database and storage rules:

- Back up the **whole** `echoroo-keyring.json` file together with its selector
  configuration (`KEYRING_*` and `ECHOROO_KEYRING_DIR`) to the maintainer's
  offline password manager.
- Make that offline copy before activating a new key or selector. Keep old
  key material while any database backup or archive can contain data that
  needs it.
- Never copy the keyring into the PostgreSQL backup, POSIX storage archive,
  normal host file backup, or a VM/disk snapshot. File-level backup jobs must
  exclude `/etc/echoroo`.
- During restore, retrieve the matching keyring epoch and selectors from the
  password manager before recreating the API or workers. Do not generate new
  keys to make an old database appear usable.

After restoring the database, storage tree, keyring file, and selectors, run
the activation check from [keyring.md](keyring.md). Then test the restored
cryptographic state by decrypting one known TOTP secret and completing its 2FA
check, followed by the audit-chain verifier:

```bash
docker compose -f compose.dev.yaml exec backend \
  uv run python -m echoroo.scripts.verify_audit_chain \
  --table both --check-detects-deleted-row
```

If the TOTP check or audit verification fails, stop traffic and restore the
matching keyring epoch and selectors. A new keyring cannot decrypt or verify
data written under a previous epoch.

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
3. **Keyring activation passes** — run the activation check from
   [keyring.md](keyring.md) with one expected count per running Celery worker.
4. **Login works** — log in with a real 2FA account in the browser. A
   successful TOTP challenge proves a restored wrapped DEK was decrypted with
   the matching keyring epoch.
5. **A recording plays** — open a project, open a recording, confirm audio
   streams and the spectrogram renders. This proves the storage key in
   Postgres resolves to a real file in the restored tree.
6. **Audit chain verifies** — run
   `python -m echoroo.scripts.verify_audit_chain` as shown in §3, including
   deleted-row detection, and confirm the restored chain is valid.

If steps 3–6 fail while step 1 passes, restore the PostgreSQL dump and storage
tree from the same point in time and retrieve the matching keyring epoch and
selectors from the offline password manager.

---

## Related runbooks

- `docs/runbook/keyring.md` — provision, activate, back up, restore, and
  rotate the local keyring.
- `docs/runbook/release_readiness.md` — pre-launch provisioning checklist.
- `CONFIGURATION.md` — environment variable reference.
