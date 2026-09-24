# Keyring rotation pointer

> **Superseded in part:** the old external key-service procedure is replaced
> by the local keyring. See [keyring.md](keyring.md), the operator entry point.

There is no external master-key rotation or key-deletion schedule in the
current design. Follow the keyring runbook for the supported operations:

- rotate TOTP wrapping keys and rewrap rows with explicit key IDs;
- enable PII v2 dual-write while keeping the v1 key selected indefinitely;
- keep the audit key pinned for the lifetime of the data;
- back up the complete ring and selectors offline before activation.

Do not delete old key material while any database backup or archive may still
depend on it. Use the activation barrier to recreate every consumer and
compare the loaded state before reopening traffic.
