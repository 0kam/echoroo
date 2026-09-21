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
| Tamper **evidence** | Every audit row carries `row_hash = HMAC-SHA256(KMS audit-chain key, prev_hash ‖ canonical row)` and `prev_hash` = the previous row's `row_hash`. Verification checks both: a changed row fails its MAC, a removed or reordered row breaks a link. The key never leaves KMS. |
| One archive per closed ISO week | `audit-log/<table>/<ISO year>/<ISO week>.ndjson` holds exactly the rows with `Monday 00:00 UTC <= created_at < next Monday 00:00 UTC`. The current week is never exported, so the contents of a key are deterministic. |
| Write-once | The export never overwrites or deletes an archive. Runs are serialised by a PostgreSQL advisory lock, so two runs cannot race on a key. |
| Verified on write, re-audited weekly | Rows are verified against the chain before writing and the stored bytes are compared with them afterwards. On every later run, each archive still inside the 8-week window is compared byte for byte with the live table again. A row that lands in a week after it was archived (late commit, backdated timestamp) or an archive replaced in storage **fails the task** instead of passing unnoticed. |
| Catch-up | Each run looks back 8 closed weeks and exports any week that has rows but no archive. A missed Monday heals itself on the next run. |

Schedule: Celery beat `audit-log-weekly-export`, Mondays 03:00 UTC, `default`
queue (`apps/api/echoroo/workers/celery_app.py`). The task does not retry by
itself; a failed run is picked up by the next one.

## What the application does NOT guarantee

S3 Object Lock is gone (it does not exist on a POSIX filesystem). Nothing in
the application stops someone with write access to the storage root from
replacing or deleting an archive. What is detectable, and how:

| Change to an archive | Detected by |
| --- | --- |
| Row edited, row removed from the middle, rows reordered, file emptied or garbled, archive copied to another week's key | `verify_archive` on the file alone |
| Any change at all, while the week is within 8 weeks | the weekly run (byte comparison with the live table) |
| Rows cut off the **start** of the file, or the file replaced by a forged zero-hash bootstrap row | `verify_archive(..., expected_prev_hash=<last row_hash of the preceding archive>)` |
| Rows cut off the **end** of the file | the same check run on the *next* week's archive |
| Whole file deleted | within 8 weeks it is silently **recreated** from the live table (identical bytes); after that, only a snapshot or a gap in the key listing shows it |

In short: a single archive proves its rows are genuine; only the sequence of
archives (or a snapshot) proves nothing is missing. That is why snapshots matter. Immutability is therefore an
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
naming the first bad row or broken link. Use `include_project_id=False` for
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

`AuditChainMismatchError: N week(s) failed the audit export: <keys>` — the
worker log has one `audit export failed key=… : <reason>` line per week:

- `live table: …` — the live rows of that week fail verification. The week is
  not archived.
- `archive differs from the live table` — the archive exists but no longer
  matches: a row was added to that week after archiving, or the archive was
  changed in storage. Compare the two before deciding which one is right.
- `archive exists but the live table has no rows` — rows were deleted from the
  database.
- `ClientError: …` or another exception name — storage was unreachable or
  denied for that key; the week is retried by the next run.

Every other week in the run is still processed; nothing is ever overwritten. A week that stays
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
3. If the live chain is broken too, first rule out the benign causes above,
   then treat it as a security incident: the database was modified outside the
   application.

Bootstrap rows are not failures: the baseline migration's `genesis` rows and
the `platform.wipe_executed` row are inserted before the keyed hashers exist,
with all-zero hashes by design. The export accepts exactly those two actions
without a MAC, and only at the start of the chain (every week's first row must
link to the row before it, so a zero-hash row further along cannot link). Their
*contents* are not authenticated — that is inherent to bootstrap rows. The `chain-verify` endpoint does not know this exception and
reports them as mismatches.

## Wipe guard

`python -m echoroo.scripts.check_wipe_guard` looks for the genesis marker at
`audit-log/genesis/marker.json` in the same storage the export writes to, so
the marker is covered by the same read-only view and snapshots.
