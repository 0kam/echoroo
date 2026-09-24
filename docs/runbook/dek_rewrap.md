# TOTP DEK rewrap pointer

> **Superseded in part:** the old external key-service procedure is replaced
> by the local keyring. See [keyring.md](keyring.md), the operator entry point.

Run TOTP rotation only in a maintenance window. Add the target key to the
ring, make the required offline backup, select the new key and retain the
source as the `_OLD` pair. Recreate `backend`, `worker`, and `worker-cpu`, then
run the activation check before serving traffic.

The rewrap command must name both key IDs and both versions explicitly:

```bash
uv run --project apps/api python scripts/rewrap_dek.py \
  --source-key-id totp-wrap-2026-01 \
  --target-key-id totp-wrap-2026-02 \
  --old-version 1 \
  --new-version 2
```

Verify that no row remains at the old version and test a real 2FA login. In a
later activation window, unselect `_OLD` but keep its material in the file
for as long as database backups require it. The complete procedure,
including rollback, restore, and loss handling, is in [keyring.md](keyring.md).
