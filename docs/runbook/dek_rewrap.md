# Runbook: TOTP DEK Rewrap & CMK Rotation (Phase 17 A-8)

This runbook covers rotation of the AWS KMS Customer Master Key (CMK)
that wraps every user's TOTP data encryption key (DEK). The rotation is
zero-downtime: the application can decrypt records under the **old**
CMK and the **new** CMK simultaneously during a grace window while the
runbook script `scripts/rewrap_dek.py` re-encrypts each DEK under the
new CMK using `kms:ReEncrypt` (the plaintext DEK never leaves AWS KMS,
satisfying FR-091b).

This runbook chains into:

* [`docs/runbook/cmk_rotation.md`](cmk_rotation.md) — the upstream
  per-CMK rotation procedure (alias renaming, 30-day deletion preflight).
* [`echoroo.core.kms_ops.schedule_cmk_deletion`](../../apps/api/echoroo/core/kms_ops.py)
  — the safe-deletion helper that enforces the runbook's 30-day window.

## Settings contract

The rotation is driven entirely by env vars (no source change required):

| Setting | Env var | Meaning |
|---|---|---|
| `two_factor_dek_cmk_alias_new` | `AWS_KMS_CMK_2FA_DEK_ALIAS_NEW` | Current CMK alias for newly encrypted TOTP DEKs. |
| `two_factor_dek_kid_new`       | `AWS_KMS_CMK_2FA_DEK_KID_NEW`   | Version stamped on `users.two_factor_secret_dek_version` for new writes. |
| `two_factor_dek_cmk_alias_old` | `AWS_KMS_CMK_2FA_DEK_ALIAS_OLD` | Previous CMK alias accepted during grace window (must be paired with `_KID_OLD`). |
| `two_factor_dek_kid_old`       | `AWS_KMS_CMK_2FA_DEK_KID_OLD`   | Previous version stamp routed to `_ALIAS_OLD`. |

The `validate_production_secrets` Pydantic validator rejects
half-configured grace windows (alias without kid or kid without alias)
in `staging` / `production` environments.

The decrypt-side routing lives in
`echoroo.services.two_factor_service._resolve_dek_alias_for_version`:

```
version == kid_new             → alias_new
version == kid_old (paired)    → alias_old
otherwise                      → TwoFactorError("DEK version ... not configured")
```

When the application sees a version it does not recognise (e.g. an
operator unset the `_OLD` pair before all records were rewrapped) it
fails closed with an explicit error pointing at this runbook.

## Rotation procedure

### Phase 1 — Preflight (T-7d)

1. Decide on the new CMK alias suffix (e.g. `alias/echoroo-totp-dek` —
   AWS supports re-pointing aliases atomically) and the new version
   number (current `kid_new + 1`, e.g. 1 → 2).
2. Verify monitoring captures `dek_rewrap_failure_total` (per-batch
   `failed` count emitted by `scripts/rewrap_dek.py`). Until the
   metric is wired, dashboard the script's stderr in your batch
   runner.
3. Confirm a recent DB backup exists. The rewrap is non-destructive
   (CAS-guarded UPDATE; ciphertext is replaced atomically), but a
   point-in-time snapshot lets you roll back the DEK *version stamp*
   and re-decrypt from backup without coordinating with KMS.

### Phase 2 — Create the new CMK (T-2d)

1. Create the new SYMMETRIC_DEFAULT CMK in the same AWS region.
2. Create a *temporary* alias for the new CMK
   (e.g. `alias/echoroo-totp-dek-new`).
3. **Do not** re-point the production alias yet.

### Phase 3 — Enter the grace window (T-0)

1. Re-point the existing alias for the OLD CMK to a side alias
   (e.g. `alias/echoroo-totp-dek-old`).
2. Re-point the production alias to the new CMK.
3. Update env vars in the deployment (rolling restart):

   ```
   AWS_KMS_CMK_2FA_DEK_ALIAS_NEW=alias/echoroo-totp-dek
   AWS_KMS_CMK_2FA_DEK_KID_NEW=2
   AWS_KMS_CMK_2FA_DEK_ALIAS_OLD=alias/echoroo-totp-dek-old
   AWS_KMS_CMK_2FA_DEK_KID_OLD=1
   ```

4. Verify a small sample of users can still complete 2FA login:
   their records carry `two_factor_secret_dek_version = 1` so the
   service routes the unwrap call to the OLD alias, while any new
   2FA enrollment writes a record with version 2 wrapped under the
   NEW alias.

### Phase 4 — Run the rewrap (T-0 + 1h)

```
uv run --project apps/api python scripts/rewrap_dek.py \
    --source-alias alias/echoroo-totp-dek-old \
    --destination-alias alias/echoroo-totp-dek \
    --old-version 1 \
    --new-version 2 \
    --dry-run
```

Review the dry-run output. Then:

```
uv run --project apps/api python scripts/rewrap_dek.py \
    --source-alias alias/echoroo-totp-dek-old \
    --destination-alias alias/echoroo-totp-dek \
    --old-version 1 \
    --new-version 2 \
    --confirm
```

