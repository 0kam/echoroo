# Audit Log Archive Runbook

**Created**: 2026-09-21 (storage migration slice 3)
**Status**: pre-launch
**Owner**: operations (human action required for the items marked **ops**)

The audit tables (`project_audit_log`, `platform_audit_log`) are exported
weekly to object storage as NDJSON archives (FR-095). This runbook says what
the application guarantees about those archives, what it does **not**, and
what operations must add so the archives stay immutable.

Design background: `docs/architecture/storage-lustre-migration.md`
(decision 1, slice 3).

## What the application guarantees

| Property | How |
| --- | --- |
| Tamper **evidence** | Every audit row carries `row_hash = HMAC-SHA256(KMS audit-chain key, prev_hash ‖ canonical row)`. Changing, dropping or reordering a row breaks verification. The key never leaves KMS. |
| One archive per closed ISO week | `audit-log/<table>/<ISO year>/<ISO week>.ndjson` holds exactly the rows with `Monday 00:00 UTC <= created_at < next Monday 00:00 UTC`. The current week is never exported, so the contents of a key are deterministic. |
| Write-once | The export skips any key that already exists. It never overwrites or deletes an archive. |
| Verified on write | Rows are verified against the chain before writing, and the archive is read back from storage and verified again before the run reports success. |
| Catch-up | Each run looks back 8 closed weeks and exports any week that has rows but no archive. A missed Monday heals itself on the next run. |

Schedule: Celery beat `audit-log-weekly-export`, Mondays 03:00 UTC, queue
`worker-cpu` (`apps/api/echoroo/workers/celery_app.py`).

## What the application does NOT guarantee

S3 Object Lock is gone (it does not exist on a POSIX filesystem). Nothing in
the application stops someone with write access to the storage root from
replacing or deleting an archive. Replacement is **detectable** (verification
fails, because the attacker cannot mint valid MACs without the KMS key);
deletion is detectable only by noticing the gap. Immutability is therefore an
operational control — the next section.

## Operations: keeping archives immutable — **ops**

> **Open — needs facts about the Lustre service** (design doc, open decision 5).
> The two controls below are the agreed direction (decision 1, 2026-09-20);
> the concrete mechanism and schedule are filled in once we know what the
> filesystem offers.

1. **Read-only view.** After cutover the archives live under
   `<storage root>/audit-log/`. The application's service account is the only
   writer. Auditors and any second VM mount the filesystem **read-only**.
   - Mechanism: _TBD — read-only mount of the whole filesystem on the auditor
     VM, or a sub-directory export if the service supports it._
2. **Snapshots.** Periodic snapshots of `<storage root>/audit-log/`, retained
   for at least the audit retention period (3 years, FR-095), stored where
   the application's service account cannot delete them.
   - Mechanism and schedule: _TBD — filesystem-level snapshots if offered;
     otherwise a weekly `rsync --ignore-existing` to a location owned by a
     different account, run after the Monday export._

Until cutover (slice 4) the archives are in the S3 bucket `S3_BUCKET` under the
same `audit-log/` prefix; the same keys become the same relative paths.

## Verifying an archive

From a worker container (needs KMS access):

```bash
docker exec echoroo-worker-cpu-1 uv run python -c "
from echoroo.workers.audit_log_export import verify_archive
print(verify_archive('audit-log/project_audit_log/2026/38.ndjson', include_project_id=True))
"
```

Prints the number of verified rows, or raises `AuditArchiveMismatchError`
naming the first bad row. Use `include_project_id=False` for
`platform_audit_log`.

To verify the live tables instead of an archive:
`POST /web-api/v1/admin/audit-log/chain-verify?target=project` (or
`target=platform`), as a platform admin. There is no UI for it yet.

## Running the export by hand

```bash
docker exec echoroo-worker-cpu-1 uv run python -c "
from echoroo.workers.audit_log_export import export_weekly
print(export_weekly())
"
```

Safe to repeat: existing archives are skipped.

## When the export task fails

`AuditChainMismatchError: refused to archive N week(s) with a broken chain: <keys>`
means the **live table** failed verification for those weeks. The export never
archives such a week, and still archives every clean week in the same run.
Verify the live table (above) to find the first bad row. A week that stays
broken for more than 8 weeks falls out of the catch-up window and must be
exported by hand once resolved (`export_weekly(now_iso=...)` with a `now`
inside the window).

Known benign cause in **development only**: rows written while the KMS key
differed — LocalStack key regeneration before 2026-07-07 (PR #246), or a
pytest run inside the dev container whose fresh-session audit writers reach
the dev database with the test KMS key. Production has neither.

## When verification fails

1. Do not delete or "fix" the archive. Copy it aside.
2. Verify the live table (above). If the live chain is intact, the archive was
   altered in storage: restore that key from the most recent snapshot that
   verifies, and investigate who had write access.
3. If the live chain is broken too, treat it as a security incident: the
   database was modified outside the application.

## Wipe guard

`python -m echoroo.scripts.check_wipe_guard` looks for the genesis marker at
`audit-log/genesis/marker.json` in the same storage the export writes to, so
the marker is covered by the same read-only view and snapshots.
