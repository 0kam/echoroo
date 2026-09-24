# Keyring operations runbook

**Status**: pre-launch
**Owner**: deployment maintainer (human action required)

This is the operator entry point for the local keyring used by the API and
Celery workers. The keyring file contains fresh 256-bit key material and must
be treated as a secret independently of the database and storage backups.

## Provision a deployment

1. Create the host directory and give it to the runtime UID. The file is
   deliberately outside the application storage tree:

   ```bash
   sudo install -d -o 1000 -g 1000 -m 0750 /etc/echoroo
   ```

2. From the repository root, create the ring with the admin-only Compose
   service. `create` refuses to overwrite an existing file and writes the
   result with mode `0400`:

   ```bash
   docker compose -f compose.dev.yaml run --rm keyring-admin \
     create /keyring/echoroo-keyring.json --prefix 2026-01
   docker compose -f compose.dev.yaml run --rm keyring-admin \
     check /keyring/echoroo-keyring.json
   ```

   The command creates `totp-wrap-2026-01`, `pii-hmac-2026-01`, and
   `audit-hmac-2026-01`. Do not print or copy the material into a ticket,
   shell history, log, or chat.

3. Set the selectors in `.env` to those IDs:

   ```dotenv
   ECHOROO_KEYRING_DIR=/etc/echoroo
   KEYRING_TOTP_KEY=totp-wrap-2026-01
   KEYRING_TOTP_KEY_VERSION=1
   KEYRING_PII_KEY=pii-hmac-2026-01
   KEYRING_AUDIT_KEY=audit-hmac-2026-01
   ```

   During a TOTP rotation, `_OLD` is a pair: set both
   `KEYRING_TOTP_KEY_OLD` and `KEYRING_TOTP_KEY_VERSION_OLD`, with a distinct
   positive version. `KEYRING_PII_KEY_V2` is optional. The application
   validates that every selected ID has the right purpose.

4. Before any selector or file activation, copy the whole keyring file and
   the selector configuration to the maintainer's offline password manager.
   Keep the two pieces together and label the key epochs and backup date.
   Never rely on a database backup as the keyring backup.

5. Confirm the VM backup boundary before production. File-level backups must
   exclude `/etc/echoroo`. If the provider makes VM or disk snapshots, put
   the keyring on a separate virtual disk excluded from those snapshots and
   confirm that memory snapshots are disabled. If no such controls exist,
   record that the whole-VM capture risk is accepted. Host swap must be
   encrypted or disabled.

6. Recreate every consumer after provisioning or changing the file/selectors;
   containers do not hot-reload the cached ring:

   ```bash
   docker compose -f compose.dev.yaml up -d --force-recreate \
     backend worker worker-cpu
   docker compose -f compose.dev.yaml exec backend \
     uv run python -m echoroo.scripts.keyring_activation_check
   ```

   Reopen traffic only when the activation check exits `0` and confirms the
   API and every worker loaded the same state. `/health/ready` exposes only
   the `keyring_state` digest; use the activation check and worker detail for
   the comparison.

## Activation barrier

Every keyring-content or selector change is a maintenance-window operation:

1. Stop `backend`, `worker`, and `worker-cpu`.
2. Change the file and `.env` selectors.
3. Recreate all three consumers with the command above.
4. Run `keyring_activation_check` and inspect its exit status.
5. Reopen the application only on exit `0`.

Do not perform a rolling activation. A worker that retains an old cached ring
must be stopped and recreated before traffic or queued work is resumed.

## TOTP rotation and DEK rewrap

Before activating a new TOTP key, add it to the ring and make an offline
backup of the complete updated file plus selector configuration. In a
maintenance window, select the new ID/version and retain the previous pair as
`_OLD`, then recreate all consumers and pass the activation check.

For example:

```bash
docker compose -f compose.dev.yaml run --rm keyring-admin add \
  /keyring/echoroo-keyring.json --purpose totp-wrap --id totp-wrap-2026-02
```

Run the rewrap with explicit source and target IDs and version numbers:

```bash
uv run --project apps/api python scripts/rewrap_dek.py \
  --source-key-id totp-wrap-2026-01 \
  --target-key-id totp-wrap-2026-02 \
  --old-version 1 \
  --new-version 2
```

Verify that no database row still has the old version and that login works.
In the next maintenance window, unselect `_OLD` and recreate all consumers
again. Keep the old material in the keyring for as long as any database
backup or archive can contain rows that need it; unselecting it is not
deleting it.

## PII and audit keys

To enable PII v2 dual-write, add a fresh `pii-hmac-<prefix>` key, back up the
ring offline, select it as `KEYRING_PII_KEY_V2`, and pass the activation
barrier. `KEYRING_PII_KEY` v1 remains selected indefinitely because historical
lookups, summaries, banners, and existing audit data still need it. There is
no completion mode and no v1 retirement step.

The audit key is pinned for the lifetime of the data. Do not rotate or delete
it as routine maintenance.

## Backup and restore test

The offline backup is the whole keyring file plus the selector configuration.
Restore both before bringing up consumers. With a restored database and
storage tree, verify all of the following before reopening traffic:

- decrypt one known TOTP secret and complete its 2FA check;
- verify the audit chain, including its links and MACs;
- check `/health/ready` and run `keyring_activation_check`.

A database, storage, or VM backup that does not include the matching keyring
epoch is not a usable restore set. File-level backup jobs must continue to
exclude `/etc/echoroo` because its copy is held offline separately.

## Key loss

Do not generate replacement keys and pretend that they restore old data. If
the ring is irretrievably lost:

- users must re-enrol 2FA after a new TOTP key is provisioned;
- historical PII lookups are lost;
- the audit chain cannot be verified or extended verifiably after the loss;
- do not restart the application without the required key epochs.

Verified archives remain the evidence for the period before the loss. A new
audit key does not safely restart the existing chain because this design has
no audit key-epoch boundary.

## Audit-key compromise

Preserve all archives and checkpoints that were verified before the
compromise, and record the incident. Replacing the audit key in place does
not make the existing chain verifiable under a new epoch. Rows written after
the compromise are treated as unverified until a future key-epoch design
provides a supported boundary; do not claim that a new key repairs the old
chain.