Each batch prints a summary like:

```
Batch 1: {'processed': 100, 'rewrapped': 100, 'skipped': 0, 'failed': 0}
```

* `rewrapped`: rows successfully re-encrypted under the new CMK.
* `skipped`: rows whose optimistic CAS guard tripped (a concurrent 2FA
  enrollment / reset moved the record). The next batch picks these up
  if their version is still `--old-version`; otherwise they were
  written fresh under `--new-version` and need no rewrap.
* `failed`: KMS rewrap raised. Investigate before continuing.

**Exit codes:**

* `0` — convergence reached (no rows left at `--old-version`) and all
  rewrapped rows succeeded.
* `1` — at least one row's KMS `ReEncrypt` raised. Investigate the
  ``ERROR user_id=...`` lines on stderr before re-running.
* `2` — `--max-batches` was exhausted before convergence. Some rows
  at `--old-version` are still un-rewrapped. Re-run with a higher
  `--max-batches` (or rely on the next cron tick).

### Phase 5 — Exit the grace window (T+24h)

1. Confirm `SELECT count(*) FROM users WHERE two_factor_secret_dek_version = 1
   AND two_factor_secret_encrypted IS NOT NULL` returns 0.
2. Unset the `_OLD` env vars in the deployment:

   ```
   AWS_KMS_CMK_2FA_DEK_ALIAS_OLD=
   AWS_KMS_CMK_2FA_DEK_KID_OLD=
   ```

   With both unset the `validate_production_secrets` guard is happy
   (the half-configured guard only fires when *one* of the pair is set).

3. Roll the deployment.

### Phase 6 — Schedule old CMK deletion (T+30d)

Use [`echoroo.core.kms_ops.schedule_cmk_deletion`](../../apps/api/echoroo/core/kms_ops.py)
to schedule the old CMK for deletion. The helper enforces the runbook's
30-day pre-flight window (see `docs/runbook/cmk_rotation.md`).

## Race conditions and edge cases

### In-flight 2FA verification during rewrap

The script's optimistic UPDATE (`WHERE id = :id AND
two_factor_secret_dek_version = :old_version AND
two_factor_secret_encrypted = :old_payload`) loses to any concurrent
mutation. Concretely:

* User logs in mid-rewrap → service decrypts using the **OLD** alias
  (the user's row still says version 1) → succeeds.
* User re-enrolls mid-rewrap → service writes a new row under the NEW
  alias with version 2. The script's CAS guard then fails for that row
  (payload no longer matches), the row is reported `skipped`, and a
  re-run picks up no rows for that user (already at version 2).

### Decrypt-time routing during a deploy roll

Because the `_OLD` env vars must be set on every API replica BEFORE the
new CMK alias is moved, a partial roll could leave a replica without
`_OLD` configured while a record carrying version 1 hits it. That
replica responds with `TwoFactorError("DEK version 1 is not configured
for decryption — operator must run scripts/rewrap_dek.py before
removing the prior CMK alias from settings")`. Affected users see a
generic 5xx; rolling forward fixes them. To avoid this, always set the
`_OLD` env vars on all replicas BEFORE re-pointing the production
alias.

## Rollback

If monitoring shows a spike in 2FA decrypt errors after Phase 3:

1. Re-point the production alias back at the OLD CMK.
2. Restore the env vars to the pre-rotation values:
   ```
   AWS_KMS_CMK_2FA_DEK_ALIAS_NEW=alias/echoroo-totp-dek
   AWS_KMS_CMK_2FA_DEK_KID_NEW=1
   AWS_KMS_CMK_2FA_DEK_ALIAS_OLD=
   AWS_KMS_CMK_2FA_DEK_KID_OLD=
   ```
3. Roll the deployment.

If rewrap has already started writing version 2 records, run the
script in reverse to bring them back to version 1:

```
uv run --project apps/api python scripts/rewrap_dek.py \
    --source-alias alias/echoroo-totp-dek \
    --destination-alias alias/echoroo-totp-dek-old \
    --old-version 2 \
    --new-version 1 \
    --confirm
```

## Why `kms:ReEncrypt` and not `Decrypt + Encrypt`

The application never sees the plaintext DEK during a rewrap. Calling
`Decrypt` followed by `Encrypt` would briefly load the plaintext DEK
into application memory, where a process dump or crash could leak it.
`kms:ReEncrypt` performs both operations entirely inside KMS — the
plaintext DEK never crosses the network or enters application memory.
This is the FR-091b ("KMS isolation") guarantee that
`scripts/lint_kms_isolation.py` enforces statically.

## See also

* `apps/api/echoroo/core/kms.py` — `wrap_dek`, `unwrap_dek`, `rewrap_dek`.
* `apps/api/echoroo/services/two_factor_service.py` —
  `_resolve_dek_alias_for_version`, `_current_dek_version`.
* `apps/api/tests/security/crypto/test_dek_rewrap_and_kms_isolation.py`
  — moto-based roundtrip tests.
* `apps/api/tests/unit/services/test_two_factor_service.py` —
  routing-only unit tests with a stubbed `Settings`.
