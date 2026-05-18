# Contract Reconciliation Checklist

**Date**: 2026-05-18
**Feature**: 010 Email Verification and Trusted Devices
**Owner task**: T016

Spec-local contract deltas live in `specs/010-email-verification-trusted-devices/contracts/`. Canonical contracts used by repository contract checks live under `specs/006-permissions-redesign/contracts/`. T016 must reconcile these before endpoint implementation proceeds.

## Canonical Files To Update

| Canonical file | Required change |
|----------------|-----------------|
| `specs/006-permissions-redesign/contracts/auth.yaml` | Add real verify-email response/error contract, add verify-email resend, add `trust_device` and `device_label` fields to 2FA challenge and TOTP setup confirm, add `trusted_device_created`, and add `login_state="complete"` branch for trusted-device login. |
| `specs/006-permissions-redesign/contracts/account.yaml` | Add account trusted-device list and revoke endpoints, or link to a new canonical account-security contract if the repository establishes one during T016. |
| `specs/006-permissions-redesign/contracts/README.md` | Update endpoint table, security matrix, public auth allowlist notes, and cookie notes for the trusted-device cookie. |
| `specs/006-permissions-redesign/contracts/trusted.yaml` | No direct trusted-device account contract should be mixed into project trusted-user invitation contracts unless T016 deliberately renames/splits the file to avoid ambiguity. |

## Required Contract Assertions

- `/web-api/v1/auth/verify-email` is public, pre-session, token-only, and returns success or audit-safe invalid/expired/reused failures.
- `/web-api/v1/auth/verify-email/resend` returns generic 202 and does not disclose account existence.
- `/web-api/v1/auth/login` has discriminator-compatible response variants for `2fa_setup_required`, `2fa_required`, and `complete`.
- `/web-api/v1/auth/2fa/challenge` and `/web-api/v1/auth/2fa/setup/totp/confirm` accept `trust_device` only on second-factor success paths.
- Trusted-device self-service endpoints are first-party session routes and require CSRF for state-changing revoke operations.
- `/api/v1/*` programmatic auth remains API-key only and does not expose trusted-device or BFF email-verification behavior.

## OpenAPI/Test Follow-up

T008 should add failing spec/010 contract expectations before T016 edits canonical files. After T016, run:

```bash
cd apps/api
uv run pytest tests/contract/test_openapi_diff.py tests/contract/test_auth_010_contract.py
```

## Reconciliation Done Criteria

- Spec-local delta files and canonical spec/006 files describe the same request/response fields.
- Security schemes match the BFF/API-key split documented in spec/006.
- No duplicated or conflicting endpoint definitions remain.
- Contract tests fail before implementation for missing runtime behavior, not because canonical YAML is stale.
