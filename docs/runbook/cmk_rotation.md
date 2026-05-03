# Runbook: CMK Rotation & Deletion (Phase 17 A-1 / T977)

This runbook documents the operational procedures for rotating and deleting
AWS KMS Customer Master Keys (CMKs) used by Echoroo for envelope encryption
of TOTP secrets, audit chain hashing, PII hashing, and invitation HMACs.

The 30-day pre-flight check below is enforced in code by
[`echoroo.core.kms_ops.schedule_cmk_deletion`](../../apps/api/echoroo/core/kms_ops.py).

## CMK rotation

Annual CMK rotation is the default for all CMK aliases used by the
application (`alias/echoroo-totp-dek`, `alias/echoroo-pii-hash`,
`alias/echoroo-audit-chain`, `alias/echoroo-invitation-hmac`).

Rotation steps:

1. Confirm the new key has been created and tagged with the same alias
   suffix plus a date-stamped suffix (e.g. `alias/echoroo-totp-dek-2026q2`).
2. Run the dual-write rewrap batch for any DEKs wrapped by the previous CMK.
3. Verify metric `dek_rewrap_failure_total` is zero for 24 hours after the
   batch completes.
4. Update the alias to point at the new key.
5. Wait at least 30 days before scheduling the previous key for deletion
   (see "CMK deletion 30-day pre-flight check" below).

## CMK deletion 30-day pre-flight check

AWS KMS allows `PendingWindowInDays` between 7 and 30. The Echoroo runbook
**MANDATES** a minimum of 30 days so the on-call team has time to detect
and cancel an accidental deletion before the key (and the data it
encrypts) is destroyed permanently.

Before scheduling any CMK deletion:

1. Use `echoroo.core.kms_ops.schedule_cmk_deletion()` (NOT a raw boto3
   `kms_client.schedule_key_deletion(...)` call). The helper enforces
   the runbook minimum and emits a structured audit log entry.
2. The helper raises `CMKDeletionWindowError` (a subclass of
   `ValueError`) if `pending_window_in_days < 30`. The AWS API is NOT
   called in that case — no state is mutated.
3. Provide `operator=` (your SSO identity) and `reason=` (ticket or
   change-request URL) for audit traceability.
4. Confirm M-of-N approval (2 superusers) before invoking the helper —
   this is a procedural gate above the code-level guard.
5. After the AWS API call returns, monitor CloudTrail for the
   `ScheduleKeyDeletion` event and verify `PendingWindowInDays` matches
   what the helper requested.

Example invocation:

```python
from echoroo.core.kms_ops import schedule_cmk_deletion

response = schedule_cmk_deletion(
    key_id="alias/echoroo-totp-dek-2025q4",
    pending_window_in_days=30,
    operator="alice@echoroo.app",
    reason="CR-2026-0142 — retire q4 2025 TOTP DEK after annual rotation",
)
```

If the window is too short the helper raises:

```
CMKDeletionWindowError: CMK deletion rejected:
pending_window_in_days=7 is below the 30-day runbook minimum
(Echoroo §CMK rotation policy).
```

## Cancelling a scheduled deletion

If a deletion was scheduled in error, run `aws kms cancel-key-deletion
--key-id <id>` immediately and confirm the key returns to `Enabled`
state. Open an incident retrospective for any cancelled deletion to
identify the root cause (typo, missing approval, wrong key alias).

## References

- `apps/api/echoroo/core/kms_ops.py` — code-level guard implementation.
- `apps/api/tests/security/key_rotation/test_cmk_deletion_window_guard.py`
  — boundary tests (7 / 29 / 30 / >30 day windows).
- `specs/006-permissions-redesign/checklists/security.md` §"鍵ローテ SLA
  (Runbook)" — checklist row "CMK deletion window 30 日最低".
